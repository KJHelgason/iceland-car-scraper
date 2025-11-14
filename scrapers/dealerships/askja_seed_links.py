import asyncio
from playwright.async_api import async_playwright, TimeoutError as PwTimeout
from scrapers.dealerships.askja_scraper import scrape_askja

BASE_URL = "https://www.notadir.is/"


async def discover_askja_links():
    """
    Discover manufacturer-specific URLs from Askja (notadir.is).
    Clicks "Sjá alla framleiðendur" and extracts manufacturer filter links.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        print(f"Navigating to {BASE_URL}...")
        await page.goto(BASE_URL)
        await asyncio.sleep(2)
        
        # Click "Sjá alla framleiðendur" to expand manufacturer list
        try:
            show_all_button = await page.wait_for_selector('a:has-text("Sjá alla framleiðendur")', timeout=10000)
            print("Clicking 'Sjá alla framleiðendur'...")
            await show_all_button.click()
            await asyncio.sleep(1)
        except PwTimeout:
            print("Could not find 'Sjá alla framleiðendur' button")
            await browser.close()
            return []
        
        # Get all manufacturer links from the list
        # They are in li elements under the ul
        manufacturer_list = await page.query_selector('xpath=/html/body/div[4]/div[2]/div[1]/div/div/div[2]/ul')
        
        if not manufacturer_list:
            print("Could not find manufacturer list")
            await browser.close()
            return []
        
        # Get all li elements
        manufacturer_items = await manufacturer_list.query_selector_all('li')
        print(f"Found {len(manufacturer_items)} manufacturer options")
        
        manufacturer_urls = []
        
        for item in manufacturer_items:
            try:
                # Get the link or button within the li
                link = await item.query_selector('a, button')
                if not link:
                    continue
                
                # Get manufacturer name from text
                manufacturer_text = await link.inner_text()
                manufacturer_text = manufacturer_text.strip()
                
                # Get the data attribute or construct URL
                # The filters create URLs like: https://www.notadir.is/#&manufacturer=Mercedes-Benz
                data_value = await link.get_attribute('data-value')
                if not data_value:
                    # Try to get from onclick or other attributes
                    data_value = manufacturer_text.replace(' ', '-')
                
                url = f"{BASE_URL}#&manufacturer={data_value}"
                
                print(f"Make: {manufacturer_text} -> {url}")
                manufacturer_urls.append(url)
                
            except Exception as e:
                print(f"Error processing manufacturer item: {e}")
                continue
        
        await browser.close()
        
        # Remove duplicates and save to file
        unique_urls = list(set(manufacturer_urls))
        unique_urls.sort()
        
        print(f"\n=== Discovered {len(unique_urls)} unique manufacturer URLs ===")
        for url in unique_urls:
            print(url)
        
        # Save to file
        with open("askja_seed_links.txt", "w", encoding="utf-8") as f:
            for url in unique_urls:
                f.write(url + "\n")
        
        print(f"\nSaved {len(unique_urls)} URLs to askja_seed_links.txt")
        return unique_urls


async def scrape_all_askja_makes(max_clicks: int = 50):
    """
    Discover all manufacturer URLs and scrape each one.
    """
    print("Discovering manufacturer URLs...")
    urls = await discover_askja_links()
    
    print(f"\nDiscovered {len(urls)} seed URLs")
    
    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{len(urls)}] Scraping {url}")
        await scrape_askja(max_clicks=max_clicks, start_url=url)


if __name__ == "__main__":
    asyncio.run(discover_askja_links())
