import asyncio
import re
from datetime import datetime

from playwright.async_api import async_playwright, TimeoutError as PwTimeout
from db.db_setup import SessionLocal
from db.models import CarListing
from utils.normalizer import normalize_make, normalize_model, normalize_title, pretty_make, get_display_name
from utils.s3_uploader import download_and_upload_image

BASE_URL = "https://bilasolur.is/"

# Flag to enable/disable S3 uploads (set to False to keep old behavior)
USE_S3_STORAGE = True

# --- helpers ---------------------------------------------------------------

async def wait_for_results_or_empty(page, timeout_ms=15000) -> bool:
    """
    Returns True if we detect results (.sr-item) on the page, False if page looks empty.
    Never raises; handles empty results gracefully.
    """
    try:
        # let the page settle
        await page.wait_for_load_state("domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except PwTimeout:
            pass  # not all pages go idle; that's fine

        # quick progressive checks
        for _ in range(3):
            cards = await page.query_selector_all(".sr-item")
            if len(cards) > 0:
                return True
            # look for obvious empty states
            html = (await page.content()).lower()
            if ("engar niðurstöður" in html) or ("no results" in html):
                return False
            # sometimes content arrives after a scroll nudge
            await page.mouse.wheel(0, 2000)
            await asyncio.sleep(0.8)

        # last attempt: small explicit wait for a card
        try:
            await page.wait_for_selector(".sr-item", timeout=timeout_ms)
            return True
        except PwTimeout:
            return False
    except Exception:
        return False


def parse_int(text: str | None) -> int | None:
    if not text:
        return None
    try:
        return int(text)
    except Exception:
        return None


def extract_price(text: str | None) -> int | None:
    """
    From strings like 'kr. 2.990.000', 'Flott verð kr. 2.990.000 án vsk.' -> 2990000
    """
    if not text:
        return None
    text = text.replace("\xa0", " ").replace("&nbsp;", " ")
    # take the last big number we see
    m = re.findall(r"(\d[\d\. ]+)", text)
    if not m:
        return None
    raw = m[-1]
    try:
        return int(raw.replace(".", "").replace(" ", ""))
    except ValueError:
        return None


def extract_car_id(url: str) -> str | None:
    """
    Extract the unique car ID (cid) from Bilasölur URLs.
    Example: https://bilasolur.is/CarDetails.aspx?bid=76&cid=296487&sid=... -> '296487'
    This is the true unique identifier; other params (schid, schpage) vary by search context.
    """
    if not url:
        return None
    match = re.search(r'[?&]cid=(\d+)', url)
    return match.group(1) if match else None


def extract_kilometers(text: str | None) -> int | None:
    """
    Handles:
      - '45.000 km' -> 45000
      - '12 þ.km.' / '12 þ.km' / '12 þúsund km' -> 12000
    """
    if not text:
        return None
    t = text.lower().replace("\xa0", " ").replace("&nbsp;", " ")

    m_th = re.search(r"(\d+)\s*(þ\.?km|þúsund|þ\.km)", t)
    if m_th:
        try:
            return int(m_th.group(1)) * 1000
        except ValueError:
            pass

    m = re.search(r"([\d\.\s]+)\s*km", t, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1).replace(".", "").replace(" ", ""))
        except ValueError:
            return None

    return None

# --- main ------------------------------------------------------------------

