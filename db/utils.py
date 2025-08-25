from db.db_setup import SessionLocal
from db.models import CarListing, ReferencePrice
from sqlalchemy import func
from datetime import datetime

def update_reference_prices():
    session = SessionLocal()
    print("Updating reference price table...")

    # Query: group dealership listings by make, model, year
    rows = session.query(
        CarListing.make,
        CarListing.model,
        CarListing.year,
        func.avg(CarListing.price).label("avg_price"),
        func.min(CarListing.price).label("min_price"),
        func.max(CarListing.price).label("max_price"),
        func.count().label("count")
    ).filter(
        CarListing.source.in_(["Bilasolur", "Bilaland"])
    ).filter(
        CarListing.price.isnot(None)
    ).group_by(
        CarListing.make, CarListing.model, CarListing.year
    ).all()

    # Clear old reference prices
    session.query(ReferencePrice).delete()

    # Insert updated aggregates
    for row in rows:
        ref = ReferencePrice(
            make=row.make,
            model=row.model,
            year=row.year,
            avg_price=row.avg_price,
            min_price=row.min_price,
            max_price=row.max_price,
            count=row.count,
            updated_at=datetime.utcnow()
        )
        session.add(ref)

    session.commit()
    session.close()
    print("Reference price table updated.")
