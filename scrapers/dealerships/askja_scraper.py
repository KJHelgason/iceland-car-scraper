import asyncio
import re
from playwright.async_api import async_playwright, TimeoutError as PwTimeout
from sqlalchemy.orm import Session
from datetime import datetime
from db.db_setup import SessionLocal
from db.models import CarListing
from utils.normalizer import normalize_make, normalize_model, normalize_title, pretty_make, get_display_name

BASE_URL = "https://www.notadir.is/"

# --- helpers ---------------------------------------------------------------

def extract_price(text: str) -> int | None:
    """Extract price from text like 'Verð: 2.990.000 kr' or '2.990.000'"""
    # Remove all dots and extract numbers
    cleaned = text.replace('.', '').replace(',', '')
    match = re.search(r'(\d+)', cleaned)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def extract_kilometers_from_spans(km_text: str) -> int | None:
    """
    Extract kilometers from text with format like '93 þ.km.' (93 thousand km)
    or just a number followed by km indicator.
    """
    # Remove dots and commas
    cleaned = km_text.replace('.', '').replace(',', '')
    
    # Check if it contains 'þ' (thousand indicator)
    if 'þ' in cleaned.lower():
        # Extract the number before þ
        match = re.search(r'(\d+)', cleaned)
        if match:
            try:
                # Multiply by 1000 since þ means thousand
                return int(match.group(1)) * 1000
            except ValueError:
                return None
    else:
        # Just extract the number
        match = re.search(r'(\d+)', cleaned)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
    return None


def extract_kilometers(text: str) -> int | None:
    """Extract kilometers from text like 'Ekinn: 45.000 km' or '45.000 km'"""
    match = re.search(r'([\d.]+)\s*km', text, re.IGNORECASE)
    if match:
        km_str = match.group(1).replace('.', '')
        try:
            return int(km_str)
        except ValueError:
            return None
    return None


def extract_year(text: str) -> int | None:
    """Extract year from text like 'Árgerð: 2020' or just '2020'"""
    match = re.search(r'Árgerð.*?(\d{4})', text, re.IGNORECASE | re.DOTALL)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    # Try standalone 4-digit year
    match = re.search(r'\b(19|20)\d{2}\b', text)
    if match:
        try:
            return int(match.group(0))
        except ValueError:
            return None
    return None


def parse_title(title: str) -> tuple[str | None, str | None]:
    """
    Parse make and model from title.
    Example: 'Mercedes-Benz GLC 300' -> ('Mercedes-Benz', 'GLC 300')
    """
    parts = title.strip().split(maxsplit=1)
    if len(parts) >= 2:
        return parts[0], parts[1]
    elif len(parts) == 1:
        return parts[0], None
    return None, None


# --- main ------------------------------------------------------------------

