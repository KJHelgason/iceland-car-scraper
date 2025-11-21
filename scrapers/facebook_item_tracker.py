"""
Utilities for Facebook Marketplace item ID handling and tracking.
"""
import re
from typing import Optional, Set
from datetime import datetime, timedelta


def extract_item_id(url: str) -> Optional[str]:
    """
    Extract Facebook Marketplace item ID from URL.
    
    Examples:
        https://www.facebook.com/marketplace/item/1234567890/ -> '1234567890'
        https://www.facebook.com/marketplace/item/1234567890/?ref=... -> '1234567890'
    
    Args:
        url: Facebook Marketplace listing URL
        
    Returns:
        Item ID string or None if not found
    """
    if not url:
        return None
    
    # Match /marketplace/item/NUMBERS/
    match = re.search(r'/marketplace/item/(\d+)', url)
    if match:
        return match.group(1)
    
    return None


def get_scraped_item_ids() -> Set[str]:
    """
    Get set of all Facebook item IDs that have already been scraped.
    Queries car_listings table and extracts item IDs from URLs.
    
    Returns:
        Set of item ID strings
    """
    import os
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from db.models import CarListing
    
    try:
        DATABASE_URL = os.getenv("DATABASE_URL")
        if not DATABASE_URL:
            return set()
        
        # Convert async URL to sync
        if "asyncpg" in DATABASE_URL:
            DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")
        
        engine = create_engine(DATABASE_URL, echo=False)
        Session = sessionmaker(bind=engine)
        
        with Session() as session:
            result = session.execute(
                select(CarListing.url)
                .where(CarListing.source == "Facebook Marketplace")
            )
            
            item_ids = set()
            for (url,) in result.fetchall():
                item_id = extract_item_id(url)
                if item_id:
                    item_ids.add(item_id)
            
            return item_ids
            
    except Exception as e:
        print(f"⚠️  Could not fetch scraped item IDs: {e}")
        return set()


def get_rejected_item_ids() -> Set[str]:
    """
    Get set of all Facebook item IDs that have been rejected (non-vehicles, errors, etc.).
    Queries rejected_facebook_items table.
    
    Returns:
        Set of rejected item ID strings
    """
    import os
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from db.models import RejectedFacebookItem
    
    try:
        DATABASE_URL = os.getenv("DATABASE_URL")
        if not DATABASE_URL:
            return set()
        
        # Convert async URL to sync
        if "asyncpg" in DATABASE_URL:
            DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")
        
        engine = create_engine(DATABASE_URL, echo=False)
        Session = sessionmaker(bind=engine)
        
        with Session() as session:
            result = session.execute(
                select(RejectedFacebookItem.item_id)
            )
            
            return {item_id for (item_id,) in result.fetchall()}
            
    except Exception as e:
        print(f"⚠️  Could not fetch rejected item IDs: {e}")
        return set()


def add_rejected_item(item_id: str, reason: str, notes: Optional[str] = None):
    """
    Add an item ID to the rejected list.
    
    Args:
        item_id: Facebook Marketplace item ID
        reason: Rejection reason ('non_vehicle', 'navigation_failed', 'invalid_data')
        notes: Optional additional details
    """
    import os
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from db.models import RejectedFacebookItem
    
    try:
        DATABASE_URL = os.getenv("DATABASE_URL")
        if not DATABASE_URL:
            return
        
        # Convert async URL to sync
        if "asyncpg" in DATABASE_URL:
            DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")
        
        engine = create_engine(DATABASE_URL, echo=False)
        Session = sessionmaker(bind=engine)
        
        with Session() as session:
            # Check if already exists
            existing = session.query(RejectedFacebookItem).filter_by(item_id=item_id).first()
            if existing:
                # Update reason and timestamp
                existing.reason = reason
                existing.rejected_at = datetime.utcnow()
                if notes:
                    existing.notes = notes
            else:
                # Add new
                rejected = RejectedFacebookItem(
                    item_id=item_id,
                    reason=reason,
                    notes=notes
                )
                session.add(rejected)
            
            session.commit()
            
    except Exception as e:
        print(f"⚠️  Could not add rejected item {item_id}: {e}")


def update_last_seen(url: str):
    """
    Update last_seen_at timestamp for a listing URL.
    Called during discovery when we see the listing is still active on Facebook.
    
    Args:
        url: Facebook Marketplace listing URL
    """
    import os
    from sqlalchemy import create_engine, update
    from sqlalchemy.orm import sessionmaker
    from db.models import CarListing
    
    try:
        DATABASE_URL = os.getenv("DATABASE_URL")
        if not DATABASE_URL:
            return
        
        # Convert async URL to sync
        if "asyncpg" in DATABASE_URL:
            DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")
        
        engine = create_engine(DATABASE_URL, echo=False)
        Session = sessionmaker(bind=engine)
        
        with Session() as session:
            session.execute(
                update(CarListing)
                .where(CarListing.url == url)
                .values(last_seen_at=datetime.utcnow())
            )
            session.commit()
            
    except Exception as e:
        # Silently fail - not critical
        pass


def mark_old_listings_inactive(days_threshold: int = 7):
    """
    Mark listings as inactive if they haven't been seen in discovery for N days.
    This means they were removed/sold on Facebook.
    
    Args:
        days_threshold: Number of days without being seen before marking inactive
        
    Returns:
        Number of listings marked inactive
    """
    import os
    from sqlalchemy import create_engine, update, and_
    from sqlalchemy.orm import sessionmaker
    from db.models import CarListing
    
    try:
        DATABASE_URL = os.getenv("DATABASE_URL")
        if not DATABASE_URL:
            return 0
        
        # Convert async URL to sync
        if "asyncpg" in DATABASE_URL:
            DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")
        
        engine = create_engine(DATABASE_URL, echo=False)
        Session = sessionmaker(bind=engine)
        
        cutoff_date = datetime.utcnow() - timedelta(days=days_threshold)
        
        with Session() as session:
            result = session.execute(
                update(CarListing)
                .where(and_(
                    CarListing.source == "Facebook Marketplace",
                    CarListing.is_active == True,
                    CarListing.last_seen_at < cutoff_date,
                    CarListing.last_seen_at != None
                ))
                .values(is_active=False)
            )
            session.commit()
            
            count = result.rowcount
            if count > 0:
                print(f"✓ Marked {count} old Facebook listings as inactive (not seen in {days_threshold}+ days)")
            
            return count
            
    except Exception as e:
        print(f"⚠️  Could not mark old listings inactive: {e}")
        return 0
