import asyncio
import os
import random
import re
import json
from datetime import datetime
from playwright.async_api import async_playwright
from db.db_setup import SessionLocal
from db.models import CarListing
from utils.normalizer import normalize_make, normalize_model, normalize_title, pretty_make, get_display_name  # ✅ NEW
from scrapers.facebook_item_tracker import extract_item_id, add_rejected_item, update_last_seen

# Choose AI provider: 'openai' or 'gemini' or 'regex' (no AI)
AI_PROVIDER = os.getenv("AI_PROVIDER", "openai")  # Default to OpenAI

# Initialize AI based on provider
if AI_PROVIDER == "openai":
    from openai import OpenAI
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
elif AI_PROVIDER == "gemini":
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
    gemini_model = genai.GenerativeModel("gemini-2.0-flash-exp")

FB_URL = "https://www.facebook.com/marketplace/category/vehicles"
COOKIES_FILE = "fb_state.json"

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
    # Prefer "Ekinn"/"Keyrður" style but allow intervening words
    # e.g. "Ekinn aðeins 99.000km"
    match = re.search(r"(?:ekinn|keyrður)(?:\s+\S+){0,5}?\s*(\d[\d.,]*)\s*(?:km|kílómetrar|þúsund)?", text)
    if not match:
        # Generic number followed by km (covers '99,503 km', '99.000km', '📍 Mileage: 99,503 km')
        match = re.search(r"(\d[\d.,]*)\s*(?:km|kílómetrar|þúsund)", text)
    if match:
        raw = match.group(1)
        # Normalize number separators
        value = raw.replace(".", "").replace(",", "")
        # If the text contains the Icelandic word 'þúsund', interpret as thousands
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

# ----- AI extraction -----
def is_likely_vehicle(title, price_text, description):
    """Quick pre-filter to skip obvious non-vehicle listings before AI extraction."""
    combined_text = f"{title} {description}".lower()
    
    # Check price first - if over 500k ISK, almost certainly a vehicle
    price = extract_number(price_text)
    if price and price >= 500000:
        return True  # High price = likely vehicle, skip part keywords check
    
    # For lower prices, check for part-only listings (title-heavy indicators)
    # These keywords in TITLE strongly suggest parts/accessories only
    title_lower = title.lower()
    title_only_part_keywords = [
        "til sölu dekk",  # "tires for sale"
        "felgur til sölu",  # "rims for sale"
        "sumardekk",  # summer tires (when in title)
        "nagladekk",  # studded tires (when in title)
        "pallhús",  # truck bed cover
        "hleðslusnúra",  # charging cable
        "varahlut",  # spare part
        "hurðaspjöld",  # door panels
        " rims for sale",
        " tires for sale",
        " wheels for sale",
    ]
    
    if any(keyword in title_lower for keyword in title_only_part_keywords):
        return False
    
    # Check price - if under 100k ISK, likely a part
    if price and price < 100000:
        return False
    
    return True


def extract_structured_data(title, price_text, description, url=None):
    """Extract vehicle data using configured AI provider or regex fallback."""
    
    # Pre-filter: Skip obvious non-vehicles
    if not is_likely_vehicle(title, price_text, description):
        print(f"⚠️ SKIPPING: Likely a part/accessory, not a vehicle")
        
        # Track this as rejected
        if url:
            item_id = extract_item_id(url)
            if item_id:
                add_rejected_item(item_id, "non_vehicle", f"Title: {title}")
        
        return {}
    
    if AI_PROVIDER == "openai":
        return extract_with_openai(title, price_text, description)
    elif AI_PROVIDER == "gemini":
        return extract_with_gemini(title, price_text, description)
    else:
        # Fallback to regex-only extraction (no AI)
        return extract_with_regex(title, price_text, description)


