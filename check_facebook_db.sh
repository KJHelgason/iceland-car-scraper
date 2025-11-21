#!/bin/bash
# Check Facebook listing additions and search for Santa Fe 2003

echo "📊 Checking Facebook listing activity..."

docker exec -i $(docker ps -q -f name=db) psql -U postgres -d iceland_cars << 'EOF'

-- Total Facebook listings
\echo '========================================='
\echo '📊 Total Facebook listings in database:'
SELECT COUNT(*) FROM car_listings WHERE source = 'Facebook Marketplace';

-- Active Facebook listings
\echo ''
\echo '✅ Active Facebook listings:'
SELECT COUNT(*) FROM car_listings WHERE source = 'Facebook Marketplace' AND is_active = TRUE;

-- Listings added in last 24 hours
\echo ''
\echo '🆕 Listings added in last 24 hours:'
SELECT COUNT(*) FROM car_listings 
WHERE source = 'Facebook Marketplace' 
AND created_at >= NOW() - INTERVAL '24 hours';

-- Listings added in last 7 days
\echo ''
\echo '📅 Listings added in last 7 days:'
SELECT COUNT(*) FROM car_listings 
WHERE source = 'Facebook Marketplace' 
AND created_at >= NOW() - INTERVAL '7 days';

-- Most recent additions
\echo ''
\echo '🔥 Most recent 10 Facebook additions:'
SELECT 
    TO_CHAR(created_at, 'YYYY-MM-DD HH24:MI') as added,
    year, make, model, price
FROM car_listings 
WHERE source = 'Facebook Marketplace'
ORDER BY created_at DESC
LIMIT 10;

-- Search for Hyundai Santa Fe 2003
\echo ''
\echo '========================================='
\echo '🔍 Searching for Hyundai Santa Fe 2003...'
SELECT 
    id, 
    is_active,
    price,
    url,
    TO_CHAR(created_at, 'YYYY-MM-DD HH24:MI') as created,
    TO_CHAR(scraped_at, 'YYYY-MM-DD HH24:MI') as last_scraped
FROM car_listings 
WHERE source = 'Facebook Marketplace'
AND make ILIKE '%hyundai%'
AND model ILIKE '%santa%'
AND year = 2003;

-- If not found, search for ANY Santa Fe
\echo ''
\echo '🔍 All Hyundai Santa Fe listings (any year):'
SELECT 
    year, make, model, is_active, price
FROM car_listings 
WHERE source = 'Facebook Marketplace'
AND make ILIKE '%hyundai%'
AND model ILIKE '%santa%'
ORDER BY year DESC;

-- Listings scraped in last 24 hours
\echo ''
\echo '========================================='
\echo '🔄 Listings scraped/updated in last 24 hours:'
SELECT COUNT(*) FROM car_listings 
WHERE source = 'Facebook Marketplace' 
AND scraped_at >= NOW() - INTERVAL '24 hours';

-- Check incomplete listings (missing year)
\echo ''
\echo '⚠️  Active listings with missing year (possible scraping issues):'
SELECT url
FROM car_listings 
WHERE source = 'Facebook Marketplace'
AND is_active = TRUE
AND year IS NULL
LIMIT 5;

EOF
