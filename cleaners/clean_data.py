import asyncio
import re
from datetime import datetime
from typing import Optional

from sqlalchemy import select, func, desc, nullslast
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError  # <-- for resilient commits

from db.db_setup import SessionLocal
from db.models import CarListing
from utils.normalizer import normalize_make
from utils.s3_cleanup import delete_s3_image

# ----------------------------
# Whitelist of known car makes
# ----------------------------
KNOWN_CAR_MAKES = {
    "toyota","volkswagen","vw","skoda","audi","seat",
    "bmw","mercedes-benz","mercedes","mb","mini",
    "ford","chevrolet","chevy","opel","vauxhall",
    "peugeot","citroen","renault","dacia","fiat",
    "kia","hyundai","mazda","nissan","honda","mitsubishi",
    "subaru","suzuki","volvo","saab",
    "tesla","lexus","infiniti","acura","lincoln","cadillac",
    "alfa romeo","jaguar","land rover","range rover",
    "jeep","porsche","maserati", "ram","dodge","gmc",
    "iveco","man","aiways","byd","nio","xpeng",
    "geely","great wall","haval","wey","ora","mg","saic",
    "polestar","lynk & co","lynk-co","zeekr","hongqi","roewe",
    "wuling","smart","ds","cupra","baic","maxus",
    "leapmotor","seres","voyah", "capron", "chrysler",
    "citröen", "hummer", "isuzu", "porsche", "ssangyong",
    "weinsberg"
}
NORMALIZED_MAKE_WHITELIST = {normalize_make(m) for m in KNOWN_CAR_MAKES if normalize_make(m)}

# Bilasölur detail page selectors
BILASOLUR_PRICE_XPATH = '/html/body/form/div[7]/div/div[2]/div[9]/div/div[1]/span'
BILASOLUR_PRICE_CLASS = '.cd-price'

# Bilasölur "dead/sold/missing" banner
BILASOLUR_DEAD_BANNER_XPATH = 'xpath=/html/body/form/div[6]/div[2]'
BILASOLUR_DEAD_BANNER_TEXT = "Ökutæki gæti verið selt eða finnst ekki af öðrum ástæðum."

# Batch controls for the async null-price fixer
BATCH_SIZE = 100     # commit DB every N rows
PAGE_ROTATE = 300    # recreate Playwright page every N navigations

# ----------------------------
# Helpers
# ----------------------------
def is_full_row(c: CarListing) -> bool:
    return all([
        c.make, c.model, c.year is not None,
        c.price is not None, c.kilometers is not None
    ])

def parse_is_isk_price(text: str) -> Optional[int]:
    """Parse '1.280.000' -> 1280000"""
    if not text:
        return None
    clean = text.replace("\xa0"," ").replace("&nbsp;"," ")
    m = re.search(r"(\d[\d\. ]+)", clean)
    if not m:
        return None
    raw = m.group(1).replace(".","").replace(" ","")
    try:
        return int(raw)
    except ValueError:
        return None

def should_delete_as_non_car(make: Optional[str]) -> bool:
    if not make:
        return False
    nm = normalize_make(make)
    return nm is not None and nm not in NORMALIZED_MAKE_WHITELIST

