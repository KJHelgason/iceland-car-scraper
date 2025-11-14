#!/usr/bin/env python3
"""Discover Facebook Marketplace vehicle listing URLs by scrolling.

This script scrolls through Facebook Marketplace to collect all listing URLs,
which can then be scraped incrementally throughout the day.
"""

import asyncio
import json
import os
from datetime import datetime
from playwright.async_api import async_playwright

FB_URL = "https://www.facebook.com/marketplace/category/vehicles"
COOKIES_FILE = "fb_state.json"
SEED_LINKS_FILE = "facebook_seed_links.txt"

# Popular car makes in Iceland for targeted searches
POPULAR_MAKES = [
    "toyota", "volkswagen", "audi", "bmw", "mercedes", "ford",
    "nissan", "hyundai", "kia", "mazda", "honda", "subaru",
    "volvo", "skoda", "lexus", "land rover", "tesla"
]

# Iceland location IDs for Facebook Marketplace
ICELAND_LOCATIONS = [
    "107355129303469",  # Reykjavik
    "109302625749025",  # Iceland (country)
]


async def discover_facebook_links(max_scrolls=100):
    """Scroll Facebook Marketplace and collect all listing URLs.
    Uses targeted searches for Iceland and popular car makes.
    
    Args:
        max_scrolls: Maximum number of scroll iterations per search
        
    Returns:
        List of listing URLs
    """
    
    if not os.path.exists(COOKIES_FILE):
        print(f"Error: {COOKIES_FILE} not found. Please run save_fb_cookies.py first.")
        return []
    
    with open(COOKIES_FILE, "r") as f:
        state = json.load(f)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=state)
        page = await context.new_page()
        
        # Set to track unique URLs
        listing_urls = set()
        
        # Search strategies
        # Category parameter: categoryID=vehicles (807311116126722)
        search_urls = [
            # General Iceland vehicle marketplace
            FB_URL,
            "https://www.facebook.com/marketplace/107355129303469/vehicles",  # Reykjavik vehicles
            
            # All major makes in Iceland - vehicles only
            "https://www.facebook.com/marketplace/107355129303469/search/?query=aiways&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=audi&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=bmw&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=byd&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=cadillac&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=can%20am&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=chevrolet&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=chrysler&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=dacia&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=dodge&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=fiat&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=ford&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=gmc&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=honda&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=hongqi&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=hummer&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=hyundai&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=jaguar&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=jeep&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=kia&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=koda&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=land%20rover&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=lexus&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=mazda&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=mercedes&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=mg&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=mini&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=mitsubishi&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=nissan&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=opel&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=peugeot&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=polaris&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=polestar&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=porsche&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=renault&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=scania&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=skoda&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=smart&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=ssangyong&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=subaru&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=suzuki&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=tesla&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=toyota&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=volkswagen&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=volvo&categoryID=807311116126722",
            "https://www.facebook.com/marketplace/107355129303469/search/?query=yamaha&categoryID=807311116126722",
        ]
        
        for search_idx, search_url in enumerate(search_urls, 1):
            print(f"\n[{search_idx}/{len(search_urls)}] Searching: {search_url}")
            
            try:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
                await asyncio.sleep(3)
                
                scroll_count = 0
                no_new_items_count = 0
                
                while scroll_count < max_scrolls:
                    scroll_count += 1
                    
                    # Get all listing links on the page
                    links = await page.query_selector_all('a[href*="/marketplace/item/"]')
                    
                    before_count = len(listing_urls)
                    for link in links:
                        href = await link.get_attribute("href")
                        if href and "/marketplace/item/" in href:
                            # Clean URL - remove query params and hash
                            clean_url = href.split("?")[0].split("#")[0]
                            # Ensure full URL
                            if not clean_url.startswith("http"):
                                clean_url = f"https://www.facebook.com{clean_url}"
                            listing_urls.add(clean_url)
                    
                    new_items = len(listing_urls) - before_count
                    print(f"  Scroll {scroll_count}/{max_scrolls}: Found {new_items} new listings (total: {len(listing_urls)})")
                    
                    # Check if we're getting new items
                    if new_items == 0:
                        no_new_items_count += 1
                        if no_new_items_count >= 3:
                            print("  No new listings found after 3 scrolls. Moving to next search.")
                            break
                    else:
                        no_new_items_count = 0
                    
                    # Scroll to bottom
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(2)
                    
            except Exception as e:
                print(f"  Error searching {search_url}: {e}")
                continue
        
        await browser.close()
    
    # Convert to sorted list
    urls = sorted(list(listing_urls))
    
    # Save to file with timestamp
    with open(SEED_LINKS_FILE, "w", encoding="utf-8") as f:
        f.write(f"# Facebook Marketplace seed links\n")
        f.write(f"# Generated: {datetime.now().isoformat()}\n")
        f.write(f"# Total URLs: {len(urls)}\n")
        f.write("#\n")
        for url in urls:
            f.write(f"{url}\n")
    
    print(f"\nDiscovered {len(urls)} unique listing URLs")
    print(f"Saved to {SEED_LINKS_FILE}")
    
    return urls


if __name__ == "__main__":
    asyncio.run(discover_facebook_links(max_scrolls=50))
