#!/usr/bin/env python3
"""Check Facebook Marketplace listings without images to see if they're inactive."""

import asyncio
import json
import os
from playwright.async_api import async_playwright
from db.db_setup import SessionLocal
from db.models import CarListing
from datetime import datetime

FB_COOKIES_FILE = "fb_state.json"


async def check_inactive_facebook_listings():
    """Check each Facebook listing without an image to see if it's inactive."""
    
    session = SessionLocal()
    
    # Get all active Facebook Marketplace listings without images
    # Only check listings that are currently marked as active
    listings_no_img = session.query(CarListing).filter_by(source='Facebook Marketplace', is_active=True).filter(
        (CarListing.image_url == None) | (CarListing.image_url == '')
    ).all()
    
    print(f"Found {len(listings_no_img)} active Facebook Marketplace listings without images")
    print("Checking each one to see if it's still active...\n")
    
    if not listings_no_img:
        print("No listings to check!")
        session.close()
        return
    
    if not os.path.exists(FB_COOKIES_FILE):
        print(f"Error: {FB_COOKIES_FILE} not found. Please run save_fb_cookies.py first.")
        session.close()
        return
    
    with open(FB_COOKIES_FILE, "r") as f:
        state = json.load(f)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=state)
        page = await context.new_page()
        
        inactive_count = 0
        active_with_image_count = 0
        active_no_image_count = 0
        error_count = 0
        
        inactive_ids = []
        
        for idx, listing in enumerate(listings_no_img, 1):
            try:
                print(f"[{idx}/{len(listings_no_img)}] Checking {listing.title}")
                print(f"  URL: {listing.url}")
                
                # Navigate to the listing page
                try:
                    await page.goto(listing.url, wait_until="domcontentloaded", timeout=15000)
                    await asyncio.sleep(2)
                except Exception as nav_error:
                    print(f"  ERROR navigating: {nav_error}")
                    error_count += 1
                    continue
                
                # Check if URL was redirected to unavailable_product page
                current_url = page.url
                is_inactive = False
                
                if 'unavailable_product' in current_url:
                    print(f"  ✗ INACTIVE - Redirected to unavailable_product")
                    listing.is_active = False
                    inactive_count += 1
                    inactive_ids.append(listing.id)
                    is_inactive = True
                
                if not is_inactive:
                    # Check if listing has been removed or is unavailable
                    # Facebook shows various messages for removed/unavailable listings
                    page_text = await page.content()
                    page_text_lower = page_text.lower()
                    
                    # Check for common "not available" indicators
                    if any(phrase in page_text_lower for phrase in [
                        "this content isn't available",
                        "content not found",
                        "page not found",
                        "listing is no longer available",
                        "item has been sold",
                        "removed by the seller",
                        "this listing has been removed"
                    ]):
                        print(f"  ✗ INACTIVE - Listing no longer available")
                        listing.is_active = False
                        inactive_count += 1
                        inactive_ids.append(listing.id)
                        is_inactive = True
                
                if not is_inactive:
                    # Try to get the image
                    try:
                        # Facebook listing images are typically in img tags with data-visualcompletion attribute
                        img_el = await page.query_selector('img[data-visualcompletion="media-vc-image"]')
                        if not img_el:
                            # Try alternative selector for main image
                            img_el = await page.query_selector('div[role="main"] img[src*="scontent"]')
                        
                        if img_el:
                            image_url = await img_el.get_attribute('src')
                            if image_url and image_url.startswith('http'):
                                # Update the listing with the image
                                listing.image_url = image_url
                                listing.scraped_at = datetime.utcnow()
                                active_with_image_count += 1
                                print(f"  ✓ ACTIVE with image - Updated: {image_url[:60]}...")
                            else:
                                active_no_image_count += 1
                                print(f"  ? ACTIVE but no valid image src found")
                        else:
                            active_no_image_count += 1
                            print(f"  ? ACTIVE but no image element found")
                    except Exception as e:
                        active_no_image_count += 1
                        print(f"  ? Error finding image: {e}")
                
                # Commit every 10 listings
                if idx % 10 == 0:
                    try:
                        session.commit()
                        print(f"  Committed batch")
                    except Exception as commit_error:
                        print(f"  Commit error: {commit_error}")
                        session.rollback()
                
            except Exception as e:
                print(f"  ERROR: {e}")
                error_count += 1
                session.rollback()  # Rollback on error
                continue
        
        # Final commit
        try:
            session.commit()
            print("\nFinal commit successful")
        except Exception as commit_error:
            print(f"\nFinal commit error: {commit_error}")
            session.rollback()
        
        await browser.close()
    
    print(f"\n=== Check Complete ===")
    print(f"Inactive listings (marked is_active=False): {inactive_count}")
    print(f"Active with image (updated): {active_with_image_count}")
    print(f"Active without image: {active_no_image_count}")
    print(f"Errors: {error_count}")
    print(f"Total processed: {len(listings_no_img)}")
    
    if inactive_ids:
        print(f"\n=== Inactive Listing IDs ===")
        print(f"Marked {len(inactive_ids)} listings as inactive (is_active=False)")
        print("Sample of inactive listings:")
        for listing_id in inactive_ids[:20]:  # Show first 20
            inactive = session.get(CarListing, listing_id)
            if inactive:
                print(f"  ID {listing_id}: {inactive.title} - {inactive.url}")
        
        if len(inactive_ids) > 20:
            print(f"  ... and {len(inactive_ids) - 20} more")
    
    session.close()


if __name__ == "__main__":
    asyncio.run(check_inactive_facebook_listings())