# ----------------------------
# Duplicate removal
# ----------------------------
# Cross-source duplicate detection:
# - Group by: make, model_base (ignoring trim), year, price, km (NOT source)
# - This catches duplicates like "Santa Fe 2 7 V6" vs "Santa Fe"
# - Preference order when choosing which to keep:
#   1. Non-Bilasolur sources (dealer direct is more authoritative)
#   2. Longest model name (more detailed)
#   3. Newest scraped_at (most recent data)
#   4. Highest ID (tiebreaker)
# ----------------------------
def remove_exact_duplicates(session: Session) -> int:
    from utils.normalizer import model_base
    
    print("[Duplicates] Checking for cross-source duplicates (using model base)...")
    
    # Get all listings with computed model_base
    all_listings = session.execute(select(CarListing)).scalars().all()
    
    # Group by make, model_base, year, price, km
    from collections import defaultdict
    groups = defaultdict(list)
    
    for listing in all_listings:
        if not all([listing.make, listing.model, listing.year, listing.price, listing.kilometers]):
            continue
        
        base = model_base(listing.model)
        if not base:
            continue
            
        key = (listing.make, base, listing.year, listing.price, listing.kilometers)
        groups[key].append(listing)
    
    # Find groups with multiple listings
    duplicate_groups = {k: v for k, v in groups.items() if len(v) > 1}
    
    print(f"[Duplicates] Found {len(duplicate_groups)} duplicate groups (cross-source, by model base).")
    deleted = 0
    
    for (make, base, year, price, km), dups in duplicate_groups.items():
        print(f"  - Processing dup group: {make} {base} {year}, {price} ISK, {km} km, count={len(dups)}")
        
        # Sort to determine which to keep
        # Priority: non-Bilasolur > longer model name > newer scraped_at > higher ID
        sorted_dups = sorted(dups, key=lambda x: (
            x.source != 'Bilasolur',  # Non-Bilasolur first (True > False)
            len(x.model or ''),  # Longer model name (more detailed)
            x.scraped_at or datetime.min,  # Newer scraped_at
            x.id or 0  # Higher ID
        ), reverse=True)
        
        keep = sorted_dups[0]
        to_delete = sorted_dups[1:]
        
        if to_delete:
            print(f"    ✓ Keeping: {keep.source} id={keep.id} model='{keep.model}'")
        
        for row in to_delete:
            # Delete S3 image if exists
            if row.image_url:
                delete_s3_image(row.image_url)
            session.delete(row)
            deleted += 1
            print(f"    ✗ Deleted: {row.source} id={row.id} model='{row.model}', url={row.url[:60]}...")
    
    session.commit()
    print(f"[Duplicates] Removed {deleted} exact duplicates (using model base, preferring detailed models).")
    return deleted


# ----------------------------
# Bilasölur cid duplicate removal
# ----------------------------
def extract_car_id(url: str) -> Optional[str]:
    """Extract the unique car ID (cid) from Bilasölur URLs."""
    if not url:
        return None
    match = re.search(r'[?&]cid=(\d+)', url)
    return match.group(1) if match else None


def remove_bilasolur_cid_duplicates(session: Session) -> int:
    """
    Remove duplicate Bilasölur listings with the same cid (car ID).
    Bilasölur URLs have dynamic params (schid, schpage) that change,
    but cid is the true unique identifier.
    """
    from collections import defaultdict
    
    print("[Bilasölur cid] Checking for Bilasölur duplicates by car ID...")
    
    # Get all active Bilasölur listings
    listings = session.execute(
        select(CarListing).where(
            CarListing.source == "Bilasolur",
            CarListing.is_active == True
        )
    ).scalars().all()
    
    print(f"[Bilasölur cid] Checking {len(listings)} active Bilasölur listings...")
    
    # Group by cid
    by_cid = defaultdict(list)
    
    for listing in listings:
        cid = extract_car_id(listing.url)
        if cid:
            by_cid[cid].append(listing)
    
    print(f"[Bilasölur cid] Found {len(by_cid)} unique car IDs")
    
    # Find duplicates (cids with multiple listings)
    duplicates = {cid: listings for cid, listings in by_cid.items() if len(listings) > 1}
    
    if not duplicates:
        print("[Bilasölur cid] No duplicates found!")
        return 0
    
    print(f"[Bilasölur cid] Found {len(duplicates)} car IDs with duplicates")
    
    total_deleted = 0
    
    for cid, dup_listings in duplicates.items():
        # Sort by scraped_at (most recent first), then by ID (highest first)
        sorted_listings = sorted(
            dup_listings,
            key=lambda x: (x.scraped_at if x.scraped_at else datetime.min, x.id),
            reverse=True
        )
        
        # Keep the first one (most recent)
        keep = sorted_listings[0]
        to_delete = sorted_listings[1:]
        
        print(f"  cid={cid}: Keeping id={keep.id}, deleting {len(to_delete)} duplicates")
        
        for listing in to_delete:
            # Delete S3 image if exists
            if listing.image_url:
                delete_s3_image(listing.image_url)
            session.delete(listing)
            total_deleted += 1
    
    session.commit()
    print(f"[Bilasölur cid] Removed {total_deleted} duplicate Bilasölur listings")
    return total_deleted


# ----------------------------
# Non-car removal
# ----------------------------
def remove_non_cars(session: Session) -> int:
    print("[Non-cars] Checking for non-car makes...")
    candidates = session.execute(
        select(CarListing).where(CarListing.make.isnot(None))
    ).scalars().all()
    print(f"[Non-cars] Found {len(candidates)} listings with a make.")

    removed = 0
    for c in candidates:
        if should_delete_as_non_car(c.make):
            print(f"  [x] Removing non-car listing id={c.id}, make={c.make}, url={c.url}")
            # Delete S3 image if exists
            if c.image_url:
                delete_s3_image(c.image_url)
            session.delete(c)
            removed += 1
    session.commit()
    print(f"[Non-cars] Removed {removed} listings not in whitelist.")
    return removed

