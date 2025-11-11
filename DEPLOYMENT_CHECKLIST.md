# 🚀 Facebook Improvements - Deployment Checklist

## ✅ Pre-Deployment Verification

All changes tested and ready for production deployment.

### Changes Summary:
1. ✅ Batch size: 10 → 50 listings/hour
2. ✅ Frequency: Every 2 hours → Every 1 hour
3. ✅ Discovery: Once daily → Every 6 hours
4. ✅ Search URLs: 8 → 50 (48 car makes)
5. ✅ Parts filtering: Two-layer system (pre-filter + AI)
6. ✅ AI validation: JSON mode + data validation
7. ✅ check_all_active_listings: Only checks listings >7 days old

### Expected Impact:
- **Volume:** 120 → 1,200+ listings/day (10x increase)
- **Quality:** Parts/accessories filtered out (20-30% reduction in junk)
- **Coverage:** 48 car makes, all major brands in Iceland
- **Speed:** check_all_active reduced from 2+ hours to <30 minutes

---

## 📋 Deployment Steps

### 1. Commit Changes
```powershell
git add .
git commit -m "Facebook improvements: 10x volume, 48 makes, parts filtering, AI validation"
git push origin main
```

### 2. Deploy to Hetzner
```bash
# SSH to server
ssh kjartan@bila-scraper

# Pull latest changes
cd ~/iceland-car-scraper
git stash  # If local changes exist
git pull origin main
git stash pop  # Restore local changes (docker-compose.yml)

# Rebuild and restart
cd deploy
docker-compose down
docker-compose up -d --build

# Verify container is running
docker-compose ps
```

### 3. Verify Jobs Registered
```bash
# Check logs for job registration
docker-compose logs app | grep -E "facebook|sequential|check_all"
```

**Should see:**
- ✅ `sequential_scraping` (00:00 daily)
- ✅ `facebook_discovery` (every 6 hours at :00) **← NEW**
- ✅ `facebook_batch` (every 1 hour at :15) **← UPDATED**
- ✅ `check_all_active_daily` (20:00 daily) **← FASTER**

### 4. Monitor First Runs

**First Discovery Run (next :00 hour):**
```bash
docker-compose logs -f app | grep -A 10 "Facebook URL discovery"
```
- Should discover 200-1000+ URLs from 50 search URLs
- Takes 10-30 minutes depending on scrolling

**First Batch Scrape (next :15 hour):**
```bash
docker-compose logs -f app | grep -A 50 "Facebook batch scrape"
```
- Should process 50 listings
- Watch for: "⚠️ SKIPPING: Likely a part/accessory"
- Watch for: "🚫 AI CLASSIFIED AS NON-VEHICLE"

**First Active Listings Check (20:00):**
```bash
docker-compose logs -f app | grep -A 20 "check_all_active"
```
- Should only check listings >7 days old
- Much faster than before (was checking all 7k+ listings)

---

## 🔍 Health Checks (Next 24 Hours)

### After 6 Hours:
- [ ] Discovery ran successfully (look for "Facebook discovery complete: X URLs")
- [ ] Batch scrapes running hourly (look for "Starting Facebook batch scrape")
- [ ] Parts being filtered (look for "SKIPPING" or "NON-VEHICLE" messages)

### After 24 Hours:
- [ ] Query database: How many new Facebook listings?
  ```sql
  SELECT COUNT(*) FROM car_listings 
  WHERE source = 'Facebook Marketplace' 
  AND scraped_at > NOW() - INTERVAL '24 hours';
  ```
  **Expected:** 800-1,200 new/updated listings

- [ ] Check error rate:
  ```bash
  docker-compose logs app | grep -i "error" | wc -l
  ```
  **Should be:** <50 errors in 24 hours

- [ ] Check AI extraction quality:
  ```sql
  SELECT COUNT(*) FROM car_listings 
  WHERE source = 'Facebook Marketplace' 
  AND make IS NOT NULL 
  AND model IS NOT NULL 
  AND year IS NOT NULL
  AND scraped_at > NOW() - INTERVAL '24 hours';
  ```
  **Expected:** >80% of new listings have complete data

---

## 🚨 Troubleshooting

### Issue: No URLs discovered
**Symptoms:** "No Facebook seed URLs available"
**Fix:** Check fb_state.json cookies are valid
```bash
# Re-run save_fb_cookies.py if needed
python save_fb_cookies.py
```

### Issue: AI extraction failing
**Symptoms:** Many "OpenAI extraction failed" errors
**Fix:** Verify OPENAI_API_KEY in .env
```bash
cat ~/.env | grep OPENAI_API_KEY
```

### Issue: Too many parts getting through
**Symptoms:** Database has listings for "rims", "tires", etc.
**Solution:** Add more keywords to `is_likely_vehicle()` in facebook_scraper.py

### Issue: Facebook rate limiting
**Symptoms:** "429 Too Many Requests" or blocked
**Solution:** Reduce frequency temporarily:
- Change discovery from every 6 hours → every 12 hours
- Change batch from every 1 hour → every 2 hours

---

## 📊 Success Metrics (Week 1)

Target metrics for first week:

- [ ] **Volume:** 7,000+ Facebook listings collected (1,000/day × 7 days)
- [ ] **Quality:** <10% parts/accessories in database
- [ ] **Extraction:** >75% listings have make/model/year
- [ ] **Active Check:** Completes in <1 hour (was 2+ hours)
- [ ] **Errors:** <5% error rate on scraping
- [ ] **Coverage:** All 48 makes represented in database

---

## 📝 Files Modified

1. `scripts/scheduler.py` - Batch size, frequency, discovery job
2. `scrapers/facebook_seed_links.py` - 50 search URLs (48 makes)
3. `scrapers/facebook_scraper.py` - Parts filtering, AI validation
4. `check_all_active_listings.py` - 7-day filter
5. `FACEBOOK_IMPROVEMENTS.md` - Documentation
6. `test_facebook_improvements.py` - Testing script

---

## ✅ Ready for Deployment

All changes tested locally with positive results. Deploy at your convenience!

**Deployment Time:** 5-10 minutes
**Risk Level:** Low (all changes backwards compatible)
**Rollback Plan:** `git revert` and rebuild container

---

Generated: November 11, 2025
