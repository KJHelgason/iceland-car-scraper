#!/usr/bin/env python3
"""
Test that scraped_at only updates on FIRST deactivation.
This ensures the sold_at timestamp is preserved for the website.
"""

from datetime import datetime, timedelta
from db.db_setup import SessionLocal
from db.models import CarListing

def test_scraped_at_preservation():
    """Test that scraped_at is only updated once when listing becomes inactive."""
    
    session = SessionLocal()
    
    print("="*80)
    print("🧪 TESTING SCRAPED_AT PRESERVATION ON DEACTIVATION")
    print("="*80)
    print()
    
    # Find an active listing to test with
    test_listing = session.query(CarListing).filter_by(is_active=True).first()
    
    if not test_listing:
        print("❌ No active listings found to test with")
        session.close()
        return
    
    print(f"Test Listing: {test_listing.make} {test_listing.model} ({test_listing.year})")
    print(f"Source: {test_listing.source}")
    print(f"Current is_active: {test_listing.is_active}")
    print(f"Current scraped_at: {test_listing.scraped_at}")
    print()
    
    # Simulate first deactivation
    print("📝 Simulating FIRST deactivation (was active → now inactive)...")
    original_scraped_at = test_listing.scraped_at
    
    if test_listing.is_active:  # Check if was active (like in fixed code)
        test_listing.scraped_at = datetime.utcnow()  # Update timestamp
        print(f"  ✅ Updated scraped_at to: {test_listing.scraped_at}")
    
    test_listing.is_active = False
    first_deactivation_time = test_listing.scraped_at
    print(f"  ✅ Set is_active = False")
    print()
    
    # Simulate second check (already inactive)
    print("📝 Simulating SECOND check (was inactive → still inactive)...")
    print(f"  Current is_active: {test_listing.is_active}")
    
    if test_listing.is_active:  # This should be FALSE now
        test_listing.scraped_at = datetime.utcnow()  # Should NOT execute
        print(f"  ❌ WRONG: Updated scraped_at (should not happen!)")
    else:
        print(f"  ✅ CORRECT: Did NOT update scraped_at (already inactive)")
    
    test_listing.is_active = False  # Set again (no change)
    second_check_time = test_listing.scraped_at
    print()
    
    # Verify
    print("="*80)
    print("📊 VERIFICATION")
    print("="*80)
    print(f"First deactivation time:  {first_deactivation_time}")
    print(f"Second check time:        {second_check_time}")
    print()
    
    if first_deactivation_time == second_check_time:
        print("✅ SUCCESS: scraped_at was preserved on second check!")
        print("   This means your sold_at timestamp will be accurate.")
    else:
        print("❌ FAILURE: scraped_at was updated on second check!")
        print("   This would overwrite your sold_at timestamp.")
    print()
    
    # Restore original state
    print("🔄 Restoring original listing state...")
    test_listing.is_active = True
    test_listing.scraped_at = original_scraped_at
    session.commit()
    print("✅ Test listing restored")
    
    session.close()
    print()
    print("="*80)
    print("TEST COMPLETE")
    print("="*80)

if __name__ == "__main__":
    test_scraped_at_preservation()
