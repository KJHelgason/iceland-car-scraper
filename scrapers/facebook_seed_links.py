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


async def discover_facebook_links(max_scrolls=50):
    """Scroll Facebook Marketplace and collect all listing URLs.
    
    Args:
        max_scrolls: Maximum number of scroll iterations
        
    Returns:
        List of listing URLs
    """
    
    if not os.path.exists(COOKIES_FILE):
        print(f"Error: {COOKIES_FILE} not found. Please run save_fb_cookies.py first.")
        return []
    
    with open(COOKIES_FILE, "r") as f:
        state = json.load(f)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(storage_state=state)
        page = await context.new_page()
        
        print(f"Navigating to {FB_URL}")
        await page.goto(FB_URL, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)
        
        # Set to track unique URLs
        listing_urls = set()
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
            print(f"Scroll {scroll_count}/{max_scrolls}: Found {new_items} new listings (total: {len(listing_urls)})")
            
            # Check if we're getting new items
            if new_items == 0:
                no_new_items_count += 1
                if no_new_items_count >= 3:
                    print("No new listings found after 3 scrolls. Stopping.")
                    break
            else:
                no_new_items_count = 0
            
            # Scroll to bottom
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)
        
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
