#!/usr/bin/env python3
"""Check how many active listings have images."""

from db.db_setup import SessionLocal
from db.models import CarListing

session = SessionLocal()

# Get all sources
sources = ['Bilasolur', 'Bilaland', 'Facebook Marketplace', 'Íslandsbílar', 'Hekla', 'Brimborg', 'BR']

print("=== Image Coverage Report (Active Listings Only) ===\n")

for source in sources:
    # Active listings
    active_total = session.query(CarListing).filter_by(source=source, is_active=True).count()
    
    if active_total == 0:
        continue
    
    # Active with images
    active_with_img = session.query(CarListing).filter_by(source=source, is_active=True).filter(
        (CarListing.image_url != None) & (CarListing.image_url != '')
    ).count()
    
    # Active without images
    active_no_img = active_total - active_with_img
    
    coverage_pct = (active_with_img / active_total * 100) if active_total > 0 else 0
    
    print(f'{source}:')
    print(f'  Active listings: {active_total}')
    print(f'  With images: {active_with_img} ({coverage_pct:.1f}%)')
    print(f'  Without images: {active_no_img}')
    print()

# Summary of all active listings
total_active = session.query(CarListing).filter_by(is_active=True).count()
total_active_with_img = session.query(CarListing).filter_by(is_active=True).filter(
    (CarListing.image_url != None) & (CarListing.image_url != '')
).count()
total_active_no_img = total_active - total_active_with_img
overall_coverage = (total_active_with_img / total_active * 100) if total_active > 0 else 0

print("=== Overall Summary (Active Only) ===")
print(f'Total active listings: {total_active}')
print(f'With images: {total_active_with_img} ({overall_coverage:.1f}%)')
print(f'Without images: {total_active_no_img}')

# Inactive summary
total_inactive = session.query(CarListing).filter_by(is_active=False).count()
print(f'\nInactive listings (preserved for ML): {total_inactive}')

session.close()
