import asyncio
import re
from playwright.async_api import async_playwright, TimeoutError as PwTimeout
from sqlalchemy.orm import Session
from datetime import datetime
from db.db_setup import SessionLocal
from db.models import CarListing
from utils.normalizer import normalize_make, normalize_model, normalize_title, pretty_make, get_display_name

BASE_URL = "https://www.br.is/?make=-1"  # -1 means "all manufacturers"

# --- helpers ---------------------------------------------------------------

def extract_price(text: str) -> int | None:
    """Extract price from text like 'kr. 7.890.000' or 'Flott verð kr. 6.490.000'"""
    # Look for pattern like "kr. 7.890.000" or "kr 7.890.000"
    match = re.search(r'kr\.?\s*([\d.]+)', text, re.IGNORECASE)
    if match:
        price_str = match.group(1).replace('.', '')
        try:
            return int(price_str)
        except ValueError:
            return None
    return None


def extract_kilometers(text: str) -> int | None:
    """Extract kilometers from text like 'Akstur 29 þ.km.' where þ means thousand"""
    # Look for pattern like "29 þ.km." or "29 þ km"
    match = re.search(r'(\d+)\s*þ', text, re.IGNORECASE)
    if match:
        try:
            # þ means thousand, so multiply by 1000
            return int(match.group(1)) * 1000
        except ValueError:
            return None
    
    # Also try regular km pattern
    match = re.search(r'(\d+)\s*km', text, re.IGNORECASE)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    
    return None


def extract_year(text: str) -> int | None:
    """Extract year from text like '4/2022' (month/year format)"""
    # Look for month/year pattern like "4/2022" or "12/2020"
    match = re.search(r'(\d{1,2})/(\d{4})', text)
    if match:
        try:
            return int(match.group(2))  # Return the year part
        except ValueError:
            return None
    
    # Fallback to standard year pattern
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

