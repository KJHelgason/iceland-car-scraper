import asyncio
import re
from datetime import datetime

from playwright.async_api import async_playwright, TimeoutError as PwTimeout
from db.db_setup import SessionLocal
from db.models import CarListing
from utils.normalizer import normalize_make, normalize_model, normalize_title

BASE_URL = "https://islandsbilar.is/soluskra/"

# --- helpers ---------------------------------------------------------------

def extract_price(text: str | None) -> int | None:
    """
    From strings like 'Verð: 8.590.000 kr.' or 'Tilboð: 790.000 kr. 890.000 kr.' -> 8590000 or 790000
    """
    if not text:
        return None
    text = text.replace("\xa0", " ").replace("&nbsp;", " ")
    # Look for "Verð:" or "Tilboð:" followed by number
    m = re.search(r"(?:Verð|Tilboð):\s*([\d\.\s]+)\s*kr", text, re.IGNORECASE)
    if m:
        raw = m.group(1)
        try:
            return int(raw.replace(".", "").replace(" ", ""))
        except ValueError:
            return None
    # Fallback: take the first big number
    m = re.findall(r"(\d[\d\.\s]+)", text)
    if m:
        try:
            return int(m[0].replace(".", "").replace(" ", ""))
        except ValueError:
            return None
    return None


def extract_kilometers(text: str | None) -> int | None:
    """
    Handles: '181 000 km.' -> 181000
    """
    if not text:
        return None
    t = text.lower().replace("\xa0", " ").replace("&nbsp;", " ")
    m = re.search(r"([\d\.\s]+)\s*km", t, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1).replace(".", "").replace(" ", ""))
        except ValueError:
            return None
    return None


def extract_year(text: str | None) -> int | None:
    """
    Extract year from text like '7/2020' or '2020'
    """
    if not text:
        return None
    # Look for pattern like 'month/year' or just year
    m = re.search(r"\d{1,2}/(\d{4})", text)
    if m:
        try:
            year = int(m.group(1))
            if 1985 <= year <= datetime.utcnow().year + 1:
                return year
        except ValueError:
            pass
    # Fallback: standalone 4-digit year
    m = re.search(r"\b(20[0-3]\d|19[89]\d)\b", text)
    if m:
        try:
            year = int(m.group(1))
            if 1985 <= year <= datetime.utcnow().year + 1:
                return year
        except ValueError:
            pass
    return None


# --- main ------------------------------------------------------------------

