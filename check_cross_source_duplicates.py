"""Check for cross-source duplicates between Bilasölur and dealerships."""

import re
from db.db_setup import SessionLocal
from db.models import CarListing

def check_cross_source_duplicates():
    session = SessionLocal()
    
    # Get all Bilasölur listings
    print("Querying Bilasolur listings...")
    bilasolur_listings = session.query(CarListing).filter(
        CarListing.source == 'Bilasolur'
    ).all()
    
    print(f"Found {len(bilasolur_listings)} Bilasolur listings")
    
    # Extract cid (car ID) from Bilasölur URLs and map to dealership IDs
    pattern = re.compile(r'cid=(\d+)')
    duplicates = []
    
    for bilasolur_car in bilasolur_listings:
        match = pattern.search(bilasolur_car.url)
        if match:
            car_id = match.group(1)
            
            # Check if any dealership has this ID in their URL
            dealership_match = session.query(CarListing).filter(
                CarListing.source.in_(['Hekla', 'Brimborg', 'BR', 'Islandsbilar']),
                CarListing.url.like(f'%{car_id}%')
            ).first()
            
            if dealership_match:
                duplicates.append({
                    'bilasolur': bilasolur_car,
                    'dealership': dealership_match,
                    'car_id': car_id
                })
    
    print(f"Total Bilasölur listings: {len(bilasolur_listings)}")
    print(f"Cross-source duplicates found: {len(duplicates)}\n")
    
    if duplicates:
        print("Sample duplicates (first 10):")
        for i, dup in enumerate(duplicates[:10], 1):
            bs = dup['bilasolur']
            dl = dup['dealership']
            print(f"\n{i}. Car ID {dup['car_id']}:")
            print(f"   Bilasölur (ID {bs.id}): {bs.make} {bs.model} {bs.year} - {bs.price} ISK")
            print(f"   {dl.source} (ID {dl.id}): {dl.make} {dl.model} {dl.year} - {dl.price} ISK")
        
        if len(duplicates) > 10:
            print(f"\n... and {len(duplicates) - 10} more")
    
    session.close()
    return len(duplicates)

if __name__ == "__main__":
    check_cross_source_duplicates()