def extract_with_openai(title, price_text, description):
    """Extract using OpenAI API with structured output."""
    prompt = f"""Extract vehicle information from this Facebook listing. 
    
IMPORTANT: If this is a car PART or ACCESSORY (not a complete vehicle), return {{"is_vehicle": false}}.

Common parts/accessories to reject (Icelandic):
- dekk (tires), felgur (rims), ljós (lights), hurðaspjöld (door panels)
- pallhús (truck bed cover), hleðslusnúra (charging cable)
- varahlutir (spare parts), speglar (mirrors), sæti (seats)

Title: {title}
Price: {price_text}
Description:
{description}

Extract ONLY if this is a complete VEHICLE for sale:
- Make (car manufacturer)
- Model (car model name)
- Year (4 digits)
- Price (numeric, in ISK)
- Mileage (numeric kilometers)

Rules:
- Mileage must be a number in kilometers. Prefer numbers followed by "km", "kílómetrar", "þúsund", or words like "Ekinn"/"Keyrður".
- Ignore unrelated numbers like "Joined Facebook in 2023".
- If mileage is in thousands (e.g., "145 þúsund"), convert to full number (145000).
- If no mileage is given, return null.
- If any field cannot be determined, return null for that field.
- If this is NOT a vehicle (parts, accessories, etc.), return {{"is_vehicle": false}}

Return ONLY valid JSON:
{{"is_vehicle": true, "make": "...", "model": "...", "year": 2020, "price": 1500000, "mileage": 145000}}
OR
{{"is_vehicle": false}}"""
    
    try:
        # Log input data
        print("\n" + "="*80)
        print("🤖 AI EXTRACTION - INPUT DATA")
        print("="*80)
        print(f"Title: {title}")
        print(f"Price Text: {price_text}")
        print(f"Description (first 200 chars): {description[:200] if description else 'None'}...")
        print("="*80)
        
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a data extraction assistant. Return only valid JSON, no markdown or explanations."},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_tokens=200,
            response_format={"type": "json_object"}  # Force JSON output
        )
        
        text = response.choices[0].message.content.strip()
        data = json.loads(text)
        
        # Log raw AI output
        print("🤖 AI EXTRACTION - RAW OUTPUT")
        print("="*80)
        print(f"Raw JSON: {text}")
        print("="*80)
        
        # Check if AI classified as non-vehicle
        if data.get("is_vehicle") == False:
            print("🚫 AI CLASSIFIED AS NON-VEHICLE (part/accessory)")
            print("="*80 + "\n")
            return {}
        
        # Validate extracted data
        validation_messages = []
        
        if data.get("year"):
            year = int(data["year"])
            # Year should be between 1950 and current year + 2
            if year < 1950 or year > datetime.now().year + 2:
                validation_messages.append(f"❌ Invalid year: {year} (must be 1950-{datetime.now().year + 2})")
                data["year"] = None
            else:
                validation_messages.append(f"✅ Year: {year}")
        else:
            validation_messages.append("⚠️ Year: None")
        
        if data.get("price"):
            price = int(data["price"])
            # Price should be reasonable (100k - 100M ISK)
            if price < 100000 or price > 100000000:
                validation_messages.append(f"❌ Invalid price: {price:,} ISK (must be 100k-100M)")
                data["price"] = None
            else:
                validation_messages.append(f"✅ Price: {price:,} ISK")
        else:
            validation_messages.append("⚠️ Price: None")
        
        if data.get("mileage"):
            mileage = int(data["mileage"])
            # Mileage should be reasonable (0 - 1M km)
            if mileage < 0 or mileage > 1000000:
                validation_messages.append(f"❌ Invalid mileage: {mileage:,} km (must be 0-1M)")
                data["mileage"] = None
            else:
                validation_messages.append(f"✅ Mileage: {mileage:,} km")
        else:
            validation_messages.append("⚠️ Mileage: None")
        
        validation_messages.append(f"✅ Make: {data.get('make', 'None')}")
        validation_messages.append(f"✅ Model: {data.get('model', 'None')}")
        
        # Log validation results
        print("🤖 AI EXTRACTION - VALIDATION")
        print("="*80)
        for msg in validation_messages:
            print(msg)
        print("="*80 + "\n")
        # If AI omitted mileage, try a regex fallback on title+description
        if not data.get("mileage"):
            fallback_m = extract_mileage(f"{title}\n{description}")
            if fallback_m and 0 <= fallback_m <= 1000000:
                data["mileage"] = fallback_m
                print(f"ℹ️ Filled mileage from regex fallback: {fallback_m} km")

        return data
    except Exception as e:
        print(f"❌ OpenAI extraction failed: {e}")
        print("Falling back to regex extraction")
        # Fallback to regex
        return extract_with_regex(title, price_text, description)


def extract_with_gemini(title, price_text, description):
    """Extract using Gemini API (original implementation)."""
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
        print(f"Gemini extraction failed: {e}")
        return extract_with_regex(title, price_text, description)


def extract_with_regex(title, price_text, description):
    """Fallback regex-based extraction (no AI required)."""
    data = {}
    
    # Try to extract year from title or description
    combined = f"{title} {description}"
    year_match = re.search(r'\b(19|20)\d{2}\b', combined)
    if year_match:
        data["year"] = int(year_match.group(0))
    
    # Extract price from price_text
    data["price"] = extract_number(price_text)
    
    # Extract mileage from description
    data["mileage"] = extract_mileage(description)
    
    # Try to extract make/model from title (basic splitting)
    if title:
        # Common Icelandic car makes
        makes = ["toyota", "volkswagen", "vw", "audi", "bmw", "mercedes", "mercedes-benz", "ford", 
                "nissan", "hyundai", "kia", "mazda", "honda", "subaru", "volvo", "skoda", "seat",
                "peugeot", "citroen", "renault", "opel", "chevrolet", "dodge", "jeep", "land rover",
                "range rover", "tesla", "lexus", "mitsubishi", "suzuki", "fiat"]
        
        title_lower = title.lower()
        for make in makes:
            if make in title_lower:
                data["make"] = make
                # Try to get model (words after make)
                make_idx = title_lower.find(make)
                after_make = title[make_idx + len(make):].strip()
                model_parts = after_make.split()[:3]  # Take first 3 words as model
                if model_parts:
                    data["model"] = " ".join(model_parts)
                break
    
    return data

