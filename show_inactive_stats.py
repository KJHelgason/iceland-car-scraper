#!/usr/bin/env python3
"""Show breakdown of active/inactive listings by source."""

from db.db_setup import SessionLocal
from db.models import CarListing
from sqlalchemy import func

session = SessionLocal()

results = session.query(
    CarListing.source,
    CarListing.is_active,
    func.count(CarListing.id)
).group_by(
    CarListing.source,
    CarListing.is_active
).all()

by_source = {}
for src, is_active, cnt in results:
    if src not in by_source:
        by_source[src] = {'active': 0, 'inactive': 0}
    if is_active:
        by_source[src]['active'] = cnt
    else:
        by_source[src]['inactive'] = cnt

print('\nInactive Listings Breakdown by Source:')
print('=' * 80)
print(f"{'Source':<20} {'Active':>7} {'Inactive':>9} {'Total':>7} {'% Inactive':>12}")
print('-' * 80)

total_active = 0
total_inactive = 0

for src in sorted(by_source.keys()):
    data = by_source[src]
    active = data['active']
    inactive = data['inactive']
    total = active + inactive
    pct = (inactive / total * 100) if total > 0 else 0
    
    total_active += active
    total_inactive += inactive
    
    print(f"{src:<20} {active:7,} {inactive:9,} {total:7,} {pct:11.1f}%")

print('-' * 80)
grand_total = total_active + total_inactive
grand_pct = (total_inactive / grand_total * 100) if grand_total > 0 else 0
print(f"{'TOTAL':<20} {total_active:7,} {total_inactive:9,} {grand_total:7,} {grand_pct:11.1f}%")
print('=' * 80)

session.close()