# ----------------------------
# Bilasólur: fix null prices (BATCHED + resilient)
# ----------------------------
async def _fix_bilasolur_null_prices_async() -> int:
    """
    Visit each Bilasolur row with null price and try to update it.
    If we can't fill in the missing data, delete the incomplete listing (no value without the data).
    Complete listings are kept for ML even if marked inactive.
    Commits in batches to avoid huge transactions and recovers from transient DB connection drops.
    """
    from playwright.async_api import async_playwright

    def _get_candidates(sess: Session):
        # Pull only id + url to iterate robustly and re-fetch ORM rows by id as needed
        return sess.execute(
            select(CarListing.id, CarListing.url)
            .where(
                CarListing.source == "Bilasolur",
                CarListing.price.is_(None),
                CarListing.url.isnot(None)
            )
            .order_by(CarListing.id.asc())
        ).all()

    session = SessionLocal()
    candidates = _get_candidates(session)
    total = len(candidates)
    print(f"[Bilasolur null price] Found {total} rows with null price.")
    if not candidates:
        session.close()
        return 0

    fixed = deleted = processed = 0
    ops_since_commit = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        for idx, (cid, url) in enumerate(candidates, start=1):
            processed += 1
            if idx % 25 == 1 or idx == total:
                print(f"  - Progress: {idx}/{total} (fixed={fixed}, deleted={deleted})")

            # Rotate page periodically to avoid memory bloat/leaks
            if idx % PAGE_ROTATE == 0:
                try:
                    await page.close()
                except Exception:
                    pass
                page = await browser.new_page()

            # Re-fetch ORM row by id (fresh object each iteration)
            c = session.get(CarListing, cid)
            if not c:
                continue  # row may have been deleted elsewhere

            # Navigate to detail page
            try:
                await page.goto(url, timeout=30000)
            except Exception as e:
                print(f"    [!] Failed to load page: {e}")
                # Can't fill in data if page won't load - delete if incomplete
                if not is_full_row(c):
                    print("    [x] Deleted row (can't load + incomplete).")
                    if c.image_url:
                        delete_s3_image(c.image_url)
                    session.delete(c)
                    deleted += 1
                ops_since_commit += 1
                # Batch commit guard
                if ops_since_commit >= BATCH_SIZE:
                    try:
                        session.commit()
                    except OperationalError as oe:
                        print("    [DB] OperationalError on commit, retrying with fresh session…", oe)
                        session.rollback()
                        session.close()
                        session = SessionLocal()
                    ops_since_commit = 0
                continue

            # Try class selector first, then XPath
            price_val = None
            try:
                el = await page.query_selector(BILASOLUR_PRICE_CLASS)
                if el:
                    price_text = await el.inner_text()
                    price_val = parse_is_isk_price(price_text)
            except Exception:
                pass

            if price_val is None:
                try:
                    elx = await page.query_selector(f'xpath={BILASOLUR_PRICE_XPATH}')
                    if elx:
                        price_text = await elx.inner_text()
                        price_val = parse_is_isk_price(price_text)
                except Exception:
                    pass

            if price_val is not None:
                c.price = price_val
                c.scraped_at = datetime.utcnow()
                fixed += 1
                print(f"    [+] Updated id={c.id} price to {price_val} ISK")
            else:
                # Can't fill in the price - delete if incomplete (no value without the data)
                if not is_full_row(c):
                    print("    [x] Deleted row (still null price + incomplete).")
                    if c.image_url:
                        delete_s3_image(c.image_url)
                    session.delete(c)
                    deleted += 1
                # else keep complete row for modeling even if currently no price on page

            ops_since_commit += 1

            # Batch commit
            if ops_since_commit >= BATCH_SIZE:
                try:
                    session.commit()
                    print(f"    [DB] Committed batch at idx {idx} (fixed={fixed}, deleted={deleted})")
                except OperationalError as oe:
                    print("    [DB] OperationalError on commit, retrying with fresh session…", oe)
                    session.rollback()
                    session.close()
                    session = SessionLocal()
                ops_since_commit = 0

        # Final commit
        try:
            session.commit()
            print(f"    [DB] Final commit complete (fixed={fixed}, deleted={deleted}, processed={processed}).")
        except OperationalError as oe:
            print("    [DB] OperationalError on final commit, retrying with fresh session…", oe)
            session.rollback()
            session.close()
            session = SessionLocal()
            session.commit()

        await page.close()
        await browser.close()

    session.close()
    print(f"[Bilasolur null price] Done. Fixed {fixed}, deleted {deleted}, processed {processed}.")
    return fixed + deleted

