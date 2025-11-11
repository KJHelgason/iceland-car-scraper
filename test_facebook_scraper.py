#!/usr/bin/env python3
"""
Test Facebook scraper with detailed logging.
Tests the improved AI extraction with 10 listings.
"""

import asyncio
from scrapers.facebook_scraper import scrape_facebook
from scrapers.facebook_seed_links import discover_facebook_links

async def test_facebook_scraper():
    """Test Facebook scraper with 10 listings."""
    
    print("="*80)
    print("🧪 FACEBOOK SCRAPER TEST")
    print("="*80)
    print("Testing improved AI extraction with detailed logging")
    print("Will scrape 10 listings to verify:")
    print("  - AI receives correct data")
    print("  - AI returns valid JSON")
    print("  - Validation catches bad data")
    print("="*80)
    print()
    
    # Option 1: Discover fresh URLs (requires Facebook login)
    print("📡 Discovering Facebook listing URLs...")
    seed_urls = await discover_facebook_links(max_scrolls=20)
    
    if not seed_urls:
        print("❌ No URLs discovered. Make sure fb_state.json exists.")
        print("Run: python save_fb_cookies.py")
        return
    
    print(f"✅ Discovered {len(seed_urls)} URLs")
    print()
    
    # Option 2: Use existing seed file (faster, no login needed)
    # import os
    # if os.path.exists("facebook_seed_links.txt"):
    #     with open("facebook_seed_links.txt", "r") as f:
    #         seed_urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    #     print(f"📄 Loaded {len(seed_urls)} URLs from facebook_seed_links.txt")
    
    print("="*80)
    print("🚀 STARTING SCRAPE OF 10 LISTINGS")
    print("="*80)
    print()
    
    # Scrape 10 listings
    await scrape_facebook(max_items=10, start_urls=seed_urls)
    
    print()
    print("="*80)
    print("✅ TEST COMPLETE")
    print("="*80)
    print()
    print("Review the logs above to verify:")
    print("  1. AI INPUT: Title, Price Text, Description")
    print("  2. AI OUTPUT: Raw JSON response")
    print("  3. VALIDATION: Year, Price, Mileage checks")
    print("  4. FINAL RESULT: Saved to database")

if __name__ == "__main__":
    asyncio.run(test_facebook_scraper())
