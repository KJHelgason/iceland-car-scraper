#!/usr/bin/env python3
"""
Comprehensive check of all active listings across all sources to detect inactive/expired listings.
"""

import asyncio
import json
import os
from playwright.async_api import async_playwright
from db.db_setup import SessionLocal
from db.models import CarListing
from datetime import datetime, timedelta

FB_COOKIES_FILE = "fb_state.json"


async def check_listing_active(page, listing, source):
    """
    Check if a listing is still active by visiting its URL.
    Returns: (is_active: bool, reason: str)
    """
    try:
        await page.goto(listing.url, wait_until="domcontentloaded", timeout=15000)
        await asyncio.sleep(1.5)
        
        current_url = page.url
        page_content = await page.content()
        page_text_lower = page_content.lower()
        
        # Facebook Marketplace specific checks
        if source == "Facebook Marketplace":
            if 'unavailable_product' in current_url:
                return False, "Redirected to unavailable_product"
            
            # Check for "Sold" in title (common indicator)
            try:
                title_el = await page.query_selector('h1 span[dir="auto"]')
                if title_el:
                    title_text = (await title_el.inner_text()).lower()
                    if title_text.startswith('sold') or '\nsold\n' in title_text:
                        return False, "Title shows 'Sold'"
            except Exception:
                pass
            
            if any(phrase in page_text_lower for phrase in [
                "this content isn't available",
                "content not found",
                "page not found",
                "listing is no longer available",
                "item has been sold",
                "removed by the seller",
                "this listing has been removed"
            ]):
                return False, "Facebook removed/unavailable message"
        
        # Bilasolur specific checks
        elif source == "Bilasolur":
            # Check if redirected away from listing page
            if 'CarDetails.aspx' not in current_url:
                return False, "Redirected away from listing page"
            
            # Check for "not found" or error messages
            if any(phrase in page_text_lower for phrase in [
                "ekki til",
                "not found",
                "villa kom upp",
                "error occurred",
                "bifreið fannst ekki"
            ]):
                return False, "Bilasolur error/not found"
            
            # Check if the main content is missing (usually means listing removed)
            has_price = await page.query_selector('span.price, div.price, .car-price')
            if not has_price:
                return False, "No price element found (likely removed)"
        
        # Bilaland specific checks
        elif source == "Bilaland":
            # Check if redirected to homepage or search
            if listing.url not in current_url and '/bil/' not in current_url:
                return False, "Redirected away from listing"
            
            if any(phrase in page_text_lower for phrase in [
                "ekki til",
                "not found",
                "bifreið fannst ekki"
            ]):
                return False, "Bilaland not found"
        
        # Askja specific checks
        elif source == "Askja":
            if 'bilar/bil/' not in current_url:
                return False, "Redirected away from listing"
            
            if any(phrase in page_text_lower for phrase in [
                "ekki til",
                "not found",
                "villa"
            ]):
                return False, "Askja error/not found"
        
        # BR specific checks
        elif source == "BR":
            if '/bilar/notadir-bilar/' not in current_url:
                return False, "Redirected away from listing"
            
            if "ekki til" in page_text_lower or "not found" in page_text_lower:
                return False, "BR not found"
        
        # Brimborg specific checks
        elif source == "Brimborg":
            if '/notadir-bilar/' not in current_url:
                return False, "Redirected away from listing"
            
            if "ekki til" in page_text_lower or "not found" in page_text_lower:
                return False, "Brimborg not found"
        
        # Hekla specific checks
        elif source == "Hekla":
            if '/notadir-bilar/' not in current_url:
                return False, "Redirected away from listing"
            
            if "ekki til" in page_text_lower or "not found" in page_text_lower:
                return False, "Hekla not found"
        
        # If we made it here, listing appears active
        return True, "Active"
        
    except Exception as e:
        return None, f"Error checking: {str(e)[:100]}"


