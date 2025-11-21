#!/bin/bash
# Quick check of Facebook stats on server

echo "🔍 Facebook Marketplace Stats"
echo "=============================="

# Use docker exec to query the database
docker exec $(docker ps -q -f name=db) psql -U postgres -d iceland_cars -t -c "
SELECT 
    'Total FB listings: ' || COUNT(*)::text
FROM car_listings 
WHERE source = 'Facebook Marketplace';

SELECT 
    'Active FB listings: ' || COUNT(*)::text
FROM car_listings 
WHERE source = 'Facebook Marketplace' AND is_active = TRUE;

SELECT 
    'Added last 24h: ' || COUNT(*)::text
FROM car_listings 
WHERE source = 'Facebook Marketplace' 
AND created_at >= NOW() - INTERVAL '24 hours';

SELECT 
    'Added last 7 days: ' || COUNT(*)::text
FROM car_listings 
WHERE source = 'Facebook Marketplace' 
AND created_at >= NOW() - INTERVAL '7 days';

SELECT 
    'Scraped last 24h: ' || COUNT(*)::text
FROM car_listings 
WHERE source = 'Facebook Marketplace' 
AND scraped_at >= NOW() - INTERVAL '24 hours';
"

echo ""
echo "🚗 Searching for Hyundai Santa Fe 2003..."
docker exec $(docker ps -q -f name=db) psql -U postgres -d iceland_cars -t -c "
SELECT COUNT(*) || ' found'
FROM car_listings 
WHERE source = 'Facebook Marketplace'
AND make ILIKE '%hyundai%'
AND model ILIKE '%santa%'
AND year = 2003;
"

echo ""
echo "📋 All Hyundai Santa Fe (any year):"
docker exec $(docker ps -q -f name=db) psql -U postgres -d iceland_cars -c "
SELECT year, is_active, price, url
FROM car_listings 
WHERE source = 'Facebook Marketplace'
AND make ILIKE '%hyundai%'
AND model ILIKE '%santa%'
ORDER BY year DESC;
"
