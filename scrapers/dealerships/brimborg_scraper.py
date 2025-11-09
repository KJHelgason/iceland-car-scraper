import asyncio
import re
from datetime import datetime

from playwright.async_api import async_playwright, TimeoutError as PwTimeout
from db.db_setup import SessionLocal
from db.models import CarListing
from utils.normalizer import normalize_make, normalize_model, normalize_title, pretty_make, get_display_name

BASE_URL = "https://notadir.brimborg.is/is"

# --- helpers ---------------------------------------------------------------

def extract_price(text: str | None) -> int | None:
    """
    From strings like 'Verð:7.990.000 kr.' or 'Tilboð2.990.000 kr.' -> 7990000 or 2990000
    """
    if not text:
        return None
    text = text.replace("\xa0", " ").replace("&nbsp;", " ")
    # Look for "Tilboð" first (discounted price), then "Verð:"
    m = re.search(r"Tilboð[\s:]*?([\d\.\s]+)\s*kr", text, re.IGNORECASE)
    if not m:
        m = re.search(r"Verð[\s:]*?([\d\.\s]+)\s*kr", text, re.IGNORECASE)
    if m:
        raw = m.group(1)
        try:
            return int(raw.replace(".", "").replace(" ", ""))
        except ValueError:
            return None
    return None


def extract_kilometers(text: str | None) -> int | None:
    """
    From format like 'Ekinn (km): 26.460' -> 26460
    """
    if not text:
        return None
    m = re.search(r"Ekinn\s*\(km\):\s*([\d\.\s]+)", text, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1).replace(".", "").replace(" ", ""))
        except ValueError:
            return None
    return None


def extract_year(text: str | None) -> int | None:
    """
    From format like 'Árgerð (nýskráð): 09/2023' or 'Árgerð (nýskráð):\n09/2023' -> 2023
    """
    if not text:
        return None
    # Handle both inline and newline-separated formats
    m = re.search(r"Árgerð.*?(\d{2})/(\d{4})", text, re.IGNORECASE | re.DOTALL)
    if m:
        try:
            year = int(m.group(2))
            if 1985 <= year <= datetime.utcnow().year + 1:
                return year
        except ValueError:
            pass
    return None


def parse_title(title: str | None) -> tuple[str | None, str | None]:
    """
    Parse title like 'BMW iX xDrive40' -> ('BMW', 'iX xDrive40')
    or 'Polestar 2 LRDM Pilot Lite' -> ('Polestar', '2 LRDM')
    """
    if not title:
        return None, None
    
    parts = title.strip().split()
    if len(parts) == 0:
        return None, None
    
    make = parts[0]
    # Take next 1-3 parts as model
    model = " ".join(parts[1:4]) if len(parts) > 1 else (parts[1] if len(parts) > 1 else None)
    
    return make, model


# --- main ------------------------------------------------------------------

async def scrape_brimborg(max_pages: int = 20, start_url: str | None = None):
    """
    Scrape Brimborg used cars listings with pagination.
    """
    session = SessionLocal()
    new_listings = 0
    updated_listings = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        current_page = 1
        base_url = start_url if start_url else BASE_URL
        
        while current_page <= max_pages:
            print(f"Scraping page {current_page}...")
            
            # Build URL with page parameter
            if current_page == 1:
                url = base_url
            else:
                # Add page query param
                separator = "&" if "?" in base_url else "?"
                url = f"{base_url}{separator}page={current_page}"
            
            await page.goto(url)
            
            # Wait for listings to load
            try:
                await page.wait_for_selector('a[href*="/notadir-bilar/bill/"]', timeout=15000)
                await asyncio.sleep(1)
            except PwTimeout:
                print(f"No listings found on page {current_page}")
                break
            
            # Get all listing links
            links = await page.query_selector_all('a[href*="/notadir-bilar/bill/"]')
            
            if len(links) == 0:
                print(f"No more listings found, stopping at page {current_page}")
                break
            
            print(f"Found {len(links)} listings on page {current_page}")
            
            # Process each listing card
            for link in links:
                try:
                    # URL
                    href = await link.get_attribute("href")
                    if href and not href.startswith("http"):
                        href = f"https://notadir.brimborg.is{href}"
                    if not href:
                        continue
                    
                    # Get title from link
                    title_line = await link.inner_text()
                    title_line = title_line.strip()
                    
                    # Get parent container for full card data
                    # The parent likely contains price, year, km, image
                    parent = await link.evaluate_handle('el => el.parentElement')
                    card_text = await parent.inner_text()
                    
                    # Try to get more context from grandparent
                    grandparent = await link.evaluate_handle('el => el.parentElement.parentElement')
                    gp_text = await grandparent.inner_text()
                    
                    # Combine texts for extraction
                    full_text = f"{title_line}\n{card_text}\n{gp_text}"
                    
                    # Image URL - look for img in the card
                    image_url = None
                    img_el = await grandparent.query_selector("img")
                    if img_el:
                        img_src = await img_el.get_attribute("src")
                        if img_src and "placeholder" not in img_src.lower():
                            if img_src.startswith("http"):
                                image_url = img_src
                            elif img_src.startswith("/"):
                                image_url = f"https://notadir.brimborg.is{img_src}"
                    
                    # Parse title to extract make and model
                    make, model = parse_title(title_line)
                    
                    # Extract data from full text
                    year = extract_year(full_text)
                    kilometers = extract_kilometers(full_text)
                    price = extract_price(full_text)
                    
                    # Normalize
                    normalized_title = normalize_title(title_line) if title_line else None
                    normalized_make = normalize_make(make) if make else None
                    normalized_model = normalize_model(model) if model else None
                    
                    # Upsert
                    existing = session.query(CarListing).filter_by(url=href).first()
                    
                    if not existing:
                        # fallback: same car but new URL
                        existing = (
                            session.query(CarListing)
                            .filter_by(
                                source="Brimborg",
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
                            source="Brimborg",
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
            
            # Check if we should continue to next page
            # Brimborg uses URL-based pagination (?page=N)
            # If we got fewer than 40 listings (typical page size), probably last page
            if len(links) < 40:
                print(f"Found only {len(links)} listings, likely last page")
                break
            
            current_page += 1
        
        await browser.close()
    
    session.close()
    print(f"Done. {new_listings} new listings added. {updated_listings} listings updated.")


if __name__ == "__main__":
    asyncio.run(scrape_brimborg(max_pages=20))
