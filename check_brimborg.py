from db.db_setup import SessionLocal
from db.models import CarListing

session = SessionLocal()

# Get recent listings
results = session.query(CarListing).filter(
    CarListing.source == 'Brimborg'
).order_by(CarListing.scraped_at.desc()).limit(5).all()

print('Recent Brimborg listings:')
for r in results:
    img_preview = r.image_url[:70] + '...' if r.image_url else 'None'
    print(f'{r.make} {r.model} ({r.year}) - {r.price:,} kr - {r.kilometers:,} km')
    print(f'  Image: {img_preview}')
    print()

# Stats
total = session.query(CarListing).filter(CarListing.source == 'Brimborg').count()
with_img = session.query(CarListing).filter(
    CarListing.source == 'Brimborg',
    CarListing.image_url != None
).count()

print(f'Total: {total}, With images: {with_img} ({100*with_img/total:.1f}%)')

session.close()
