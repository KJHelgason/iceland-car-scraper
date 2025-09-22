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
def remove_exact_duplicates(session: Session) -> int:
    print("[Duplicates] Checking for duplicates...")
    rows = session.execute(
        select(
            CarListing.make, CarListing.model, CarListing.year,
            CarListing.price, CarListing.kilometers, CarListing.source,
            func.count(CarListing.id)
        ).group_by(
            CarListing.make, CarListing.model, CarListing.year,
            CarListing.price, CarListing.kilometers, CarListing.source
        ).having(func.count(CarListing.id) > 1)
    ).all()

    print(f"[Duplicates] Found {len(rows)} duplicate groups.")
    deleted = 0
    for (make, model, year, price, km, source, cnt) in rows:
        print(f"  - Processing dup group: {make} {model} {year}, {price} ISK, {km} km, source={source}, count={cnt}")
        dups = session.execute(
            select(CarListing).where(
                CarListing.make == make,
                CarListing.model == model,
                CarListing.year == year,
                CarListing.price == price,
                CarListing.kilometers == km,
                CarListing.source == source
            ).order_by(
                nullslast(CarListing.scraped_at.desc()),
                CarListing.id.desc()
            )
        ).scalars().all()

        keep = dups[0]
        to_delete = dups[1:]
        for row in to_delete:
            session.delete(row)
            deleted += 1
            print(f"    [x] Deleted duplicate id={row.id}, url={row.url}")
    session.commit()
    print(f"[Duplicates] Removed {deleted} exact duplicates.")
    return deleted

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
    Visit each Bilasólur row with null price; update if price found; otherwise delete
    if the row is still incomplete. Commits in batches to avoid huge transactions
    and recovers from transient DB connection drops.
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
                if not is_full_row(c):
                    print("    [x] Deleted row (dead + incomplete).")
                    session.delete(c); deleted += 1
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
                if not is_full_row(c):
                    print("    [x] Deleted row (still null price + incomplete).")
                    session.delete(c); deleted += 1
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

    # 2) Fix Bilasólur null prices (update if price exists, delete if dead+incomplete)
    fixed_or_deleted = fix_bilasolur_null_prices()

    # 3) Now that prices are filled where possible, remove exact duplicates
    session = SessionLocal()
    try:
        removed_dups = remove_exact_duplicates(session)
    finally:
        session.close()

    # 4) Prune dead listings

    # A) Full Bilasólur sweep (keeps full rows and marks them inactive)
    bilasolur_dead_actions = prune_bilasolur_dead_listings_all(
        select_window=500,
        commit_batch=100,
        only_incomplete=True
    )

    # B) Full Bilaland sweep (similar logic)
    bilaland_dead_actions = prune_bilaland_dead_listings_all(
        select_window=500,
        commit_batch=100,
        only_incomplete=True
    )

    # C) Facebook listings validation
    fb_actions = validate_facebook_listings(limit=200)

    print("=== Cleaning summary ===")
    print(f"  - Non-cars removed: {removed_non_cars}")
    print(f"  - Bilasólur null price fixes/deletions: {fixed_or_deleted}")
    print(f"  - Duplicates removed: {removed_dups}")
    print(f"  - Bilasólur dead listings actions (inactive/deleted): {bilasolur_dead_actions}")
    print(f"  - Bilaland dead listings actions (inactive/deleted): {bilaland_dead_actions}")
    print(f"  - Facebook listings validated: {fb_actions}")


if __name__ == "__main__":
    run_all_cleaners()