async def scrape_br(max_scrolls: int = 20, start_url: str | None = None):
    """
    Scrape BR (br.is) used cars listings with infinite scroll.
    Scrolls to load more listings instead of using pagination.
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
        await asyncio.sleep(3)
        
        # Wait for listings container to load
        try:
            await page.wait_for_selector('xpath=/html/body/form/div[4]/div/div[3]', timeout=15000)
            await asyncio.sleep(1)
        except PwTimeout:
            print("Listings container not found")
            await browser.close()
            session.close()
            return
        
        # Scroll to load all listings
        previous_count = 0
        scroll_count = 0
        no_change_count = 0
        
        while scroll_count < max_scrolls:
            # Get current listing count
            links = await page.query_selector_all('xpath=/html/body/form/div[4]/div/div[3]//a[contains(@href, "CarDetails.aspx")]')
            current_count = len(links)
            
            print(f"Scroll {scroll_count + 1}/{max_scrolls}: Found {current_count} listings")
            
            # Check if count has changed
            if current_count == previous_count:
                no_change_count += 1
                if no_change_count >= 3:
                    print("No new listings loaded after 3 scrolls, stopping")
                    break
            else:
                no_change_count = 0
            
            previous_count = current_count
            
            # Scroll to bottom
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)
            
            scroll_count += 1
        
        # Get all listing links after scrolling
        links = await page.query_selector_all('xpath=/html/body/form/div[4]/div/div[3]//a[contains(@href, "CarDetails.aspx")]')
        
        if len(links) == 0:
            print("No listings found")
            await browser.close()
            session.close()
            return
        
        print(f"\nProcessing {len(links)} total listings...")
        
        # Process each listing card
        for link in links:
            try:
                # URL
                href = await link.get_attribute("href")
                if href and not href.startswith("http"):
                    # Add missing slash if needed
                    if not href.startswith("/"):
                        href = f"/{href}"
                    href = f"https://www.br.is{href}"
                if not href:
                    continue
                
                # Get make and model from the title-text div with specific spans
                # The div contains span.sr-make and span.sr-model
                make_text = None
                model_text = None
                title = ""
                
                try:
                    # Navigate to the card element containing title-text
                    # The link is inside the card, so go up to find the title-text div
                    parent = await link.evaluate_handle('el => el.parentElement')
                    
                    # Look for div.title-text within the card
                    title_div = await parent.query_selector('div.title-text')
                    if not title_div:
                        # Try searching in parent's parent
                        grandparent = await link.evaluate_handle('el => el.parentElement.parentElement')
                        title_div = await grandparent.query_selector('div.title-text')
                    
                    if title_div:
                        # Get make from span.sr-make
                        make_span = await title_div.query_selector('span.sr-make')
                        if make_span:
                            make_text = await make_span.inner_text()
                            make_text = make_text.strip()
                        
                        # Get model from span.sr-model
                        model_span = await title_div.query_selector('span.sr-model')
                        if model_span:
                            model_text = await model_span.inner_text()
                            model_text = model_text.strip()
                        
                        # Combine for full title
                        if make_text and model_text:
                            title = f"{make_text} {model_text}"
                        elif make_text:
                            title = make_text
                        elif model_text:
                            title = model_text
                except Exception as e:
                    print(f"Error extracting make/model: {e}")
                
                # Fallback: if we didn't get title from spans, try the old way
                if not title:
                    title_line = await link.inner_text()
                    lines = title_line.split('\n')
                    title = lines[0].strip() if len(lines) > 0 else title_line.strip()
                    title = title.replace('-', ' ')
                
                # Get parent container for full card data
                parent = await link.evaluate_handle('el => el.parentElement')
                card_text = await parent.inner_text()
                
                # Try to get more context from grandparent
                grandparent = await link.evaluate_handle('el => el.parentElement.parentElement')
                gp_text = await grandparent.inner_text()
                
                # Try great-grandparent for even more context
                great_grandparent = await link.evaluate_handle('el => el.parentElement.parentElement.parentElement')
                ggp_text = await great_grandparent.inner_text()
                
                # Combine texts for extraction
                full_text = f"{card_text}\n{gp_text}\n{ggp_text}"
                
                # Image URL - look for img in the card
                image_url = None
                try:
                    # Try grandparent first
                    img = await grandparent.query_selector("img")
                    if not img:
                        # Try great-grandparent
                        img = await great_grandparent.query_selector("img")
                    if img:
                        image_url = await img.get_attribute("src")
                        if not image_url:
                            image_url = await img.get_attribute("data-src")
                        if image_url and not image_url.startswith("http"):
                            image_url = f"https://www.br.is{image_url}"
                except Exception:
                    pass
                
                # Extract data
                price = extract_price(full_text)
                kilometers = extract_kilometers(full_text)
                year = extract_year(full_text)
                
                # Parse make/model - prefer the span values if we got them
                if make_text and model_text:
                    make = make_text
                    model = model_text
                else:
                    make, model = parse_title(title)
                
                # Normalize
                normalized_title = normalize_title(title)
                normalized_make = normalize_make(make) if make else None
                normalized_model = normalize_model(model) if model else None
                
                # Check if listing exists
                existing = session.query(CarListing).filter_by(url=href, source="BR").first()
                
                # Upsert
                if existing:
                    updated = False
                    for field, value in {
                        "price": price,
                        "kilometers": kilometers,
                        "title": normalized_title,
                        "make": normalized_make,
                        "model": normalized_model,
                        "year": year,
                        "url": href,
                    }.items():
                        if value is not None and getattr(existing, field) != value:
                            setattr(existing, field, value)
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
                        source="BR",
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
                print(f"Error processing listing: {e}")
                continue
        
        session.commit()
        
        await browser.close()
    
    session.close()
    print(f"Done. {new_listings} new listings added. {updated_listings} listings updated.")


if __name__ == "__main__":
    asyncio.run(scrape_br(max_pages=20))