async def scrape_bilasolur(max_pages: int = 3, start_urls: list[str] | None = None):
    """
    Scrape bilasolur.is result pages.
    - If start_urls is provided (e.g., from the seeder), we scrape those.
    - Otherwise we start at BASE_URL.
    - On each page we either scrape any .sr-item cards, or skip if empty.
    - We still follow additional SearchResults.aspx "Meira" links when present.
    """
    session = SessionLocal()
    new_listings = 0
    updated_listings = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        urls_to_scrape = list(start_urls) if start_urls else [BASE_URL]
        scraped_urls: set[str] = set()

        while urls_to_scrape:
            current_url = urls_to_scrape.pop(0)
            if current_url in scraped_urls:
                continue
            scraped_urls.add(current_url)

            print(f"Scraping: {current_url}")
            await page.goto(current_url)

            has_results = await wait_for_results_or_empty(page)
            if not has_results:
                print("  [i] No results found on this page. Skipping.")
                # Still try to pick up pagination links; some “empty” pages might still expose filters
                next_links = await page.query_selector_all('a[href*="SearchResults.aspx"]')
                for a in next_links:
                    href = await a.get_attribute("href")
                    if not href:
                        continue
                    if not href.startswith("http"):
                        href = f"https://bilasolur.is/{href.lstrip('/')}"
                    if href not in scraped_urls and href not in urls_to_scrape:
                        urls_to_scrape.append(href)
                if len(scraped_urls) >= max_pages:
                    break
                continue

            listings = await page.query_selector_all(".sr-item")
            print(f"Found {len(listings)} cars on this page")

            for item in listings:
                # Make/model/title
                make_el = await item.query_selector(".car-make")
                make_raw = (await make_el.evaluate("el => el.innerText.trim()")) if make_el else None

                model_el = await item.query_selector(".car-make-and-model")
                title_raw = (await model_el.evaluate("el => el.innerText.trim()")) if model_el else None

                model_raw = None
                if title_raw and make_raw and title_raw.upper().startswith(make_raw.upper()):
                    model_raw = title_raw[len(make_raw):].strip()

                # Normalize
                normalized_make = normalize_make(make_raw) if make_raw else None
                normalized_model = normalize_model(model_raw) if model_raw else None
                normalized_title = normalize_title(title_raw) if title_raw else None

                # URL
                link_el = await item.query_selector("a.sr-link")
                link = await link_el.get_attribute("href") if link_el else None
                if link and not link.startswith("http"):
                    link = f"https://bilasolur.is/{link.lstrip('/')}"
                if not link:
                    continue

                # Image URL
                image_url = None
                img_el = await item.query_selector("img.swiper-slide")
                if img_el:
                    img_src = await img_el.get_attribute("src")
                    if img_src:
                        if not img_src.startswith("http"):
                            temp_image_url = f"https://bilasolur.is/{img_src.lstrip('/')}"
                        else:
                            temp_image_url = img_src
                        
                        # Upload to S3 if enabled
                        if USE_S3_STORAGE:
                            try:
                                # We need listing ID for S3, so we'll upload after creating the listing
                                # For now, just store the temporary URL
                                image_url = temp_image_url
                            except Exception as e:
                                print(f"  ⚠ S3 upload failed, using temporary URL: {e}")
                                image_url = temp_image_url
                        else:
                            image_url = temp_image_url

                # Price
                price = None
                price_el = await item.query_selector(".car-price")
                if price_el:
                    price_text = await price_el.evaluate("el => el.innerText.trim()")
                    price = extract_price(price_text)

                # Tech details (year, km)
                year, kilometers = None, None
                tech_el = await item.query_selector(".tech-details")
                if tech_el:
                    tech_text = await tech_el.evaluate("el => el.innerText.trim()")
                    if tech_text:
                        ym = re.search(r"(19|20)\d{2}", tech_text)
                        if ym:
                            year = parse_int(ym.group(0))
                        if "km" in tech_text.lower():
                            kilometers = extract_kilometers(tech_text)

                # Extract the unique car ID from the URL
                # Bilasölur URLs have dynamic parameters (schid, schpage) that change,
                # but the cid (car ID) is the true unique identifier
                car_id = extract_car_id(link)
                
                # Check for existing listing by car_id (Bilasölur only)
                existing = None
                if car_id:
                    existing = (
                        session.query(CarListing)
                        .filter_by(source="Bilasolur")
                        .filter(CarListing.url.like(f'%cid={car_id}%'))
                        .first()
                    )
                
                # Fallback: check by URL if no car_id found
                if not existing:
                    existing = session.query(CarListing).filter_by(url=link).first()

                # Another fallback: same car details (for older listings without cid in URL)
                if not existing:
                    existing = (
                        session.query(CarListing)
                        .filter_by(
                            source="Bilasolur",
                            make=normalized_make,
                            model=normalized_model,
                            year=year,
                            title=normalized_title,
                        )
                        .first()
                    )
                
                # Check for cross-source duplicate (same car from different source)
                # If found, skip this listing since we prefer non-Bilasolur sources
                if not existing and normalized_make and normalized_model and year and price and kilometers:
                    cross_source_dup = (
                        session.query(CarListing)
                        .filter_by(
                            make=normalized_make,
                            model=normalized_model,
                            year=year,
                            price=price,
                            kilometers=kilometers
                        )
                        .filter(CarListing.source != "Bilasolur")
                        .first()
                    )
                    
                    if cross_source_dup:
                        print(f"  ⚠ Skipping: Found in {cross_source_dup.source} (preferring dealer source)")
                        continue

                if existing:
                    updated = False
                    for field, value in {
                        "price": price,
                        "kilometers": kilometers,
                        "title": normalized_title,
                        "make": normalized_make,
                        "model": normalized_model,
                        "year": year,
                        "url": link,  # update URL if it changed
                    }.items():
                        if value is not None and getattr(existing, field) != value:
                            setattr(existing, field, value)
                            updated = True
                    
                    # Handle image URL - upload to S3 if enabled and not already S3 URL
                    if image_url:
                        needs_s3_upload = (
                            USE_S3_STORAGE and 
                            's3.amazonaws.com' not in (existing.image_url or '') and
                            existing.image_url != image_url
                        )
                        
                        if needs_s3_upload:
                            try:
                                s3_url = await download_and_upload_image(
                                    image_url=image_url,
                                    listing_id=existing.id,
                                    make=normalized_make or 'unknown',
                                    model=normalized_model or 'unknown',
                                    year=year or 0,
                                    source_url=link
                                )
                                if s3_url:
                                    existing.image_url = s3_url
                                    updated = True
                                else:
                                    # Fallback to temporary URL if S3 fails
                                    existing.image_url = image_url
                                    updated = True
                            except Exception as e:
                                print(f"  ⚠ S3 upload failed: {e}")
                                existing.image_url = image_url
                                updated = True
                        elif existing.image_url != image_url:
                            existing.image_url = image_url
                            updated = True
                    
                    if updated:
                        existing.scraped_at = datetime.utcnow()
                        updated_listings += 1
                else:
                    # Create new listing first to get ID
                    car = CarListing(
                        source="Bilasolur",
                        title=normalized_title,
                        make=normalized_make,
                        model=normalized_model,
                        year=year,
                        price=price,
                        kilometers=kilometers,
                        url=link,
                        image_url=image_url,  # Temporary URL for now
                        display_make=pretty_make(normalized_make) if normalized_make else None,
                        display_name=get_display_name(normalized_model) if normalized_model else None,
                        scraped_at=datetime.utcnow(),
                    )
                    session.add(car)
                    session.flush()  # Get the ID without committing
                    
                    # Upload to S3 if enabled
                    if image_url and USE_S3_STORAGE:
                        try:
                            s3_url = await download_and_upload_image(
                                image_url=image_url,
                                listing_id=car.id,
                                make=normalized_make or 'unknown',
                                model=normalized_model or 'unknown',
                                year=year or 0,
                                source_url=link
                            )
                            if s3_url:
                                car.image_url = s3_url
                        except Exception as e:
                            print(f"  ⚠ S3 upload failed for new listing: {e}")
                    
                    new_listings += 1

            session.commit()

            # Follow pagination / meira links
            next_links = await page.query_selector_all('a[href*="SearchResults.aspx"]')
            for a in next_links:
                href = await a.get_attribute("href")
                if not href:
                    continue
                if not href.startswith("http"):
                    href = f"https://bilasolur.is/{href.lstrip('/')}"
                if href not in scraped_urls and href not in urls_to_scrape:
                    urls_to_scrape.append(href)

            if len(scraped_urls) >= max_pages:
                break

        await browser.close()

    session.close()
    print(f"Done. {new_listings} new listings added. {updated_listings} listings updated.")