def normalize_facebook_url(url):
    """
    Normalize Facebook URL by removing tracking parameters.
    Facebook adds tracking params that change each visit, but the item ID stays the same.
    Example: /marketplace/item/123456/?ref=... → /marketplace/item/123456/
    """
    if not url:
        return url
    
    # Extract just the item ID
    match = re.search(r'/marketplace/item/(\d+)', url)
    if match:
        item_id = match.group(1)
        return f"https://www.facebook.com/marketplace/item/{item_id}/"
    
    return url


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
async def scrape_facebook(max_items=20, start_urls=None):
    """Scrape Facebook Marketplace listings.
    
    Args:
        max_items: Maximum number of listings to scrape (when scrolling)
        start_urls: Optional list of listing URLs to scrape directly (skips scrolling)
    """
    session = SessionLocal()
    new_listings = 0
    updated_listings = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=COOKIES_FILE if os.path.exists(COOKIES_FILE) else None)
        await ensure_facebook_login(context)
        page = await context.new_page()
        
        # If start_urls provided, use them directly (from seed file)
        if start_urls:
            listing_urls = start_urls[:max_items] if max_items else start_urls
            print(f"Scraping {len(listing_urls)} listings from provided URLs...")
        else:
            # Original behavior: scroll and discover
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

            # Try primary description xpath, then fallbacks
            desc_el = await page.query_selector('xpath=/html/body/div[1]/div/div[1]/div/div[3]/div/div/div[1]/div[1]/div[2]/div/div/div/div/div/div[1]/div[2]/div/div[2]/div/div[1]/div[1]/div[5]/div[2]/div')
            if not desc_el:
                # Fallback: try class-based selector
                desc_el = await page.query_selector('div.xz9dl7a.xn6708d.xsag5q8.x1ye3gou')
            if not desc_el:
                # Fallback: use container (includes all listing content)
                desc_el = container
            raw_description = await desc_el.inner_text() if desc_el else None
            description = clean_text(raw_description)

            # Image URL - Facebook typically has images in img tags with specific attributes
            image_url = None
            try:
                # Try to find the main listing image (usually in a gallery or as the primary photo)
                img_el = await page.query_selector('img[data-visualcompletion="media-vc-image"]')
                if not img_el:
                    # Fallback to any large image in the container
                    img_el = await container.query_selector('img[src*="scontent"]')
                if img_el:
                    img_src = await img_el.get_attribute("src")
                    if img_src and img_src.startswith("http"):
                        image_url = img_src
            except Exception as e:
                print(f"Failed to extract image URL: {e}")

            # Extract with AI/regex
            structured = extract_structured_data(title, price_text, description, url)

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

            # Skip non-vehicles (already tracked as rejected in extract_structured_data)
            if structured == {}:
                print(f"Skipping non-vehicle listing: {title}")
                continue
            if price and price > 100_000_000:
                print(f"Skipping unrealistic price for {title}: {price}")
                item_id = extract_item_id(url)
                if item_id:
                    add_rejected_item(item_id, "invalid_data", f"Unrealistic price: {price}")
                continue

            # Update last_seen_at timestamp (this listing is still active on Facebook)
            update_last_seen(url)

            # Normalize URL to handle Facebook's changing tracking parameters
            normalized_url = normalize_facebook_url(url)

            # Upsert - check by normalized URL first (most reliable for Facebook)
            existing = (
                session.query(CarListing)
                .filter_by(source="Facebook Marketplace")
                .filter(CarListing.url.like(f"%/marketplace/item/{normalized_url.split('/')[-2]}/%"))
                .first()
            )
            
            # If not found by URL and we have enough data, try by make/model/year/title
            if not existing and all([make, model, year, title]):
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

            if existing:
                updated = False
                for field, value in {
                    "price": price,
                    "kilometers": mileage,
                    "description": description,
                    # Don't update URL - causes duplicates due to changing tracking params
                }.items():
                    if value is not None and getattr(existing, field) != value:
                        setattr(existing, field, value)
                        updated = True
                
                # Update structured fields if missing in DB but we have them now
                for field, value in {
                    "make": make,
                    "model": model,
                    "year": year,
                }.items():
                    if value is not None and getattr(existing, field) is None:
                        setattr(existing, field, value)
                        updated = True
                
                # Update display fields if we just filled make/model
                if make and not existing.display_make:
                    existing.display_make = pretty_make(make)
                    updated = True
                if model and not existing.display_name:
                    existing.display_name = get_display_name(model)
                    updated = True
                
                # Always update image_url if we have one and DB doesn't (or it's different)
                if image_url and existing.image_url != image_url:
                    existing.image_url = image_url
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
                    display_make=pretty_make(make) if make else None,
                    display_name=get_display_name(model) if model else None,
                    scraped_at=datetime.utcnow(),
                    description=description,
                    image_url=image_url,
                )
                session.add(car)
                new_listings += 1


        session.commit()
        await browser.close()
    session.close()
    print(f"Done. {new_listings} new listings added. {updated_listings} listings updated.")

if __name__ == "__main__":
    asyncio.run(scrape_facebook(max_items=10))