def fix_bilasolur_null_prices() -> int:
    return asyncio.run(_fix_bilasolur_null_prices_async())

# ----------------------------
# Dead listing pruning (recent window, marks full rows inactive)
# ----------------------------
async def _prune_dead_listings_async(limit: int = 200) -> int:
    from playwright.async_api import async_playwright

    session = SessionLocal()
    candidates = session.execute(
        select(CarListing)
        .where(CarListing.url.isnot(None))
        .order_by(
            nullslast(CarListing.scraped_at.desc()),
            CarListing.id.desc()
        )
        .limit(limit)
    ).scalars().all()
    print(f"[Dead listings] Checking {len(candidates)} recent listings...")

    removed = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        for c in candidates:
            print(f"  - Visiting id={c.id}, source={c.source}, url={c.url}")
            is_dead = False
            try:
                await page.goto(c.url, timeout=25000)
                html = await page.content()

                if c.source == "Bilasolur":
                    has_price = await page.query_selector(BILASOLUR_PRICE_CLASS)
                    dead_node = await page.query_selector(BILASOLUR_DEAD_BANNER_XPATH)
                    dead_text = (await dead_node.inner_text()) if dead_node else ""
                    has_dead_banner = BILASOLUR_DEAD_BANNER_TEXT in dead_text

                    if (not has_price and 'class="cd-price"' not in html) or has_dead_banner:
                        is_dead = True

                elif c.source == "Bilaland":
                    if "kr." not in html and "carBox" not in html:
                        is_dead = True

                elif c.source == "Facebook Marketplace":
                    if "Marketplace" in (await page.title()) and "/marketplace/item/" not in page.url:
                        is_dead = True

            except Exception:
                print("    [!] Timeout or navigation error.")
                is_dead = True

            if is_dead:
                if is_full_row(c):
                    if c.is_active:
                        c.is_active = False
                        print("    [•] Marked dead (kept for modeling).")
                else:
                    if c.image_url:
                        delete_s3_image(c.image_url)
                    session.delete(c)
                    removed += 1
                    print("    [x] Deleted incomplete dead listing.")
            else:
                # Optional: revive listing if it came back alive
                if hasattr(c, "is_active") and not c.is_active:
                    c.is_active = True

        session.commit()
        await page.close()
        await browser.close()
    session.close()
    print(f"[Dead listings] Removed {removed} incomplete dead listings.")
    return removed

def prune_dead_listings(limit: int = 200) -> int:
    return asyncio.run(_prune_dead_listings_async(limit=limit))

# ----------------------------
# Full Bilasólur sweep: windowed by id to cover all rows safely
# ----------------------------
async def _prune_bilasolur_dead_listings_all_async(
    select_window: int = 500,   # how many rows to fetch per window
    commit_batch: int = 100,    # how many updates/deletes per commit
    only_incomplete: bool = True,  # skip deleting complete rows (always keep, mark inactive)
) -> int:
    from playwright.async_api import async_playwright
    from sqlalchemy import and_

    session = SessionLocal()

    def fetch_window(after_id: int | None):
        conds = [
            CarListing.source == "Bilasolur",
            CarListing.url.isnot(None),
        ]
        # If you want to scan everything, set only_incomplete=False from the caller
        if after_id is not None:
            conds.append(CarListing.id > after_id)

        rows = (
            session.execute(
                select(CarListing.id, CarListing.url)
                .where(and_(*conds))
                .order_by(CarListing.id.asc())
                .limit(select_window)
            )
            .all()
        )
        return rows

    last_id = None
    total_actions = 0  # deletes + inactivations
    ops_since_commit = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        while True:
            window = fetch_window(last_id)
            if not window:
                break

            print(f"[Dead listings ALL] Window starting after id={last_id or 0}, fetched={len(window)}")

            for cid, url in window:
                # refresh ORM row
                c = session.get(CarListing, cid)
                if not c:
                    last_id = cid
                    continue

                # If only_incomplete=True and row is full, we won't delete it, but we still may mark inactive
                is_dead = False
                try:
                    await page.goto(url, timeout=25000)
                    html = await page.content()

                    has_price = await page.query_selector(BILASOLUR_PRICE_CLASS)
                    dead_node = await page.query_selector(BILASOLUR_DEAD_BANNER_XPATH)
                    dead_text = (await dead_node.inner_text()) if dead_node else ""
                    has_dead_banner = BILASOLUR_DEAD_BANNER_TEXT in dead_text

                    if (not has_price and 'class="cd-price"' not in html) or has_dead_banner:
                        is_dead = True
                except Exception:
                    is_dead = True

                if is_dead:
                    if is_full_row(c):
                        # keep full rows, just mark inactive
                        if c.is_active:
                            c.is_active = False
                            total_actions += 1
                    else:
                        # delete only incomplete rows
                        if c.image_url:
                            delete_s3_image(c.image_url)
                        session.delete(c)
                        total_actions += 1
                else:
                    # alive: ensure active
                    if hasattr(c, "is_active") and not c.is_active:
                        c.is_active = True
                        total_actions += 1

                ops_since_commit += 1
                if ops_since_commit >= commit_batch:
                    try:
                        session.commit()
                        print("    [DB] Committed batch of updates/deletes.")
                    except OperationalError as oe:
                        print("    [DB] OperationalError on commit; refreshing session…", oe)
                        session.rollback()
                        session.close()
                        session = SessionLocal()
                    ops_since_commit = 0

                last_id = cid  # advance cursor

        # Final commit
        try:
            session.commit()
            print("    [DB] Final commit complete.")
        except OperationalError as oe:
            print("    [DB] OperationalError on final commit; retrying…", oe)
            session.rollback()
            session.close()
            session = SessionLocal()
            session.commit()

        await page.close()
        await browser.close()

    session.close()
    print(f"[Dead listings ALL] Actions (inactive or deleted): {total_actions}")
    return total_actions

