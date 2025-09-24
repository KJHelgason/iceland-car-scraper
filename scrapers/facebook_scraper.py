import asyncio
import os
import random
import re
import json
from datetime import datetime
from playwright.async_api import async_playwright
from db.db_setup import SessionLocal
from db.models import CarListing
from utils.normalizer import normalize_make, normalize_model, normalize_title  # ✅ NEW
import google.generativeai as genai  # Gemini SDK

FB_URL = "https://www.facebook.com/marketplace/category/vehicles"
COOKIES_FILE = "fb_state.json"

# Initialize Gemini
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
#gemini_model = genai.GenerativeModel("gemini-2.5-pro")
gemini_model = genai.GenerativeModel("gemini-1.5-flash")

# ----- Utilities -----
def extract_number(text):
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text)
    text = str(text)
    # pick the FIRST number (handles "ISK250,000ISK900,000")
    numbers = re.findall(r"\d[\d.,]*", text)
    if numbers:
        try:
            return int(numbers[0].replace(".", "").replace(",", ""))
        except ValueError:
            return None
    return None

def extract_mileage(text):
    if not text:
        return None
    text = str(text).lower()
    # Prefer "Ekinn"/"Keyrður" style
    match = re.search(r"(?:ekinn|keyrður)\s*(\d[\d.,]*)\s*(?:km|kílómetrar|þúsund)?", text)
    if not match:
        match = re.search(r"(\d[\d.,]*)\s*(?:km|kílómetrar|þúsund)", text)
    if match:
        value = match.group(1).replace(".", "").replace(",", "")
        if "þúsund" in text:
            try:
                return int(value) * 1000
            except ValueError:
                return None
        try:
            return int(value)
        except ValueError:
            return None
    return None

def clean_text(text):
    """Remove unrelated marketplace junk lines."""
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines()]
    filtered = [
        l for l in lines
        if l and not any(kw in l.lower() for kw in ["joined facebook", "today's picks", "away"])
    ]
    return "\n".join(filtered)

# ----- Gemini extraction -----
def extract_structured_data(title, price_text, description):
    prompt = f"""
    Extract the following fields from this Facebook vehicle listing:

    Title: {title}
    Price: {price_text}
    Description:
    {description}

    Extract:
    - Make
    - Model
    - Year (4 digits)
    - Price (numeric, in ISK)
    - Mileage (numeric kilometers)

    Rules:
    - Mileage must be a number in kilometers. Prefer numbers followed by "km", "kílómetrar", "þúsund", or words like "Ekinn"/"Keyrður".
    - Ignore unrelated numbers like "Joined Facebook in 2023".
    - If mileage is in thousands (e.g., "145 þúsund"), convert to full number (145000).
    - If no mileage is given, return null.
    Return only JSON: {{ "make": ..., "model": ..., "year": ..., "price": ..., "mileage": ... }}
    """
    try:
        response = gemini_model.generate_content(prompt)
        text = response.text.strip()
        json_str = text[text.find("{"): text.rfind("}") + 1]
        data = json.loads(json_str)
        return data
    except Exception as e:
        print("Gemini extraction failed:", e, "\nRaw response:", locals().get("text", "No response"))
        return {}

# ----- Facebook login -----
async def ensure_facebook_login(context):
    if not os.path.exists(COOKIES_FILE):
        print("No Facebook cookies found. Opening login page...")
        page = await context.new_page()
        await page.goto("https://www.facebook.com/")
        print("Please log in manually, then press ENTER here when finished.")
        input()
        await context.storage_state(path=COOKIES_FILE)
        print(f"Saved new Facebook login session to {COOKIES_FILE}")
        await page.close()

