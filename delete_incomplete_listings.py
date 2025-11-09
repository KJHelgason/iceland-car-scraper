#!/usr/bin/env python3
"""Delete incomplete listings that are marked as inactive.

This script removes listings that:
1. Are marked as is_active=False (already confirmed dead/sold)
2. Have missing critical data fields (price, make, model, year, or kilometers)

Complete listings (with all required fields) are kept for ML training even if inactive.
Only incomplete AND inactive listings are deleted to clean up database clutter.
"""

import asyncio
from db.db_setup import SessionLocal
from db.models import CarListing
from sqlalchemy import select, and_
from datetime import datetime
from utils.s3_cleanup import delete_s3_image


def is_incomplete(listing: CarListing) -> bool:
    """Check if a listing is missing critical fields."""
    return not all([
        listing.make,
        listing.model,
        listing.year is not None,
        listing.price is not None,
        listing.kilometers is not None
    ])


async def delete_incomplete_listings(batch_size: int = 100):
    """Delete incomplete listings that are marked inactive."""
    
    session = SessionLocal()
    
    print("=== Deleting Incomplete Inactive Listings ===\n")
    
    # Get all sources
    sources = session.query(CarListing.source).distinct().all()
    sources = [s[0] for s in sources]
    
    total_deleted = 0
    
    for source in sources:
        print(f"--- {source} ---")
        
        # Get all inactive listings for this source
        inactive_listings = session.execute(
            select(CarListing)
            .where(CarListing.source == source)
            .where(CarListing.is_active == False)
        ).scalars().all()
        
        if not inactive_listings:
            print(f"  No inactive listings found\n")
            continue
        
        print(f"  Found {len(inactive_listings)} inactive listings")
        
        # Filter to only incomplete ones
        incomplete_listings = [l for l in inactive_listings if is_incomplete(l)]
        
        if not incomplete_listings:
            print(f"  All inactive listings are complete (kept for ML)\n")
            continue
        
        print(f"  Found {len(incomplete_listings)} incomplete listings to delete")
        
        deleted_count = 0
        for idx, listing in enumerate(incomplete_listings, 1):
            try:
                # Show what's missing
                missing_fields = []
                if not listing.make:
                    missing_fields.append("make")
                if not listing.model:
                    missing_fields.append("model")
                if listing.year is None:
                    missing_fields.append("year")
                if listing.price is None:
                    missing_fields.append("price")
                if listing.kilometers is None:
                    missing_fields.append("kilometers")
                
                missing_str = ", ".join(missing_fields)
                title_preview = listing.title[:40] if listing.title else "No title"
                print(f"    [{idx}/{len(incomplete_listings)}] Deleting: {title_preview} (missing: {missing_str})")
                
                # Delete S3 image if exists
                if listing.image_url:
                    delete_s3_image(listing.image_url)
                
                session.delete(listing)
                deleted_count += 1
                
                # Commit in batches
                if deleted_count % batch_size == 0:
                    try:
                        session.commit()
                        print(f"    ✓ Committed batch of {batch_size}")
                    except Exception as e:
                        print(f"    ✗ Batch commit error: {e}")
                        session.rollback()
            
            except Exception as e:
                print(f"    ✗ Error deleting listing {listing.id}: {e}")
                session.rollback()
                continue
        
        # Final commit for this source
        try:
            session.commit()
            print(f"  ✓ Final commit for {source}")
        except Exception as e:
            print(f"  ✗ Final commit error: {e}")
            session.rollback()
        
        print(f"  Deleted: {deleted_count}")
        print(f"  Kept for ML: {len(inactive_listings) - deleted_count} (complete but inactive)\n")
        
        total_deleted += deleted_count
    
    session.close()
    
    print(f"=== Summary ===")
    print(f"Total incomplete inactive listings deleted: {total_deleted}")
    
    return total_deleted


if __name__ == "__main__":
    asyncio.run(delete_incomplete_listings(batch_size=100))