def prune_bilasolur_dead_listings_all(select_window: int = 500, commit_batch: int = 100, only_incomplete: bool = True) -> int:
    return asyncio.run(_prune_bilasolur_dead_listings_all_async(
        select_window=select_window,
        commit_batch=commit_batch,
        only_incomplete=only_incomplete,
    ))

# ----------------------------
# Bilaland: full sweep dead/inactive pruning
# ----------------------------
async def _prune_bilaland_dead_listings_all_async(
    select_window: int = 500,
    commit_batch: int = 100,
    only_incomplete: bool = True,
) -> int:
    from playwright.async_api import async_playwright
    from sqlalchemy import and_

    session = SessionLocal()

    def fetch_window(after_id: int | None):
        conds = [CarListing.source == "Bilaland", CarListing.url.isnot(None)]
        if after_id is not None:
            conds.append(CarListing.id > after_id)

        rows = (
            session.execute(
                select(CarListing.id, CarListing.url)
                .where(and_(*conds))
                .order_by(CarListing.id.asc())
                .limit(select_window)
            )
            .all()
        )
        return rows

    last_id = None
    total_actions = 0
    ops_since_commit = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        while True:
            window = fetch_window(last_id)
            if not window:
                break

            print(f"[Bilaland dead listings] Window after id={last_id or 0}, fetched={len(window)}")

            for cid, url in window:
                c = session.get(CarListing, cid)
                if not c:
                    last_id = cid
                    continue

                is_dead = False
                try:
                    await page.goto(url, timeout=25000)
                    dead_node = await page.query_selector(
                        "xpath=/html/body/form/div[3]/div[3]/div/div/div/text()"
                    )
                    dead_text = (await dead_node.inner_text()) if dead_node else ""
                    if "Engar upplýsingar fundust um ökutæki" in dead_text:
                        is_dead = True
                except Exception:
                    is_dead = True

                if is_dead:
                    if is_full_row(c):
                        if c.is_active:
                            c.is_active = False
                            total_actions += 1
                    else:
                        if c.image_url:
                            delete_s3_image(c.image_url)
                        session.delete(c)
                        total_actions += 1
                else:
                    if hasattr(c, "is_active") and not c.is_active:
                        c.is_active = True
                        total_actions += 1

                ops_since_commit += 1
                if ops_since_commit >= commit_batch:
                    try:
                        session.commit()
                        print("    [DB] Committed batch of updates/deletes.")
                    except OperationalError as oe:
                        print("    [DB] OperationalError on commit; refreshing session…", oe)
                        session.rollback()
                        session.close()
                        session = SessionLocal()
                    ops_since_commit = 0

                last_id = cid

        try:
            session.commit()
            print("    [DB] Final commit complete.")
        except OperationalError as oe:
            session.rollback()
            session.close()
            session = SessionLocal()
            session.commit()

        await page.close()
        await browser.close()

    session.close()
    print(f"[Bilaland dead listings] Actions (inactive or deleted): {total_actions}")
    return total_actions

