import asyncio
import re
from datetime import datetime

from playwright.async_api import async_playwright, TimeoutError as PwTimeout
from db.db_setup import SessionLocal
from db.models import CarListing
from utils.normalizer import normalize_make, normalize_model, normalize_title, pretty_make, get_display_name

BASE_URL = "https://www.hekla.is/is/bilar/notadir-bilar"

# --- helpers ---------------------------------------------------------------

def extract_price(text: str | None) -> int | None:
    """
    From strings like 'Verð:6.290.000 kr.' or 'Tilboð:11.290.000 kr.' -> 6290000 or 11290000
    """
    if not text:
        return None
    text = text.replace("\xa0", " ").replace("&nbsp;", " ")
    # Look for "Tilboð:" first (discounted price), then "Verð:"
    m = re.search(r"Tilboð:\s*([\d\.\s]+)\s*kr", text, re.IGNORECASE)
    if not m:
        m = re.search(r"Verð:\s*([\d\.\s]+)\s*kr", text, re.IGNORECASE)
    if m:
        raw = m.group(1)
        try:
            return int(raw.replace(".", "").replace(" ", ""))
        except ValueError:
            return None
    return None


def extract_kilometers(text: str | None) -> int | None:
    """
    From format like '12.2023/ 20.000/ Rafmagn' -> 20000
    The second number after / is kilometers
    """
    if not text:
        return None
    # Pattern: date/ kilometers/ fuel
    parts = text.split("/")
    if len(parts) >= 2:
        km_part = parts[1].strip()
        # Remove dots and spaces
        try:
            return int(km_part.replace(".", "").replace(" ", ""))
        except ValueError:
            return None
    return None


def extract_year(text: str | None) -> int | None:
    """
    From format like '12.2023/ 20.000/ Rafmagn' -> 2023
    The first part is month.year
    """
    if not text:
        return None
    # Pattern: MM.YYYY
    m = re.search(r"(\d{2})\.(\d{4})", text)
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
    Parse title like 'VW ID.5 GTX 220 KW' -> ('VW', 'ID.5 GTX')
    or 'AUDI Q5 55 TFSI ETRON' -> ('AUDI', 'Q5 55')
    """
    if not title:
        return None, None
    
    parts = title.strip().split()
    if len(parts) == 0:
        return None, None
    
    make = parts[0]
    # Take next 1-2 parts as model
    model = " ".join(parts[1:3]) if len(parts) > 1 else (parts[1] if len(parts) > 1 else None)
    
    return make, model


# --- main ------------------------------------------------------------------

async def scrape_hekla(max_pages: int = 20, start_url: str | None = None):
    """
    Scrape Hekla used cars listings with pagination.
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
                # Check if base_url already has query params
                separator = "&" if "?" in base_url else "?"
                url = f"{base_url}{separator}page={current_page}"
            
            await page.goto(url)
            
            # Wait for listings to load
            try:
                await page.wait_for_selector('a[href*="/bilar/notadir-bilar/view/"]', timeout=15000)
                await asyncio.sleep(1)
            except PwTimeout:
                print(f"No listings found on page {current_page}")
                break
            
            # Get all listing cards - need to get the great-grandparent of each link for full data including images
            links = await page.query_selector_all('a[href*="/bilar/notadir-bilar/view/"]')
            
            if len(links) == 0:
                print(f"No more listings found, stopping at page {current_page}")
                break
            
            print(f"Found {len(links)} listings on page {current_page}")
            
            # Get great-grandparents (which contain both image and listing data)
            cards = []
            for link in links:
                try:
                    # Go up 3 levels: link -> parent -> grandparent -> great-grandparent
                    # Great-grandparent has structure: <div class="img"> + <div class="info">
                    great_grandparent = await link.evaluate_handle('el => el.parentElement.parentElement.parentElement')
                    cards.append((link, great_grandparent))
                except Exception:
                    continue
            
            for link, card in cards:
                try:
                    # URL from the link element
                    href = await link.get_attribute("href")
                    if href and not href.startswith("http"):
                        href = f"https://www.hekla.is{href}"
                    if not href:
                        continue
                    
                    # Get title from link
                    title_line = await link.inner_text()
                    title_line = title_line.strip()
                    
                    # Get full card content from grandparent
                    card_text = await card.inner_text()
                    
                    # --- IMAGE URL FIX ---
                    image_url = None

                    # Scroll to ensure lazy images load
                    await card.scroll_into_view_if_needed()
                    await asyncio.sleep(0.2)

                    # The image is in div.img within the great-grandparent
                    # Structure: <div class="img"><img src="..."></div>
                    img_el = await card.query_selector("div.img img, .img img, img")

                    if img_el:
                        img_src = (
                            await img_el.get_attribute("data-src")
                            or await img_el.get_attribute("srcset")
                            or await img_el.get_attribute("src")
                        )

                        if img_src and "placeholder" not in img_src.lower():
                            # Extract first URL from srcset if necessary
                            if " " in img_src and img_src.strip().startswith("http"):
                                img_src = img_src.split(" ")[0]

                            if img_src.startswith("http"):
                                image_url = img_src
                            elif img_src.startswith("/"):
                                image_url = f"https://www.hekla.is{img_src}"

                    # Parse title
                    # Extract make and model
                    make, model = parse_title(title_line)
                    
                    # Parse the card text - format is:
                    # Title\nVerð:\nprice\nMM.YYYY\nkilometers\nfuel
                    lines = [l.strip() for l in card_text.split('\n') if l.strip()]
                    
                    # Find year and kilometers by their positions
                    year = None
                    kilometers = None
                    year_line_idx = None
                    
                    for idx, line in enumerate(lines):
                        # Find the year line (MM.YYYY format)
                        if not year and re.match(r'^\d{2}\.\d{4}$', line):
                            year = extract_year(line)
                            year_line_idx = idx
                        # Kilometers is the line immediately after year
                        elif year_line_idx is not None and idx == year_line_idx + 1:
                            try:
                                km_val = int(line.replace(".", "").replace(" ", ""))
                                if 0 < km_val < 1000000:  # reasonable km range (up to 999,999 km)
                                    kilometers = km_val
                                    break
                            except ValueError:
                                pass
                    
                    # Extract price
                    price = extract_price(card_text)
                    
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
                                source="Hekla",
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
                            source="Hekla",
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
                    print(f"Error processing card: {e}")
                    continue
            
            session.commit()
            
            # Check if there's a next page
            # Look for pagination - Hekla might use "Næsta >" button
            try:
                next_button = await page.query_selector('a:has-text("Næsta")')
                if not next_button or current_page >= max_pages:
                    print("Reached last page or max pages")
                    break
                current_page += 1
            except Exception:
                # If no next button found, try one more page anyway
                current_page += 1
                if current_page > max_pages:
                    break
        
        await browser.close()
    
    session.close()
    print(f"Done. {new_listings} new listings added. {updated_listings} listings updated.")


if __name__ == "__main__":
    asyncio.run(scrape_hekla(max_pages=20))