async def scrape_askja(max_clicks: int = 50, start_url: str | None = None):
    """
    Scrape Askja (notadir.is) used cars listings.
    Instead of pagination, this site uses a "See more" button.
    """
    session = SessionLocal()
    new_listings = 0
    updated_listings = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        url = start_url if start_url else BASE_URL
        
        print(f"Navigating to {url}...")
        await page.goto(url, wait_until="domcontentloaded")
        
        # Wait for React to load the listings
        # The site uses React, so we need to wait for dynamic content
        print("Waiting for page to load...")
        await asyncio.sleep(5)
        
        # Try to find listings - they might be in different container types
        # Common patterns: a links to car details, divs with data attributes, etc.
        try:
            # Wait for any clickable car elements to appear
            await page.wait_for_selector('div.vehicle-item, a[href*="bil"], div[data-vehicle-id]', timeout=15000)
        except PwTimeout:
            print("No listings found - trying alternative selectors")
            # If that doesn't work, just proceed and try to find any elements
        
        clicks = 0
        while clicks < max_clicks:
            print(f"Processing listings (click {clicks + 1}/{max_clicks})...")
            
            # Get all vehicle divs - they have class="vehicle"
            listing_divs = await page.query_selector_all('div.vehicle')
            
            if len(listing_divs) == 0:
                print("No listings found")
                break
            
            print(f"Found {len(listing_divs)} listings visible")
            
            # Process each listing card
            for idx, card_div in enumerate(listing_divs):
                try:
                    # Get the link element (a tag with class="vehicle__image")
                    link = await card_div.query_selector('a.vehicle__image')
                    if not link:
                        # Try any a tag
                        link = await card_div.query_selector('a')
                    if not link:
                        continue
                    
                    # URL
                    href = await link.get_attribute("href")
                    if href and not href.startswith("http"):
                        href = f"https://www.notadir.is{href}"
                    if not href:
                        continue
                    
                    # Skip if this is not a car listing
                    if "/soluskra?" not in href:
                        continue
                    
                    # Image URL - it's in the style attribute of the a tag
                    image_url = None
                    try:
                        style = await link.get_attribute("style")
                        if style:
                            # Extract URL from style like: background-image:url(...)
                            match = re.search(r"url\(([^)]+)\)", style)
                            if match:
                                image_url = match.group(1)
                                # Remove quotes if present
                                image_url = image_url.strip('\'"')
                                if image_url and not image_url.startswith("http"):
                                    image_url = f"https://www.notadir.is{image_url}"
                    except Exception:
                        pass
                    
                    # Get vehicle info from the card
                    # Make - in h4 with class="vehicle__title"
                    # Model - in p with class="vehicle__subtitle"
                    make_text = ""
                    model_text = ""
                    title_text = ""
                    try:
                        title_elem = await card_div.query_selector('h4.vehicle__title')
                        if title_elem:
                            make_text = await title_elem.inner_text()
                            make_text = make_text.strip()
                        
                        # Model - in p with class="vehicle__subtitle"
                        subtitle_elem = await card_div.query_selector('p.vehicle__subtitle')
                        if subtitle_elem:
                            model_text = await subtitle_elem.inner_text()
                            model_text = model_text.strip()
                        
                        # Combine for full title
                        title_text = f"{make_text} {model_text}".strip()
                    except Exception:
                        pass
                    
                    # Price - in em element with spans
                    price = None
                    try:
                        price_elem = await card_div.query_selector('em')
                        if price_elem:
                            # Get all spans inside and concatenate their text
                            spans = await price_elem.query_selector_all('span')
                            price_text = ""
                            for span in spans:
                                span_text = await span.inner_text()
                                price_text += span_text.strip()
                            price = extract_price(price_text)
                    except Exception as e:
                        pass
                    
                    # Get all list items for year and kilometers
                    year = None
                    kilometers = None
                    try:
                        list_items = await card_div.query_selector_all('ul li')
                        for li in list_items:
                            li_text = await li.inner_text()
                            # Check if it contains year pattern
                            if not year:
                                year = extract_year(li_text)
                            # Check if it contains km pattern
                            if not kilometers:
                                # Try to find span with km indicator
                                km_span = await li.query_selector('span:has-text("km"), span:has-text("þ")')
                                if km_span:
                                    km_text = await km_span.inner_text()
                                    kilometers = extract_kilometers_from_spans(km_text)
                    except Exception as e:
                        pass
                    
                    # Parse make/model from title
                    make, model = parse_title(title_text)
                    
                    # Normalize
                    normalized_title = normalize_title(title_text)
                    normalized_make = normalize_make(make) if make else None
                    normalized_model = normalize_model(model) if model else None
                    
                    # Check if listing exists
                    existing = session.query(CarListing).filter_by(url=href, source="Askja").first()
                    
                    # Upsert - always update to fix bad data
                    if existing:
                        # Update all fields to fix incorrect data
                        existing.price = price
                        existing.kilometers = kilometers
                        existing.title = normalized_title
                        existing.make = normalized_make
                        existing.model = normalized_model
                        existing.year = year
                        existing.url = href
                        existing.image_url = image_url
                        existing.scraped_at = datetime.utcnow()
                        updated_listings += 1
                    else:
                        car = CarListing(
                            source="Askja",
                            title=normalized_title,
                            make=normalized_make,
                            model=normalized_model,
                            year=year,
                            price=price,
                            kilometers=kilometers,
                            url=href,
                            image_url=image_url,
                            display_make=pretty_make(normalized_make) if normalized_make else None,
                            display_name=get_display_name(normalized_model) if normalized_model else None,
                            scraped_at=datetime.utcnow(),
                        )
                        session.add(car)
                        new_listings += 1
                
                except Exception as e:
                    print(f"Error processing listing {idx}: {e}")
                    continue
            
            session.commit()
            
            # Try to click "See more" button
            try:
                see_more_button = await page.query_selector('button:has-text("Sjá fleiri")')
                if see_more_button:
                    # Check if button is visible and enabled
                    is_visible = await see_more_button.is_visible()
                    is_enabled = await see_more_button.is_enabled()
                    
                    if is_visible and is_enabled:
                        print("Clicking 'Sjá fleiri' button...")
                        await see_more_button.click()
                        await asyncio.sleep(2)  # Wait for new listings to load
                        clicks += 1
                    else:
                        print("'Sjá fleiri' button not clickable, stopping")
                        break
                else:
                    print("No 'Sjá fleiri' button found, reached end")
                    break
            except Exception as e:
                print(f"Error clicking 'Sjá fleiri': {e}")
                break
        
        await browser.close()
    
    session.close()
    print(f"Done. {new_listings} new listings added. {updated_listings} listings updated.")


if __name__ == "__main__":
    asyncio.run(scrape_askja(max_clicks=50))
