"""
Re-check Facebook listings that are missing kilometers and try to extract them.
"""
import asyncio
import json
import random
from playwright.async_api import async_playwright
from db.db_setup import SessionLocal
from db.models import CarListing
from scrapers.facebook_scraper import extract_structured_data, clean_text, extract_mileage
from sqlalchemy import and_

COOKIES_FILE = "fb_state.json"

async def recheck_missing_kilometers():
    """Find Facebook listings with missing kilometers and re-scrape them."""
    
    session = SessionLocal()
    
    # Find active Facebook listings missing kilometers
    missing_km = session.query(CarListing).filter(
        and_(
            CarListing.source == "Facebook Marketplace",
            CarListing.is_active == True,
            CarListing.kilometers == None
        )
    ).order_by(CarListing.scraped_at.desc()).limit(50).all()
    
    print(f"Found {len(missing_km)} Facebook listings missing kilometers")
    print("="*80)
    
    if not missing_km:
        print("✅ No listings missing kilometers!")
        session.close()
        return
    
    # Load cookies
    try:
        with open(COOKIES_FILE, "r") as f:
            state = json.load(f)
    except FileNotFoundError:
        print(f"❌ Cookie file {COOKIES_FILE} not found. Run save_fb_cookies.py first.")
        session.close()
        return
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)  # Set to False for debugging
        context = await browser.new_context(storage_state=state)
        page = await context.new_page()
        
        updated_count = 0
        still_missing_count = 0
        
        for i, listing in enumerate(missing_km, 1):
            print(f"\n[{i}/{len(missing_km)}] {listing.make} {listing.model} ({listing.year or '?'})")
            print(f"  URL: {listing.url[:80]}...")
            print(f"  Current km: {listing.kilometers}")
            
            try:
                # Visit the listing page - SAME AS ACTUAL SCRAPER
                await page.goto(listing.url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_selector('xpath=/html/body/div[1]/div/div[1]/div/div[3]/div/div/div[1]/div[1]/div[2]/div/div/div/div/div/div[1]', timeout=10000)
                await asyncio.sleep(2)
                
                # Get container - SAME AS ACTUAL SCRAPER
                container = await page.query_selector('xpath=/html/body/div[1]/div/div[1]/div/div[3]/div/div/div[1]/div[1]/div[2]/div/div/div/div/div/div[1]')
                
                # Try expanding "See more" (description) - SAME AS ACTUAL SCRAPER
                try:
                    see_more_xpath = '/html/body/div[1]/div/div[1]/div/div[3]/div/div/div[1]/div[1]/div[2]/div/div/div/div/div/div[1]/div[2]/div/div[2]/div/div[1]/div[1]/div[5]/div[2]/div/div[1]/div/span/div/span'
                    see_more_btn = await page.query_selector(f'xpath={see_more_xpath}')
                    if see_more_btn:
                        await see_more_btn.scroll_into_view_if_needed()
                        await asyncio.sleep(0.3)
                        await see_more_btn.click()
                        await asyncio.sleep(1)
                except Exception:
                    pass  # No "See more" button or already expanded
                
                # Extract data - SAME SELECTORS AS ACTUAL SCRAPER
                title_el = await container.query_selector('h1 span[dir="auto"]') if container else None
                title = (await title_el.inner_text()) if title_el else ""
                
                price_el = await container.query_selector('span:has-text("ISK"), span:has-text("kr")') if container else None
                price_text = (await price_el.inner_text()) if price_el else ""
                
                # Try primary description xpath, then fallback selectors
                desc_el = await page.query_selector('xpath=/html/body/div[1]/div/div[1]/div/div[3]/div/div/div[1]/div[1]/div[2]/div/div/div/div/div/div[1]/div[2]/div/div[2]/div/div[1]/div[1]/div[5]/div[2]/div')
                if not desc_el:
                    # Fallback: try class-based selector
                    desc_el = await page.query_selector('div.xz9dl7a.xn6708d.xsag5q8.x1ye3gou')
                if not desc_el:
                    # Fallback: get all text from container
                    desc_el = container
                raw_description = (await desc_el.inner_text()) if desc_el else ""
                description = clean_text(raw_description)
                
                # Debug output if description is empty
                if not description or len(description) < 10:
                    print(f"  ⚠️ WARNING: Description appears empty or very short")
                    print(f"     Raw description length: {len(raw_description) if raw_description else 0}")
                
                # Try to extract with improved scraper - SAME AS ACTUAL SCRAPER
                data = extract_structured_data(title, price_text, description)
                
                # Get mileage from AI or fallback to regex - SAME AS ACTUAL SCRAPER
                mileage = data.get("mileage") if data else None
                if mileage is None:
                    mileage = extract_mileage(description)
                
                if mileage and 0 <= mileage <= 1000000:
                    new_km = mileage
                    print(f"  ✅ Found kilometers: {new_km:,} km")
                    
                    # Update the listing
                    listing.kilometers = new_km
                    session.commit()
                    updated_count += 1
                else:
                    print(f"  ⚠️ Still missing kilometers")
                    print(f"     Title: {title[:60]}...")
                    print(f"     Price: {price_text}")
                    print(f"     Desc preview: {description[:100]}...")
                    still_missing_count += 1
                    
                await asyncio.sleep(random.uniform(1, 2))  # Rate limiting
                
            except Exception as e:
                print(f"  ❌ Error: {e}")
                still_missing_count += 1
        
        await browser.close()
    
    session.close()
    
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Total checked: {len(missing_km)}")
    print(f"Updated with kilometers: {updated_count}")
    print(f"Still missing: {still_missing_count}")
    print("="*80)

if __name__ == "__main__":
    asyncio.run(recheck_missing_kilometers())
