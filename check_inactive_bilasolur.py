#!/usr/bin/env python3
"""Check Bilasölur listings without images to see if they're inactive."""

import asyncio
from playwright.async_api import async_playwright
from db.db_setup import SessionLocal
from db.models import CarListing
from datetime import datetime


async def check_inactive_bilasolur_listings():
    """Check each Bilasölur listing without an image to see if it's inactive."""
    
    session = SessionLocal()
    
    # Get all active Bilasölur listings without images
    # Only check listings that are currently marked as active
    listings_no_img = session.query(CarListing).filter_by(source='Bilasolur', is_active=True).filter(
        (CarListing.image_url == None) | (CarListing.image_url == '')
    ).all()
    
    print(f"Found {len(listings_no_img)} active Bilasölur listings without images")
    print("Checking each one to see if it's still active...\n")
    
    if not listings_no_img:
        print("No listings to check!")
        session.close()
        return
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
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
                await page.goto(listing.url, wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(1)
                
                # Check for "Engar upplýsingar fundust um ökutæki." message
                try:
                    inactive_message = await page.query_selector('xpath=/html/body/form/div[6]/div[1]')
                    if inactive_message:
                        text = await inactive_message.inner_text()
                        if "Engar upplýsingar fundust um ökutæki" in text:
                            print(f"  ✗ INACTIVE - Listing no longer exists")
                            listing.is_active = False
                            inactive_count += 1
                            inactive_ids.append(listing.id)
                            continue
                except Exception:
                    pass
                
                # Check for image at the specified xpath
                try:
                    img = await page.query_selector('xpath=/html/body/form/div[7]/div/div[1]/div/div[1]/img[2]')
                    if img:
                        image_url = await img.get_attribute('src')
                        if image_url:
                            if not image_url.startswith('http'):
                                image_url = f"https://bilasolur.is{image_url}"
                            
                            # Update the listing with the image
                            listing.image_url = image_url
                            listing.scraped_at = datetime.utcnow()
                            active_with_image_count += 1
                            print(f"  ✓ ACTIVE with image - Updated: {image_url[:60]}...")
                        else:
                            active_no_image_count += 1
                            print(f"  ? ACTIVE but no image src found")
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
    asyncio.run(check_inactive_bilasolur_listings())
