"""Check if Facebook listings are being added and search for specific listing."""
import asyncio
import os
from datetime import datetime, timedelta
from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from db.models import CarListing

async def check_facebook_activity():
    """Analyze Facebook listing activity and search for specific car."""
    
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/iceland_cars")
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # 1. Count total Facebook listings
        result = await session.execute(
            select(func.count(CarListing.id))
            .where(CarListing.source == "Facebook Marketplace")
        )
        total_fb = result.scalar()
        print(f"📊 Total Facebook listings in database: {total_fb}")
        
        # 2. Count active Facebook listings
        result = await session.execute(
            select(func.count(CarListing.id))
            .where(and_(
                CarListing.source == "Facebook Marketplace",
                CarListing.is_active == True
            ))
        )
        active_fb = result.scalar()
        print(f"✅ Active Facebook listings: {active_fb}")
        
        # 3. Count listings added in last 24 hours
        yesterday = datetime.utcnow() - timedelta(days=1)
        result = await session.execute(
            select(func.count(CarListing.id))
            .where(and_(
                CarListing.source == "Facebook Marketplace",
                CarListing.created_at >= yesterday
            ))
        )
        added_24h = result.scalar()
        print(f"🆕 Listings added in last 24 hours: {added_24h}")
        
        # 4. Count listings added in last 7 days
        week_ago = datetime.utcnow() - timedelta(days=7)
        result = await session.execute(
            select(func.count(CarListing.id))
            .where(and_(
                CarListing.source == "Facebook Marketplace",
                CarListing.created_at >= week_ago
            ))
        )
        added_7d = result.scalar()
        print(f"📅 Listings added in last 7 days: {added_7d}")
        
        # 5. Show most recent additions (last 10)
        result = await session.execute(
            select(CarListing)
            .where(CarListing.source == "Facebook Marketplace")
            .order_by(desc(CarListing.created_at))
            .limit(10)
        )
        recent_listings = result.scalars().all()
        
        print(f"\n🔥 Most recent 10 Facebook additions:")
        for listing in recent_listings:
            print(f"  - {listing.created_at.strftime('%Y-%m-%d %H:%M')}: {listing.year} {listing.make} {listing.model} - {listing.price:,} ISK")
        
        # 6. Search for Hyundai Santa Fe 2003
        print(f"\n🔍 Searching for Hyundai Santa Fe 2003...")
        result = await session.execute(
            select(CarListing)
            .where(and_(
                CarListing.source == "Facebook Marketplace",
                CarListing.make.ilike('%hyundai%'),
                CarListing.model.ilike('%santa%'),
                CarListing.year == 2003
            ))
        )
        santa_fe_listings = result.scalars().all()
        
        if santa_fe_listings:
            print(f"✅ Found {len(santa_fe_listings)} Hyundai Santa Fe 2003 listing(s):")
            for listing in santa_fe_listings:
                print(f"  - ID: {listing.id}")
                print(f"    Active: {listing.is_active}")
                print(f"    Price: {listing.price:,} ISK")
                print(f"    URL: {listing.url}")
                print(f"    Created: {listing.created_at}")
                print(f"    Last scraped: {listing.scraped_at}")
        else:
            print("❌ No Hyundai Santa Fe 2003 found in database")
            
            # Search more broadly
            print(f"\n🔍 Searching for ANY Hyundai Santa Fe (any year)...")
            result = await session.execute(
                select(CarListing)
                .where(and_(
                    CarListing.source == "Facebook Marketplace",
                    CarListing.make.ilike('%hyundai%'),
                    CarListing.model.ilike('%santa%')
                ))
                .order_by(desc(CarListing.year))
            )
            all_santa_fe = result.scalars().all()
            
            if all_santa_fe:
                print(f"Found {len(all_santa_fe)} Hyundai Santa Fe listings (any year):")
                for listing in all_santa_fe:
                    print(f"  - {listing.year} {listing.make} {listing.model} - Active: {listing.is_active} - {listing.price:,} ISK")
            else:
                print("❌ No Hyundai Santa Fe listings found at all")
        
        # 7. Check listings updated in last 24 hours (scraped_at)
        result = await session.execute(
            select(func.count(CarListing.id))
            .where(and_(
                CarListing.source == "Facebook Marketplace",
                CarListing.scraped_at >= yesterday
            ))
        )
        updated_24h = result.scalar()
        print(f"\n🔄 Listings scraped/updated in last 24 hours: {updated_24h}")
        
        # 8. Check for errors or issues
        result = await session.execute(
            select(CarListing)
            .where(and_(
                CarListing.source == "Facebook Marketplace",
                CarListing.is_active == True,
                CarListing.year == None  # Missing year suggests scraping issue
            ))
            .limit(5)
        )
        incomplete = result.scalars().all()
        
        if incomplete:
            print(f"\n⚠️  Found {len(incomplete)} active listings with missing year (possible scraping issues):")
            for listing in incomplete[:5]:
                print(f"  - {listing.url}")

if __name__ == "__main__":
    asyncio.run(check_facebook_activity())
