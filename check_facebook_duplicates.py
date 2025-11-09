"""Check for duplicate Facebook listings by item ID."""

import re
from collections import Counter
from db.db_setup import SessionLocal
from db.models import CarListing

def check_facebook_duplicates():
    session = SessionLocal()
    
    # Get all Facebook listings
    fb_listings = session.query(CarListing.id, CarListing.url, CarListing.make, CarListing.model).filter(
        CarListing.source == 'Facebook Marketplace'
    ).all()
    
    # Extract item IDs from URLs
    item_ids = []
    pattern = re.compile(r'/marketplace/item/(\d+)')
    
    for listing_id, url, make, model in fb_listings:
        match = pattern.search(url)
        if match:
            item_id = match.group(1)
            item_ids.append((item_id, listing_id, make, model))
        else:
            print(f"Warning: Could not extract item ID from URL: {url}")
    
    # Count occurrences of each item ID
    item_id_counts = Counter([item_id for item_id, _, _, _ in item_ids])
    
    # Find duplicates
    duplicates = {item_id: count for item_id, count in item_id_counts.items() if count > 1}
    total_duplicate_listings = sum(count - 1 for count in duplicates.values())
    
    print(f"Total Facebook listings: {len(fb_listings)}")
    print(f"Unique item IDs: {len(item_id_counts)}")
    print(f"Duplicate item IDs: {len(duplicates)}")
    print(f"Total duplicate listings (extras to remove): {total_duplicate_listings}")
    
    if duplicates:
        print(f"\nTop 10 duplicates:")
        for item_id, count in sorted(duplicates.items(), key=lambda x: x[1], reverse=True)[:10]:
            listings = [(lid, make, model) for iid, lid, make, model in item_ids if iid == item_id]
            print(f"  Item {item_id}: {count} copies")
            for lid, make, model in listings:
                print(f"    - ID {lid}: {make or 'N/A'} {model or 'N/A'}")
    
    session.close()

if __name__ == "__main__":
    check_facebook_duplicates()
