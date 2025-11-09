#!/usr/bin/env python3
"""Check recently marked inactive listings to verify they're actually inactive."""

from db.db_setup import SessionLocal
from db.models import CarListing
from sqlalchemy import select
from datetime import datetime, timedelta

session = SessionLocal()

# Get listings marked inactive in the last 24 hours
yesterday = datetime.utcnow() - timedelta(hours=24)

recent_inactive = session.execute(
    select(CarListing)
    .where(CarListing.is_active == False)
    .where(CarListing.scraped_at >= yesterday)
    .order_by(CarListing.scraped_at.desc())
).scalars().all()

print(f"\n=== Listings Marked Inactive in Last 24 Hours ===")
print(f"Found: {len(recent_inactive)} listings\n")

if recent_inactive:
    by_source = {}
    for listing in recent_inactive:
        source = listing.source
        if source not in by_source:
            by_source[source] = []
        by_source[source].append(listing)
    
    print("Breakdown by source:")
    for source in sorted(by_source.keys()):
        count = len(by_source[source])
        print(f"  {source}: {count} listings")
    
    print(f"\nSample of recently marked inactive:")
    print("-" * 100)
    for i, listing in enumerate(recent_inactive[:20], 1):
        title = listing.title[:50] if listing.title else "No title"
        marked_date = listing.scraped_at.strftime('%Y-%m-%d %H:%M')
        print(f"{i:2d}. [{listing.source}] {title} - Marked: {marked_date}")
        print(f"    URL: {listing.url}")
    
    if len(recent_inactive) > 20:
        print(f"\n... and {len(recent_inactive) - 20} more")
else:
    print("No listings marked inactive in the last 24 hours.")

session.close()