# ----- Main scraper -----
async def scrape_facebook(max_items=20):
    session = SessionLocal()
    new_listings = 0
    updated_listings = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=COOKIES_FILE if os.path.exists(COOKIES_FILE) else None)
        await ensure_facebook_login(context)
        page = await context.new_page()
        await page.goto(FB_URL)
        await page.wait_for_selector('div[role="main"]')

        print("Scrolling to load more listings...")
        for _ in range(5):
            await page.mouse.wheel(0, 5000)
            await asyncio.sleep(2)

        items = await page.query_selector_all('a[href*="/marketplace/item/"]')
        listing_urls = []
        for item in items[:max_items]:
            url = await item.get_attribute("href")
            if url and url.startswith("/"):
                url = f"https://www.facebook.com{url}"
            if url:
                listing_urls.append(url)

        print(f"Found {len(listing_urls)} listings. Visiting each one...")

        for url in listing_urls:
            await page.goto(url)
            await page.wait_for_selector('xpath=/html/body/div[1]/div/div[1]/div/div[3]/div/div/div[1]/div[1]/div[2]/div/div/div/div/div/div[1]')
            await asyncio.sleep(random.uniform(2, 5))  # human-like delay

            container = await page.query_selector('xpath=/html/body/div[1]/div/div[1]/div/div[3]/div/div/div[1]/div[1]/div[2]/div/div/div/div/div/div[1]')

            # Try expanding "See more" (description)
            try:
                see_more_xpath = '/html/body/div[1]/div/div[1]/div/div[3]/div/div/div[1]/div[1]/div[2]/div/div/div/div/div/div[1]/div[2]/div/div[2]/div/div[1]/div[1]/div[5]/div[2]/div/div[1]/div/span/div/span'
                see_more_btn = await page.query_selector(f'xpath={see_more_xpath}')
                if see_more_btn:
                    await see_more_btn.scroll_into_view_if_needed()
                    await asyncio.sleep(0.3)
                    await see_more_btn.click()
                    await asyncio.sleep(1)
            except Exception as e:
                print(f"Failed to click 'See more': {e}")

            # Collect scoped text
            title_el = await container.query_selector('h1 span[dir="auto"]')
            raw_title = await title_el.inner_text() if title_el else None
            title = normalize_title(raw_title) if raw_title else None

            price_el = await container.query_selector('span:has-text("ISK"), span:has-text("kr")')
            price_text = await price_el.inner_text() if price_el else None

            desc_el = await page.query_selector('xpath=/html/body/div[1]/div/div[1]/div/div[3]/div/div/div[1]/div[1]/div[2]/div/div/div/div/div/div[1]/div[2]/div/div[2]/div/div[1]/div[1]/div[5]/div[2]/div')
            raw_description = await desc_el.inner_text() if desc_el else None
            description = clean_text(raw_description)

            # Extract with Gemini
            structured = extract_structured_data(title, price_text, description)

            # Normalize make/model after LLM extraction
            raw_make = structured.get("make")
            raw_model = structured.get("model")
            make = normalize_make(raw_make) if raw_make else None
            model = normalize_model(raw_model) if raw_model else None

            year = structured.get("year")
            price = extract_number(structured.get("price") or price_text)
            mileage = structured.get("mileage")
            if mileage is None:
                mileage = extract_mileage(description)

            # Skip non-vehicles
            if structured == {}:
                print(f"Skipping non-vehicle listing: {title}")
                continue
            if price and price > 100_000_000:
                print(f"Skipping unrealistic price for {title}: {price}")
                continue

            # Upsert
            # Decide whether we can use structured uniqueness or fallback to URL
            if all([make, model, year, title]):
                # ✅ Preferred: Upsert by (source, make, model, year, title)
                existing = (
                    session.query(CarListing)
                    .filter_by(
                        source="Facebook Marketplace",
                        make=make,
                        model=model,
                        year=year,
                        title=title,
                    )
                    .first()
                )
            else:
                # ⚠️ Fallback: Upsert by URL
                existing = (
                    session.query(CarListing)
                    .filter_by(source="Facebook Marketplace", url=url)
                    .first()
                )

            if existing:
                updated = False
                for field, value in {
                    "price": price,
                    "kilometers": mileage,
                    "description": description,
                    "url": url,  # ✅ keep URL fresh since FB rotates
                }.items():
                    if value is not None and getattr(existing, field) != value:
                        setattr(existing, field, value)
                        updated = True
                if updated:
                    existing.scraped_at = datetime.utcnow()
                    updated_listings += 1
            else:
                car = CarListing(
                    source="Facebook Marketplace",
                    title=title,
                    make=make,
                    model=model,
                    year=year,
                    price=price,
                    kilometers=mileage,
                    url=url,
                    scraped_at=datetime.utcnow(),
                    description=description,
                )
                session.add(car)
                new_listings += 1


        session.commit()
        await browser.close()
    session.close()
    print(f"Done. {new_listings} new listings added. {updated_listings} listings updated.")

if __name__ == "__main__":
    asyncio.run(scrape_facebook(max_items=10))
