"""
Test single Mazda 3 listing to debug description extraction
"""
import asyncio
import json
import random
from playwright.async_api import async_playwright
from scrapers.facebook_scraper import extract_structured_data, clean_text, extract_mileage

COOKIES_FILE = "fb_state.json"

async def test_mazda():
    with open(COOKIES_FILE, "r") as f:
        state = json.load(f)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # headless=False to see what's happening
        context = await browser.new_context(storage_state=state)
        page = await context.new_page()
        
        url = "https://www.facebook.com/marketplace/item/1879392072687090/"
        
        print(f"Loading: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_selector('xpath=/html/body/div[1]/div/div[1]/div/div[3]/div/div/div[1]/div[1]/div[2]/div/div/div/div/div/div[1]', timeout=10000)
        await asyncio.sleep(2)
        
        container = await page.query_selector('xpath=/html/body/div[1]/div/div[1]/div/div[3]/div/div/div[1]/div[1]/div[2]/div/div/div/div/div/div[1]')
        
        # Try expanding "See more"
        try:
            see_more_xpath = '/html/body/div[1]/div/div[1]/div/div[3]/div/div/div[1]/div[1]/div[2]/div/div/div/div/div/div[1]/div[2]/div/div[2]/div/div[1]/div[1]/div[5]/div[2]/div/div[1]/div/span/div/span'
            see_more_btn = await page.query_selector(f'xpath={see_more_xpath}')
            if see_more_btn:
                print("Found 'See more' button, clicking...")
                await see_more_btn.scroll_into_view_if_needed()
                await asyncio.sleep(0.3)
                await see_more_btn.click()
                await asyncio.sleep(1)
            else:
                print("No 'See more' button found")
        except Exception as e:
            print(f"See more failed: {e}")
        
        # Extract data
        title_el = await container.query_selector('h1 span[dir="auto"]') if container else None
        title = (await title_el.inner_text()) if title_el else ""
        print(f"\nTitle: {title}")
        
        price_el = await container.query_selector('span:has-text("ISK"), span:has-text("kr")') if container else None
        price_text = (await price_el.inner_text()) if price_el else ""
        print(f"Price: {price_text}")
        
        # Try primary xpath
        print("\nTrying primary xpath...")
        desc_el = await page.query_selector('xpath=/html/body/div[1]/div/div[1]/div/div[3]/div/div/div[1]/div[1]/div[2]/div/div/div/div/div/div[1]/div[2]/div/div[2]/div/div[1]/div[1]/div[5]/div[2]/div')
        if desc_el:
            print("✅ Primary xpath found!")
            raw_description = await desc_el.inner_text()
        else:
            print("❌ Primary xpath failed, trying fallback...")
            desc_el = await page.query_selector('div.xz9dl7a.xn6708d.xsag5q8.x1ye3gou')
            if desc_el:
                print("✅ Fallback class selector found!")
                raw_description = await desc_el.inner_text()
            else:
                print("❌ Fallback failed, using container...")
                raw_description = (await container.inner_text()) if container else ""
        
        description = clean_text(raw_description)
        print(f"\nRaw description length: {len(raw_description)}")
        print(f"Cleaned description length: {len(description)}")
        print(f"Description preview:\n{description[:500]}")
        
        # Try extraction
        print("\n" + "="*80)
        print("RUNNING AI EXTRACTION")
        print("="*80)
        data = extract_structured_data(title, price_text, description)
        
        mileage = data.get("mileage") if data else None
        if mileage is None:
            print("\nAI returned no mileage, trying regex fallback...")
            mileage = extract_mileage(description)
        
        print(f"\n{'='*80}")
        print(f"RESULT: Mileage = {mileage}")
        print(f"{'='*80}")
        
        await asyncio.sleep(5)  # Keep browser open to inspect
        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_mazda())
