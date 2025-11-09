"""
Quick test script to check BR listings
"""
from db.db_setup import SessionLocal
from db.models import CarListing
from sqlalchemy import func

session = SessionLocal()

# Get recent BR listings
recent = session.query(CarListing).filter_by(source="BR").order_by(CarListing.scraped_at.desc()).limit(20).all()

print(f"\n=== Recent BR Listings ===")
for car in recent:
    price_str = f"{car.price:,} kr" if car.price else "N/A"
    km_str = f"{car.kilometers:,} km" if car.kilometers else "N/A"
    print(f"{car.make} {car.model} ({car.year}) - {price_str} - {km_str}")
    if car.image_url:
        print(f"  Image: {car.image_url[:80]}...")
    print(f"  URL: {car.url}")
    print()

# Stats
total = session.query(func.count(CarListing.id)).filter_by(source="BR").scalar()
with_images = session.query(func.count(CarListing.id)).filter_by(source="BR").filter(CarListing.image_url.isnot(None)).scalar()

print(f"Total: {total}, With images: {with_images} ({100*with_images/total if total > 0 else 0:.1f}%)")

session.close()
