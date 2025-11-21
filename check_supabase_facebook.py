"""Check Facebook listing additions in Supabase database."""
import os
import psycopg2
from datetime import datetime, timedelta

# Parse Supabase connection string
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://postgres.jfyzfhamueqecqxyzaov:MagnusPalmi.!@aws-0-eu-west-2.pooler.supabase.com:6543/postgres?sslmode=require")

# Convert SQLAlchemy URL to psycopg2 format
db_url = DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://")

print("🔍 Connecting to Supabase database...")
print("=" * 60)

try:
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    
    # 1. Total Facebook listings
    cur.execute("""
        SELECT COUNT(*) 
        FROM car_listings 
        WHERE source = 'Facebook Marketplace'
    """)
    total_fb = cur.fetchone()[0]
    print(f"📊 Total Facebook listings: {total_fb:,}")
    
    # 2. Active Facebook listings
    cur.execute("""
        SELECT COUNT(*) 
        FROM car_listings 
        WHERE source = 'Facebook Marketplace' AND is_active = TRUE
    """)
    active_fb = cur.fetchone()[0]
    print(f"✅ Active Facebook listings: {active_fb:,}")
    
    # 3. Listings first seen in last 24 hours (based on scraped_at as proxy)
    cur.execute("""
        SELECT COUNT(*) 
        FROM car_listings 
        WHERE source = 'Facebook Marketplace' 
        AND scraped_at >= NOW() - INTERVAL '24 hours'
        AND scraped_at IS NOT NULL
    """)
    new_24h = cur.fetchone()[0]
    print(f"🆕 New/updated in last 24 hours: {new_24h}")
    
    # 4. Listings from last 7 days
    cur.execute("""
        SELECT COUNT(*) 
        FROM car_listings 
        WHERE source = 'Facebook Marketplace' 
        AND scraped_at >= NOW() - INTERVAL '7 days'
        AND scraped_at IS NOT NULL
    """)
    new_7d = cur.fetchone()[0]
    print(f"📅 New/updated in last 7 days: {new_7d}")
    
    # 5. Listings scraped in last 24 hours
    cur.execute("""
        SELECT COUNT(*) 
        FROM car_listings 
        WHERE source = 'Facebook Marketplace' 
        AND scraped_at >= NOW() - INTERVAL '24 hours'
    """)
    scraped_24h = cur.fetchone()[0]
    print(f"🔄 Scraped in last 24 hours: {scraped_24h}")
    
    # 6. Most recent scrapes
    print(f"\n{'=' * 60}")
    print("🔥 Most recent 15 Facebook scrapes:")
    print("=" * 60)
    cur.execute("""
        SELECT 
            TO_CHAR(scraped_at, 'YYYY-MM-DD HH24:MI') as scraped,
            year, make, model, price
        FROM car_listings 
        WHERE source = 'Facebook Marketplace'
        AND scraped_at IS NOT NULL
        ORDER BY scraped_at DESC
        LIMIT 15
    """)
    
    for row in cur.fetchall():
        scraped, year, make, model, price = row
        print(f"  {scraped}: {year} {make} {model} - {price:,} ISK")
    
    # 7. Search for Hyundai Santa Fe 2003
    print(f"\n{'=' * 60}")
    print("🔍 Searching for Hyundai Santa Fe 2003...")
    print("=" * 60)
    cur.execute("""
        SELECT 
            id, is_active, price, url,
            TO_CHAR(scraped_at, 'YYYY-MM-DD HH24:MI') as scraped
        FROM car_listings 
        WHERE source = 'Facebook Marketplace'
        AND make ILIKE '%hyundai%'
        AND model ILIKE '%santa%'
        AND year = 2003
    """)
    
    results = cur.fetchall()
    if results:
        print(f"✅ Found {len(results)} Hyundai Santa Fe 2003:")
        for row in results:
            id, active, price, url, scraped = row
            print(f"\n  ID: {id}")
            print(f"  Active: {active}")
            print(f"  Price: {price:,} ISK")
            print(f"  Last scraped: {scraped}")
            print(f"  URL: {url}")
    else:
        print("❌ No Hyundai Santa Fe 2003 found")
        
        # Search for any Santa Fe
        print("\n🔍 Searching for ANY Hyundai Santa Fe (any year)...")
        cur.execute("""
            SELECT year, is_active, price, 
                   TO_CHAR(scraped_at, 'YYYY-MM-DD') as last_seen
            FROM car_listings 
            WHERE source = 'Facebook Marketplace'
            AND make ILIKE '%hyundai%'
            AND model ILIKE '%santa%'
            ORDER BY year DESC
        """)
        
        all_santa = cur.fetchall()
        if all_santa:
            print(f"Found {len(all_santa)} Hyundai Santa Fe (any year):")
            for row in all_santa:
                year, active, price, last_seen = row
                status = "✅" if active else "❌"
                print(f"  {status} {year} - {price:,} ISK (last seen {last_seen})")
        else:
            print("❌ No Hyundai Santa Fe found at all")
    
    # 8. Check for 2003 Hyundai listings
    print(f"\n{'=' * 60}")
    print("🔍 All 2003 Hyundai on Facebook:")
    cur.execute("""
        SELECT make, model, is_active, price
        FROM car_listings 
        WHERE source = 'Facebook Marketplace'
        AND make ILIKE '%hyundai%'
        AND year = 2003
        ORDER BY model
    """)
    
    hyundai_2003 = cur.fetchall()
    if hyundai_2003:
        print(f"Found {len(hyundai_2003)} Hyundai 2003 models:")
        for row in hyundai_2003:
            make, model, active, price = row
            status = "✅" if active else "❌"
            print(f"  {status} {make} {model} - {price:,} ISK")
    else:
        print("❌ No 2003 Hyundai found")
    
    # 9. Daily scrape activity trend
    print(f"\n{'=' * 60}")
    print("📈 Facebook scraping activity per day (last 7 days):")
    print("=" * 60)
    cur.execute("""
        SELECT 
            TO_CHAR(scraped_at, 'YYYY-MM-DD') as day,
            COUNT(*) as scrapes
        FROM car_listings 
        WHERE source = 'Facebook Marketplace'
        AND scraped_at >= NOW() - INTERVAL '7 days'
        AND scraped_at IS NOT NULL
        GROUP BY TO_CHAR(scraped_at, 'YYYY-MM-DD')
        ORDER BY day DESC
    """)
    
    for row in cur.fetchall():
        day, count = row
        print(f"  {day}: {count:3d} listings scraped")
    
    cur.close()
    conn.close()
    
    print(f"\n{'=' * 60}")
    print("✅ Query complete")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
