import asyncio
import re
from playwright.async_api import async_playwright
from datetime import datetime
from db.db_setup import SessionLocal
from db.models import CarListing
from utils.normalizer import normalize_make, normalize_model, normalize_title  # ✅

BASE_URL = "https://www.bilaland.is/SearchResults.aspx?id=f64d9165-4e5a-46fa-8db1-c83028b1f179"

def extract_price(text: str):
    if not text:
        return None
    text = text.replace("&nbsp;", " ").replace("\xa0", " ")
    matches = re.findall(r"(\d[\d\s\.]*)", text)
    if not matches:
        return None
    raw = matches[-1]
    try:
        return int(raw.replace(".", "").replace(" ", ""))
    except ValueError:
        return None

def extract_kilometers(text: str):
    if not text:
        return None
    text = text.lower().replace("&nbsp;", " ").replace("\xa0", " ")

    match_thousand = re.search(r"(\d+)\s*(þ\.?km|þúsund|þ\.km)", text)
    if match_thousand:
        try:
            return int(match_thousand.group(1)) * 1000
        except ValueError:
            pass

    match = re.search(r"([\d\.\s]+)\s*km", text)
    if match:
        try:
            return int(match.group(1).replace(".", "").replace(" ", ""))
        except ValueError:
            return None

    return None

async def scrape_bilaland(max_scrolls=5):
    session = SessionLocal()
    new_listings = 0
    updated_listings = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(BASE_URL)
        await page.wait_for_selector(".sr-item")

        print("Scrolling to load more listings...")
        for _ in range(max_scrolls):
            await page.mouse.wheel(0, 5000)
            await asyncio.sleep(2)

        listings = await page.query_selector_all(".sr-item")
        print(f"Found {len(listings)} cars.")

        for item in listings:
            # Title
            title_el = await item.query_selector(".sr-title .title-text")
            title = await title_el.inner_text() if title_el else None

            # Make & model
            make_el = await item.query_selector(".sr-title .sr-make")
            make = await make_el.inner_text() if make_el else None

            model_el = await item.query_selector(".sr-title .sr-model")
            model = await model_el.inner_text() if model_el else None

            # Normalize
            normalized_title = normalize_title(title) if title else None
            normalized_make = normalize_make(make) if make else None
            normalized_model = normalize_model(model) if model else None

            # URL
            link_el = await item.query_selector("a.sr-link")
            link = await link_el.get_attribute("href") if link_el else None
            if link and not link.startswith("http"):
                link = f"https://www.bilaland.is/{link.lstrip('/')}"
            if not link:
                continue

            # Price
            price = None
            price_el = await item.query_selector(".sr-yr-pr .pull-right")
            if price_el:
                price_text = await price_el.inner_text()
                price = extract_price(price_text)
                if price is None:
                    print(f"[WARN] Failed to parse price: {price_text}")

            # Year
            year = None
            year_el = await item.query_selector(".sr-yr-pr .pull-left")
            if year_el:
                year_text = await year_el.inner_text()
                year_match = re.search(r"(19|20)\d{2}", year_text)
                if year_match:
                    year = int(year_match.group(0))

            # Kilometers
            kilometers = None
            info_blocks = await item.query_selector_all(".sr-item-info .sr-item-wrapper")
            for block in info_blocks:
                label_el = await block.query_selector(".pull-left")
                value_el = await block.query_selector(".sr-right")
                if not label_el or not value_el:
                    continue
                label = (await label_el.inner_text()).lower()
                value = await value_el.inner_text()
                if "akstur" in label and "nýtt" not in value.lower():
                    kilometers = extract_kilometers(value)

            # Check if listing exists
            existing = session.query(CarListing).filter_by(url=link).first()
            if existing:
                updated = False
                for field, value in {
                    "price": price,
                    "title": normalized_title,
                    "make": normalized_make,
                    "model": normalized_model,
                    "year": year,
                    "kilometers": kilometers,
                }.items():
                    if value is not None and getattr(existing, field) != value:
                        setattr(existing, field, value)
                        updated = True
                if updated:
                    existing.scraped_at = datetime.utcnow()
                    updated_listings += 1
                continue

            # Add new listing
            car = CarListing(
                source="Bilaland",
                title=normalized_title,
                make=normalized_make,
                model=normalized_model,
                year=year,
                price=price,
                kilometers=kilometers,
                url=link,
                scraped_at=datetime.utcnow()
            )
            session.add(car)
            new_listings += 1

        session.commit()
        await browser.close()
    session.close()
    print(f"Done. {new_listings} new listings added. {updated_listings} listings updated.")

if __name__ == "__main__":
    asyncio.run(scrape_bilaland(max_scrolls=5))
