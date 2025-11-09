#!/usr/bin/env python3
"""Check the oldest active listings across all sources to see if they're still active.

This script checks the oldest listings (by scraped_at) to find ones that are no longer
available and marks them as inactive. Runs daily to gradually verify old listings.
"""

import asyncio
from playwright.async_api import async_playwright
from db.db_setup import SessionLocal
from db.models import CarListing
from datetime import datetime
from sqlalchemy import select
import json
import os


# Detection patterns for each source
DETECTION_PATTERNS = {
    'Bilasolur': {
        'inactive_xpath': 'xpath=/html/body/form/div[6]/div[1]',
        'inactive_text': 'Engar upplýsingar fundust um ökutæki',
        'image_xpath': 'xpath=/html/body/form/div[7]/div/div[1]/div/div[1]/img[2]',
    },
    'Bilaland': {
        'inactive_xpath': 'xpath=/html/body/form/div[3]/div[3]/div/div/div',
        'inactive_text': 'Engar upplýsingar fundust um ökutæki',
        'image_xpath': 'xpath=/html/body/form/div[3]/div[3]/div/div/div/div[1]/a/img',
    },
    'Facebook Marketplace': {
        'needs_cookies': True,
        'cookies_file': 'fb_state.json',
        'inactive_phrases': [
            "this content isn't available",
            "content not found",
            "page not found",
            "listing is no longer available",
            "item has been sold",
            "removed by the seller",
            "this listing has been removed"
        ],
        'image_selector': 'img[data-visualcompletion="media-vc-image"]',
        'image_selector_alt': 'div[role="main"] img[src*="scontent"]',
    },
    'Íslandsbílar': {
        'inactive_text': 'Engar niðurstöður fundust',
        'image_selector': 'img.car-image',
    },
    'Hekla': {
        'inactive_text': 'ekki til',
        'image_selector': 'img[src*="hekla"]',
    },
    'Brimborg': {
        'inactive_text': 'ekki lengur til',
        'image_selector': 'img[src*="brimborg"]',
    },
    'BR': {
        'inactive_text': 'ekki til',
        'image_selector': 'img.car-img',
    },
}


async def check_listing_status(page, listing, source_config, context=None):
    """Check if a single listing is still active and try to get image if missing."""
    
    result = {
        'is_active': True,
        'image_url': None,
        'error': None
    }
    
    try:
        # Navigate to the listing
        await page.goto(listing.url, wait_until="domcontentloaded", timeout=15000)
        await asyncio.sleep(1)
        
        # Check for inactive indicators
        is_inactive = False
        
        # Method 1: Check for inactive xpath/text
        if 'inactive_xpath' in source_config:
            try:
                inactive_el = await page.query_selector(source_config['inactive_xpath'])
                if inactive_el:
                    text = await inactive_el.inner_text()
                    if source_config['inactive_text'] in text:
                        is_inactive = True
            except Exception:
                pass
        
        # Method 2: Check page content for inactive phrases
        if 'inactive_phrases' in source_config:
            page_text = await page.content()
            page_text_lower = page_text.lower()
            if any(phrase in page_text_lower for phrase in source_config['inactive_phrases']):
                is_inactive = True
        
        # Method 3: Simple text search
        if 'inactive_text' in source_config and 'inactive_xpath' not in source_config:
            page_text = await page.content()
            if source_config['inactive_text'] in page_text:
                is_inactive = True
        
        result['is_active'] = not is_inactive
        
        # If active and no image, try to get image
        if not is_inactive and not listing.image_url:
            image_url = None
            
            # Try xpath first
            if 'image_xpath' in source_config:
                try:
                    img_el = await page.query_selector(source_config['image_xpath'])
                    if img_el:
                        image_url = await img_el.get_attribute('src')
                except Exception:
                    pass
            
            # Try CSS selector
            if not image_url and 'image_selector' in source_config:
                try:
                    img_el = await page.query_selector(source_config['image_selector'])
                    if img_el:
                        image_url = await img_el.get_attribute('src')
                except Exception:
                    pass
            
            # Try alternative selector for Facebook
            if not image_url and 'image_selector_alt' in source_config:
                try:
                    img_el = await page.query_selector(source_config['image_selector_alt'])
                    if img_el:
                        image_url = await img_el.get_attribute('src')
                except Exception:
                    pass
            
            # Ensure full URL
            if image_url and not image_url.startswith('http'):
                # Get base URL from listing URL
                from urllib.parse import urlparse
                parsed = urlparse(listing.url)
                base_url = f"{parsed.scheme}://{parsed.netloc}"
                image_url = f"{base_url}{image_url}"
            
            result['image_url'] = image_url
    
    except Exception as e:
        result['error'] = str(e)
        # Don't mark as inactive on errors - could be temporary network issues
        # Only mark inactive if we successfully loaded page and found inactive indicators
    
    return result