async def scrape_islandsbilar(max_pages: int = 5):
    """
    Scrape islandsbilar.is listings with pagination.
    """
    session = SessionLocal()
    new_listings = 0
    updated_listings = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        current_page = 1
        
        while current_page <= max_pages:
            print(f"Scraping page {current_page}...")
            
            if current_page == 1:
                await page.goto(BASE_URL)
            
            # Wait for listings to load
            try:
                await page.wait_for_selector('a[href*="/car/"]', timeout=15000)
                # Scroll to load lazy images
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1)
            except PwTimeout:
                print(f"No listings found on page {current_page}")
                break
            
            # Get all listing cards
            cards = await page.query_selector_all('a[href*="/car/"]')
            print(f"Found {len(cards)} listings on page {current_page}")
            
            imgs = await page.query_selector_all("img.card__img")
            print(f"Found {len(imgs)} images total")

            for card in cards:
                try:
                    # URL
                    link = await card.get_attribute("href")
                    if link and not link.startswith("http"):
                        link = f"https://islandsbilar.is{link}"
                    if not link:
                        continue
                    
                    # Get the full text content of the card
                    card_text = await card.inner_text()
                    
                    # Image URL - images are in div.card__img--wrapper > div > img.card__img
                    # There can be up to 5 images, we'll take the first one (or the one with is-active class)
                    parent = await card.evaluate_handle("node => node.closest('.card')")
                    img_el = await parent.query_selector("img")

                    image_url = None
                    if img_el:
                        img_src = await img_el.get_attribute("src") or await img_el.get_attribute("data-src")
                        if img_src and "placeholder" not in img_src.lower():
                            if img_src.startswith("http"):
                                image_url = img_src
                            elif img_src.startswith("/"):
                                image_url = f"https://islandsbilar.is{img_src}"
                            else:
                                image_url = f"https://assets.mango.is/{img_src}"

                    # Parse the card text to extract details
                    # Format: "MAKE MODEL [TRIM] month/year kilometers km. Transmission Fuel DriveType Verð: price"
                    # Example: "LAND ROVER DEFENDER HSE 7/2020 181 000 km. Sjálfskipting Dísil Fjórhjóladrif Verð: 8.590.000 kr."
                    lines = [l.strip() for l in card_text.split('\n') if l.strip()]
                    
                    if len(lines) < 1:
                        continue
                    
                    # The full text is typically on a single line or concatenated
                    full_text = " ".join(lines)
                    
                    # Extract the title portion (everything before month/year pattern)
                    # Pattern: find "month/year" and take everything before it
                    title_match = re.match(r"^(.+?)\s+\d{1,2}/\d{4}", full_text)
                    if title_match:
                        title_line = title_match.group(1).strip()
                    else:
                        # Fallback: take first line
                        title_line = lines[0]
                    
                    # Extract make and model from title
                    title_parts = title_line.split()
                    make = title_parts[0] if title_parts else None
                    model = " ".join(title_parts[1:3]) if len(title_parts) > 1 else (title_parts[1] if len(title_parts) > 1 else None)
                    
                    # Normalize
                    normalized_title = normalize_title(title_line) if title_line else None
                    normalized_make = normalize_make(make) if make else None
                    normalized_model = normalize_model(model) if model else None
                    
                    # Extract year (from pattern like "7/2020")
                    year = extract_year(full_text)
                    
                    # Extract kilometers (look for pattern "NUMBER km." - extract only the number before "km")
                    # Must not include the year digits
                    km_match = re.search(r'\d{4}\s+([\d\s\.]+)\s*km\.', full_text)
                    if km_match:
                        try:
                            kilometers = int(km_match.group(1).replace(".", "").replace(" ", ""))
                        except ValueError:
                            kilometers = None
                    else:
                        kilometers = None
                    
                    # Extract price (from "Verð:" or "Tilboð:")
                    price = extract_price(full_text)
                    
                    # Upsert
                    existing = session.query(CarListing).filter_by(url=link).first()
                    
                    if not existing:
                        # fallback: same car but new URL
                        existing = (
                            session.query(CarListing)
                            .filter_by(
                                source="Islandsbilar",
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
                            "url": link,
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
                            source="Islandsbilar",
                            title=normalized_title,
                            make=normalized_make,
                            model=normalized_model,
                            year=year,
                            price=price,
                            kilometers=kilometers,
                            url=link,
                            image_url=image_url,
                            scraped_at=datetime.utcnow(),
                        )
                        session.add(car)
                        new_listings += 1
                
                except Exception as e:
                    print(f"Error processing card: {e}")
                    continue
            
            session.commit()
            
            # Try to find and click next page button
            if current_page < max_pages:
                try:
                    # Look for the next page button - it's typically the last pagination item that's not disabled
                    # Using the xpath you provided: /html/body/div[1]/div/div/main/div[1]/div/ul/li[7]
                    next_button = await page.query_selector('xpath=/html/body/div[1]/div/div/main/div[1]/div/ul/li[7]')
                    
                    if not next_button:
                        # Fallback: try to find any "next" button or the last pagination number + 1
                        next_button = await page.query_selector('a[aria-label="Next"]')
                    
                    if next_button:
                        # Check if it's not disabled
                        classes = await next_button.get_attribute("class") or ""
                        if "disabled" not in classes.lower():
                            await next_button.click()
                            await asyncio.sleep(2)  # Wait for new page to load
                            current_page += 1
                        else:
                            print("Next button is disabled, reached last page")
                            break
                    else:
                        print("No next button found, stopping")
                        break
                except Exception as e:
                    print(f"Error clicking next page: {e}")
                    break
            else:
                break
        
        await browser.close()
    
    session.close()
    print(f"Done. {new_listings} new listings added. {updated_listings} listings updated.")


if __name__ == "__main__":
    asyncio.run(scrape_islandsbilar(max_pages=5))
