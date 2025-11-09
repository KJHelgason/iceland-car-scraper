"""
Remove cross-source duplicates where Bilasölur listings match dealership listings.
Bilasölur is an aggregator that pulls from Hekla, Brimborg, BR, and Íslandsbílar.
We prefer keeping the original dealership listing over the aggregated one.
"""

import re
from db.db_setup import SessionLocal
from db.models import CarListing
from utils.s3_cleanup import delete_s3_image


def extract_car_id_from_url(url: str) -> str:
    """Extract car ID from various URL formats."""
    if not url:
        return None
    
    # Bilasölur format: ?cid=123456
    match = re.search(r'[?&]cid=(\d+)', url)
    if match:
        return match.group(1)
    
    # Dealership formats: /view/123456 or /123456/ or =123456
    match = re.search(r'/(\d{5,})', url)
    if match:
        return match.group(1)
    
    match = re.search(r'=(\d{5,})', url)
    if match:
        return match.group(1)
    
    return None


def remove_cross_source_duplicates():
    """
    Find and remove cross-source duplicates.
    Strategy: Keep dealership originals, remove Bilasölur aggregated copies.
    """
    session = SessionLocal()
    
    print("[Cross-source] Finding duplicates between Bilasölur and dealerships...")
    
    # Get all Bilasölur listings
    bilasolur_listings = session.query(CarListing).filter(
        CarListing.source == 'Bilasolur'
    ).all()
    
    print(f"[Cross-source] Checking {len(bilasolur_listings)} Bilasölur listings...")
    
    duplicates_to_delete = []
    
    for bilasolur_listing in bilasolur_listings:
        car_id = extract_car_id_from_url(bilasolur_listing.url)
        if not car_id:
            continue
        
        # Check if any dealership has a listing with this ID in their URL
        dealership_match = session.query(CarListing).filter(
            CarListing.source.in_(['Hekla', 'Brimborg', 'BR', 'Islandsbilar']),
            CarListing.url.like(f'%{car_id}%')
        ).first()
        
        if dealership_match:
            duplicates_to_delete.append({
                'bilasolur_id': bilasolur_listing.id,
                'bilasolur_image': bilasolur_listing.image_url,
                'dealership_source': dealership_match.source,
                'dealership_id': dealership_match.id,
                'car_id': car_id
            })
    
    if not duplicates_to_delete:
        print("[Cross-source] No cross-source duplicates found")
        session.close()
        return 0
    
    print(f"[Cross-source] Found {len(duplicates_to_delete)} Bilasölur listings that duplicate dealership listings")
    
    # Delete the Bilasölur duplicates
    deleted_count = 0
    for dup in duplicates_to_delete:
        listing = session.query(CarListing).get(dup['bilasolur_id'])
        if listing:
            # Delete S3 image if exists
            if dup['bilasolur_image']:
                delete_s3_image(dup['bilasolur_image'])
            
            session.delete(listing)
            deleted_count += 1
            
            if deleted_count % 20 == 0:
                session.commit()
                print(f"[Cross-source] Deleted {deleted_count}/{len(duplicates_to_delete)}...")
    
    session.commit()
    print(f"[Cross-source] Removed {deleted_count} Bilasölur duplicates (kept dealership originals)")
    
    session.close()
    return deleted_count


if __name__ == "__main__":
    remove_cross_source_duplicates()
