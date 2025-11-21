#!/bin/bash
# Check if Hyundai Santa Fe 2003 is in the Facebook seed URLs on the server

echo "🔍 Checking for Hyundai Santa Fe 2003 in seed URLs..."
echo "======================================================"

# Check if the seed file exists
if [ ! -f "facebook_seed_links.txt" ]; then
    echo "❌ facebook_seed_links.txt not found!"
    exit 1
fi

# Count total URLs
TOTAL=$(grep -c "^https://" facebook_seed_links.txt)
echo "📊 Total URLs in seed file: $TOTAL"

# Search for any hyundai URLs
echo ""
echo "🚗 Searching for Hyundai URLs..."
HYUNDAI_URLS=$(grep -i "hyundai" facebook_seed_links.txt || echo "")

if [ -z "$HYUNDAI_URLS" ]; then
    echo "⚠️  Note: Seed URLs don't contain car make/model in the URL itself"
    echo "   URLs are like: https://www.facebook.com/marketplace/item/123456/"
    echo ""
    echo "💡 We need to check the database to see which URLs have been scraped as Hyundai Santa Fe"
    echo ""
    echo "Running database query..."
    
    docker exec $(docker ps -q -f name=db) psql -U postgres -d iceland_cars -c "
    SELECT 
        url,
        year, make, model,
        is_active,
        TO_CHAR(scraped_at, 'YYYY-MM-DD HH24:MI') as last_scraped
    FROM car_listings 
    WHERE source = 'Facebook Marketplace'
    AND make ILIKE '%hyundai%'
    AND (model ILIKE '%santa%' OR year = 2003)
    ORDER BY year DESC, scraped_at DESC;
    "
else
    echo "Found Hyundai URLs:"
    echo "$HYUNDAI_URLS"
fi

# Show sample of recent URLs from seed file
echo ""
echo "📋 Sample of most recent URLs in seed file (last 10):"
tail -n 10 facebook_seed_links.txt

echo ""
echo "💡 To search Facebook Marketplace manually for the listing:"
echo "   1. Go to: https://www.facebook.com/marketplace/107355129303469/search/?query=hyundai%20santa%20fe&categoryID=807311116126722"
echo "   2. Look for 2003 model"
echo "   3. Check if the URL is in facebook_seed_links.txt"
echo ""
echo "🔧 To force discovery of specific URL:"
echo "   echo 'https://www.facebook.com/marketplace/item/YOUR_ITEM_ID/' >> facebook_seed_links.txt"
