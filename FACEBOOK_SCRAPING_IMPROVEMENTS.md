# Facebook Scraping Improvements

## Changes Made

### 1. Increased Scraping Rate (3x faster)
- **Before**: 50 listings per hour
- **After**: 150 listings per hour
- **Impact**: Complete cycle through 5,164 URLs in ~33 hours (was 100+ hours)

### 2. Balanced URL Selection
- New `facebook_url_selector.py` module
- Distributes scraping evenly across different car makes
- Prevents always scraping from the start of the list
- Ensures less common makes (Hyundai, Mitsubishi, etc) get coverage

### 3. Skip Already-Scraped URLs
- Queries database before each batch
- Filters out 698 URLs already in database
- Focuses effort on the 4,466 unscraped URLs
- Reduces wasted API calls and processing time

## How to Check for Hyundai Santa Fe 2003 on Server

### Option 1: Using the Check Script (Easiest)
```bash
ssh root@95.217.163.52
cd ~/iceland-car-scraper
bash find_santa_fe.sh
```

This will:
- Check if URL exists in seed file
- Query database for any Hyundai Santa Fe
- Show all 2003 Hyundai models
- Give you manual search instructions

### Option 2: Manual Database Query
```bash
ssh root@95.217.163.52
docker exec -it $(docker ps -q -f name=db) psql -U postgres -d iceland_cars

# Then run this SQL:
SELECT 
    year, make, model, is_active, price, url,
    TO_CHAR(scraped_at, 'YYYY-MM-DD') as last_seen
FROM car_listings 
WHERE source = 'Facebook Marketplace'
AND make ILIKE '%hyundai%'
AND (model ILIKE '%santa%' OR year = 2003)
ORDER BY year DESC, scraped_at DESC;
```

### Option 3: Check Seed URLs File
```bash
ssh root@95.217.163.52
cd ~/iceland-car-scraper

# Count total URLs
grep -c "^https://" facebook_seed_links.txt

# Show most recent URLs
tail -20 facebook_seed_links.txt

# Note: URLs don't contain make/model in them
# They look like: https://www.facebook.com/marketplace/item/123456789/
```

### Option 4: Find the Listing Manually on Facebook
1. Go to Facebook Marketplace Iceland: https://www.facebook.com/marketplace/107355129303469/search/?query=hyundai%20santa%20fe&categoryID=807311116126722
2. Look for the 2003 model
3. Copy the URL (will be like: `https://www.facebook.com/marketplace/item/1234567890/`)
4. Check if it's in the seed file:
   ```bash
   ssh root@95.217.163.52
   grep "1234567890" ~/iceland-car-scraper/facebook_seed_links.txt
   ```

### Option 5: Force Add a Specific URL
If you find the listing URL and want to force it to be scraped:
```bash
ssh root@95.217.163.52
cd ~/iceland-car-scraper
echo 'https://www.facebook.com/marketplace/item/YOUR_ITEM_ID/' >> facebook_seed_links.txt
```

Then it will be picked up in the next hourly scrape.

## Current Status

From latest Supabase check:
- **698 total** Facebook listings in database
- **384 active** listings
- **44 scraped** in last 24 hours
- **223 scraped** in last 7 days
- **0 Hyundai Santa Fe 2003** found

Discovered URLs on server (from logs):
- **5,164 URLs** in seed file (last discovery run)
- **4,466 URLs** never scraped yet

## Expected Impact

With these changes:
1. **Faster discovery**: Will reach all 5,164 URLs in ~33 hours instead of 100+
2. **Better coverage**: Less common makes will be scraped proportionally
3. **No re-scraping**: 698 existing listings won't be visited again
4. **Find missing cars**: Hyundai Santa Fe 2003 should be found if it's in the discovered URLs

## Deployment

```bash
# Push changes
git push origin main

# Deploy to server
ssh root@95.217.163.52
cd ~/iceland-car-scraper
git pull origin main
cd deploy
docker-compose down
docker-compose up -d --build

# Monitor logs
docker-compose logs -f --tail=50 app
```

Look for log entries like:
```
Starting Facebook batch scrape (150 new listings from 5164 total, 698 already scraped)
```

## Monitoring Progress

Check progress after 24 hours:
```bash
python check_supabase_facebook.py
```

You should see:
- More listings added (was 44/day, should be ~150/day now)
- Better variety in makes/models
- Hopefully the Hyundai Santa Fe 2003!
