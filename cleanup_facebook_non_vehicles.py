"""
Clean up Facebook listings that are clearly not vehicles based on their titles.
"""
from db.db_setup import SessionLocal
from db.models import CarListing
from sqlalchemy import and_
from utils.s3_cleanup import delete_s3_image

def cleanup_non_vehicle_listings():
    """Delete Facebook listings that are clearly parts/accessories."""
    
    session = SessionLocal()
    
    # Keywords that indicate non-vehicle listings
    non_vehicle_keywords = [
        "rims",
        "dekk til sölu",
        "felgur til sölu", 
        "hleðslusnúra",
        "hle slusnúra",  # typo version
        "pallhús",
        "charging cable",
        "tires for sale",
        "wheels for sale",
    ]
    
    # Find Facebook listings with these keywords in title or model
    deleted_count = 0
    
    for keyword in non_vehicle_keywords:
        listings = session.query(CarListing).filter(
            and_(
                CarListing.source == "Facebook Marketplace",
                (CarListing.title.ilike(f"%{keyword}%") | CarListing.model.ilike(f"%{keyword}%"))
            )
        ).all()
        
        if listings:
            print(f"\nKeyword '{keyword}': Found {len(listings)} listings")
            for listing in listings:
                print(f"  Deleting: {listing.make} {listing.model} - {listing.title}")
                
                # Delete S3 image if exists
                if listing.image_url:
                    delete_s3_image(listing.image_url)
                
                session.delete(listing)
                deleted_count += 1
    
    session.commit()
    session.close()
    
    print(f"\n{'='*80}")
    print(f"SUMMARY: Deleted {deleted_count} non-vehicle listings")
    print(f"{'='*80}")

if __name__ == "__main__":
    cleanup_non_vehicle_listings()