async def check_all_active_listings(sources=None, limit_per_source=None, batch_size=10):
    """
    Check all active listings to see if they're still available.
    Only checks listings that are older than 7 days.
    
    Args:
        sources: List of sources to check (None = all)
        limit_per_source: Max listings to check per source (None = all)
        batch_size: Commit to database every N listings
    """
    session = SessionLocal()
    
    # Only check listings older than 7 days
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    
    # Build query for active listings older than 7 days
    query = session.query(CarListing).filter(
        CarListing.is_active == True,
        CarListing.scraped_at < seven_days_ago
    )
    
    if sources:
        query = query.filter(CarListing.source.in_(sources))
    
    # Get all active listings grouped by source
    all_active = query.all()
    
    # Group by source
    by_source = {}
    for listing in all_active:
        source = listing.source
        if source not in by_source:
            by_source[source] = []
        by_source[source].append(listing)
    
    print(f"Found {len(all_active)} active listings across {len(by_source)} sources")
    print("\nBreakdown:")
    for source, listings in by_source.items():
        count = len(listings)
        if limit_per_source:
            count = min(count, limit_per_source)
        print(f"  {source}: {count} listings to check")
    print()
    
    # Load Facebook cookies if needed
    fb_state = None
    if "Facebook Marketplace" in by_source and os.path.exists(FB_COOKIES_FILE):
        with open(FB_COOKIES_FILE, "r") as f:
            fb_state = json.load(f)
        print("✓ Loaded Facebook cookies\n")
    
    # Track statistics
    stats = {
        'total_checked': 0,
        'still_active': 0,
        'now_inactive': 0,
        'errors': 0,
        'by_source': {}
    }
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        for source, listings in by_source.items():
            print(f"\n{'='*70}")
            print(f"Checking {source}")
            print(f"{'='*70}\n")
            
            # Limit listings if specified
            listings_to_check = listings[:limit_per_source] if limit_per_source else listings
            
            # Create context with Facebook cookies if needed
            if source == "Facebook Marketplace" and fb_state:
                context = await browser.new_context(storage_state=fb_state)
            else:
                context = await browser.new_context()
            
            page = await context.new_page()
            
            source_stats = {
                'checked': 0,
                'still_active': 0,
                'now_inactive': 0,
                'errors': 0
            }
            
            for idx, listing in enumerate(listings_to_check, 1):
                try:
                    print(f"[{idx}/{len(listings_to_check)}] {listing.make} {listing.model} ({listing.year})")
                    print(f"  URL: {listing.url[:80]}...")
                    
                    is_active, reason = await check_listing_active(page, listing, source)
                    
                    if is_active is False:
                        print(f"  ✗ INACTIVE: {reason}")
                        # Only update scraped_at if this is the FIRST time we're marking it inactive
                        # This preserves the "sold_at" timestamp for your website
                        if listing.is_active:  # Was active, now becoming inactive
                            listing.scraped_at = datetime.utcnow()  # Record when it became inactive
                        listing.is_active = False
                        source_stats['now_inactive'] += 1
                        stats['now_inactive'] += 1
                    elif is_active is True:
                        print(f"  ✓ Active")
                        source_stats['still_active'] += 1
                        stats['still_active'] += 1
                    else:
                        print(f"  ? {reason}")
                        source_stats['errors'] += 1
                        stats['errors'] += 1
                    
                    source_stats['checked'] += 1
                    stats['total_checked'] += 1
                    
                    # Commit batch
                    if idx % batch_size == 0:
                        session.commit()
                        print(f"  💾 Committed batch ({source_stats['now_inactive']} deactivated so far)")
                    
                except Exception as e:
                    print(f"  ERROR: {e}")
                    source_stats['errors'] += 1
                    stats['errors'] += 1
                    session.rollback()
            
            # Final commit for this source
            session.commit()
            
            # Print source summary
            print(f"\n{source} Summary:")
            print(f"  Checked: {source_stats['checked']}")
            print(f"  Still Active: {source_stats['still_active']}")
            print(f"  Deactivated: {source_stats['now_inactive']}")
            print(f"  Errors: {source_stats['errors']}")
            
            stats['by_source'][source] = source_stats
            
            await context.close()
        
        await browser.close()
    
    session.close()
    
    # Print final summary
    print(f"\n{'='*70}")
    print("FINAL SUMMARY")
    print(f"{'='*70}")
    print(f"Total Checked: {stats['total_checked']}")
    print(f"Still Active: {stats['still_active']}")
    print(f"Deactivated: {stats['now_inactive']}")
    print(f"Errors: {stats['errors']}")
    print()
    
    for source, source_stats in stats['by_source'].items():
        deactivation_rate = (source_stats['now_inactive'] / source_stats['checked'] * 100) if source_stats['checked'] > 0 else 0
        print(f"{source}:")
        print(f"  {source_stats['now_inactive']}/{source_stats['checked']} deactivated ({deactivation_rate:.1f}%)")


if __name__ == "__main__":
    import sys
    
    # Parse arguments
    sources = None
    limit = None
    batch_size = 10
    
    # Collect all arguments after script name
    args_str = ' '.join(sys.argv[1:])
    
    for arg in sys.argv[1:]:
        if arg.startswith('--sources='):
            sources_str = arg.split('=', 1)[1]
            sources = [s.strip() for s in sources_str.split(',')]
        elif arg.startswith('--limit='):
            limit = int(arg.split('=')[1])
        elif arg.startswith('--batch='):
            batch_size = int(arg.split('=')[1])
    
    print("Comprehensive Active Listing Checker")
    print("=" * 70)
    if sources:
        print(f"Sources: {', '.join(sources)}")
    else:
        print("Sources: ALL")
    
    if limit:
        print(f"Limit per source: {limit}")
    else:
        print("Limit per source: NONE (checking all)")
    
    print(f"Batch size: {batch_size}")
    print()
    
    asyncio.run(check_all_active_listings(
        sources=sources,
        limit_per_source=limit,
        batch_size=batch_size
    ))
