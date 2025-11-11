#!/usr/bin/env python3
"""
Quick test of Facebook scraper improvements with parts filtering.
"""

import asyncio
from scrapers.facebook_scraper import scrape_facebook

async def test():
    print("="*80)
    print("🧪 TESTING IMPROVED FACEBOOK SCRAPER")
    print("="*80)
    print("New features:")
    print("  1. Pre-filter: Skips obvious parts before AI call")
    print("  2. AI Classification: AI decides if listing is a vehicle or part")
    print("  3. Icelandic keywords: Understands Icelandic part names")
    print("="*80)
    print()
    
    # Use existing seed URLs if available
    import os
    if os.path.exists("facebook_seed_links.txt"):
        with open("facebook_seed_links.txt", "r") as f:
            seed_urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        print(f"📄 Loaded {len(seed_urls)} URLs from facebook_seed_links.txt")
        await scrape_facebook(max_items=10, start_urls=seed_urls)
    else:
        print("❌ No seed URLs found. Run discovery first or use test_facebook_scraper.py")
        await scrape_facebook(max_items=10)

if __name__ == "__main__":
    asyncio.run(test())