def prune_bilaland_dead_listings_all(
    select_window: int = 500,
    commit_batch: int = 100,
    only_incomplete: bool = True
) -> int:
    return asyncio.run(_prune_bilaland_dead_listings_all_async(
        select_window=select_window,
        commit_batch=commit_batch,
        only_incomplete=only_incomplete,
    ))

# ----------------------------
# Facebook: validate active/inactive
# ----------------------------
async def _validate_facebook_listings_async(limit: int = 200) -> int:
    from playwright.async_api import async_playwright

    session = SessionLocal()
    candidates = session.execute(
        select(CarListing)
        .where(CarListing.source == "Facebook Marketplace")
        .where(CarListing.url.isnot(None))
        .order_by(
            nullslast(CarListing.scraped_at.desc()),
            CarListing.id.desc()
        )
        .limit(limit)
    ).scalars().all()
    print(f"[Facebook validation] Checking {len(candidates)} listings...")

    actions = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        for c in candidates:
            print(f"  - Visiting Facebook id={c.id}, url={c.url}")
            is_dead = False
            try:
                await page.goto(c.url, timeout=20000)
                html = await page.content()

                # Facebook "no longer available" check
                if "no longer available" in html.lower() or "not available" in html.lower():
                    is_dead = True
                elif "Marketplace" in (await page.title()) and "/marketplace/item/" not in page.url:
                    is_dead = True

            except Exception:
                print("    [!] Timeout or navigation error.")
                is_dead = True

            if is_dead:
                if is_full_row(c):
                    if c.is_active:
                        c.is_active = False
                        actions += 1
                        print("    [•] Marked inactive (kept full row).")
                else:
                    if c.image_url:
                        delete_s3_image(c.image_url)
                    session.delete(c)
                    actions += 1
                    print("    [x] Deleted incomplete dead listing.")
            else:
                if hasattr(c, "is_active") and not c.is_active:
                    c.is_active = True
                    actions += 1
                    print("    [+] Revived to active.")

        session.commit()
        await page.close()
        await browser.close()
    session.close()
    print(f"[Facebook validation] Actions taken: {actions}")
    return actions

def validate_facebook_listings(limit: int = 200) -> int:
    return asyncio.run(_validate_facebook_listings_async(limit=limit))

# ----------------------------
# Orchestrator
# ----------------------------
def run_all_cleaners():
    print("=== Starting data cleaning pipeline ===")

    # 1) Remove obvious non-cars first (reduces work for later steps)
    session = SessionLocal()
    try:
        removed_non_cars = remove_non_cars(session)
    finally:
        session.close()

    # 2) Fix Bilasolur null prices (update if price found, delete if incomplete and can't fill)
    fixed_or_deleted = fix_bilasolur_null_prices()

    # 3) Remove Bilasölur cid duplicates (same car with different URL params)
    session = SessionLocal()
    try:
        removed_bilasolur_dups = remove_bilasolur_cid_duplicates(session)
    finally:
        session.close()

    # 4) Remove cross-source duplicates (Bilasölur copies of dealership listings)
    from cleaners.clean_cross_source_duplicates import remove_cross_source_duplicates
    removed_cross_source_dups = remove_cross_source_duplicates()

    # 5) Now that prices are filled where possible, remove exact cross-source duplicates
    session = SessionLocal()
    try:
        removed_exact_dups = remove_exact_duplicates(session)
    finally:
        session.close()

    # Note: Dead listing detection moved to check_oldest_listings.py (runs daily at 12:00)
    # Incomplete inactive listing deletion moved to delete_incomplete_listings.py (runs daily at 13:00)

    print("=== Cleaning summary ===")
    print(f"  - Non-cars removed: {removed_non_cars}")
    print(f"  - Bilasolur null price fixes/deletions: {fixed_or_deleted}")
    print(f"  - Bilasolur cid duplicates removed: {removed_bilasolur_dups}")
    print(f"  - Cross-source duplicates removed (Bilasölur copies): {removed_cross_source_dups}")
    print(f"  - Exact duplicates removed: {removed_exact_dups}")
    print(f"  - Note: Dead listing detection now handled by check_oldest_listings (12:00)")
    print(f"  - Note: Incomplete inactive deletion now handled by delete_incomplete_listings (13:00)")


if __name__ == "__main__":
    run_all_cleaners()