async def check_oldest_listings(limit_per_source=100):
    """Check the oldest active listings across all sources."""
    
    session = SessionLocal()
    
    # Get all sources with active listings
    sources = session.query(CarListing.source).filter_by(is_active=True).distinct().all()
    sources = [s[0] for s in sources]
    
    print(f"=== Checking Oldest Active Listings ===")
    print(f"Sources found: {sources}\n")
    
    total_checked = 0
    total_marked_inactive = 0
    total_images_updated = 0
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        for source in sources:
            print(f"\n--- {source} ---")
            
            # Get config for this source
            source_config = DETECTION_PATTERNS.get(source, {})
            
            # Get oldest active listings for this source
            oldest_listings = session.execute(
                select(CarListing)
                .where(CarListing.source == source)
                .where(CarListing.is_active == True)
                .order_by(CarListing.scraped_at.asc())
                .limit(limit_per_source)
            ).scalars().all()
            
            print(f"Found {len(oldest_listings)} oldest active listings")
            
            if not oldest_listings:
                continue
            
            # Setup context (needed for Facebook)
            context = None
            if source_config.get('needs_cookies'):
                cookies_file = source_config.get('cookies_file')
                if cookies_file and os.path.exists(cookies_file):
                    with open(cookies_file, 'r') as f:
                        state = json.load(f)
                    context = await browser.new_context(storage_state=state)
                else:
                    print(f"  Warning: {cookies_file} not found, skipping {source}")
                    continue
            else:
                context = await browser.new_context()
            
            page = await context.new_page()
            
            marked_inactive = 0
            images_updated = 0
            
            for idx, listing in enumerate(oldest_listings, 1):
                try:
                    # Check status
                    result = await check_listing_status(page, listing, source_config, context)
                    
                    status_symbol = "✗" if not result['is_active'] else "✓"
                    image_symbol = "🖼️" if result['image_url'] else ""
                    
                    print(f"  [{idx}/{len(oldest_listings)}] {status_symbol} {listing.title[:40]} (scraped: {listing.scraped_at.strftime('%Y-%m-%d')}) {image_symbol}")
                    
                    if result['error']:
                        print(f"    Error: {result['error']}")
                    
                    # Update listing
                    if not result['is_active']:
                        listing.is_active = False
                        listing.scraped_at = datetime.utcnow()  # Update as "sold_at" date
                        marked_inactive += 1
                    
                    if result['image_url']:
                        listing.image_url = result['image_url']
                        images_updated += 1
                    
                    # Commit every 10 listings
                    if idx % 10 == 0:
                        try:
                            session.commit()
                            print(f"    ✓ Committed batch")
                        except Exception as e:
                            print(f"    ✗ Commit error: {e}")
                            session.rollback()
                
                except Exception as e:
                    print(f"  [{idx}/{len(oldest_listings)}] ERROR: {e}")
                    session.rollback()
                    continue
            
            # Final commit for this source
            try:
                session.commit()
                print(f"  ✓ Final commit for {source}")
            except Exception as e:
                print(f"  ✗ Final commit error: {e}")
                session.rollback()
            
            await page.close()
            await context.close()
            
            print(f"\n{source} Summary:")
            print(f"  Checked: {len(oldest_listings)}")
            print(f"  Marked inactive: {marked_inactive}")
            print(f"  Images updated: {images_updated}")
            
            total_checked += len(oldest_listings)
            total_marked_inactive += marked_inactive
            total_images_updated += images_updated
        
        await browser.close()
    
    session.close()
    
    print(f"\n=== Overall Summary ===")
    print(f"Total checked: {total_checked}")
    print(f"Total marked inactive: {total_marked_inactive}")
    print(f"Total images updated: {total_images_updated}")


if __name__ == "__main__":
    asyncio.run(check_oldest_listings(limit_per_source=100))
