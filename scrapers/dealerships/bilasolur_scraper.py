import asyncio
import re
from datetime import datetime

from playwright.async_api import async_playwright, TimeoutError as PwTimeout
from db.db_setup import SessionLocal
from db.models import CarListing
from utils.normalizer import normalize_make, normalize_model, normalize_title

BASE_URL = "https://bilasolur.is/"

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

                # Upsert
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

                if existing:
                    updated = False
                    for field, value in {
                        "price": price,
                        "kilometers": kilometers,
                        "url": link,  # URL can change, keep the latest
                    }.items():
                        if value is not None and getattr(existing, field) != value:
                            setattr(existing, field, value)
                            updated = True
                    if updated:
                        existing.scraped_at = datetime.utcnow()
                        updated_listings += 1
                else:
                    car = CarListing(
                        source="Bilasolur",
                        title=normalized_title,
                        make=normalized_make,
                        model=normalized_model,
                        year=year,
                        price=price,
                        kilometers=kilometers,
                        url=link,
                        scraped_at=datetime.utcnow(),
                    )
                    session.add(car)
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
