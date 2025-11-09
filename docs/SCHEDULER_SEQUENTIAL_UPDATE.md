# Scheduler Sequential Execution Update

## Overview
Updated the scheduler from fixed cron times to sequential execution, where each scraper waits for the previous one to complete before starting.

## Changes Made

### Before (Fixed Cron Schedule)
```
00:00 - Bilasölur starts (may run 2+ hours)
02:00 - Bilaland starts (regardless if Bilasölur finished)
04:00 - Hekla starts
06:00 - Brimborg starts
08:00 - BR starts
10:00 - Íslandsbílar starts
22:00 - Facebook discovery starts
```

**Problem**: If a scraper takes longer than expected, the next one starts anyway, causing:
- Resource competition (browser instances, CPU, memory)
- Database connection conflicts
- Incomplete scraping if timeout occurs

### After (Sequential Execution)
```
00:00 - Sequential scraping starts:
  1. Bilasölur → waits for completion
  2. Bilaland → waits for completion  
  3. Hekla → waits for completion
  4. Brimborg → waits for completion
  5. BR → waits for completion
  6. Íslandsbílar → waits for completion
  7. Facebook discovery → waits for completion
  
02:15, 04:15, 06:15... - Facebook batch scraping (10 listings/hour)
12:00 - Check oldest listings
13:00 - Delete incomplete listings
14:00 - Rebuild deals
16:00 - Clean data
18:00 - Train price models
20:00 - Comprehensive active listings check
```

**Benefits**:
- No resource conflicts
- Each scraper gets full system resources
- Guaranteed completion before next starts
- More reliable and predictable

## Implementation Details

### New Function: `job_sequential_scraping()`
```python
async def job_sequential_scraping():
    """
    Run all scrapers sequentially starting at midnight.
    Each scraper waits for the previous one to complete.
    """
    # 1. Bilasölur (largest, runs first)
    try:
        log.info("[1/7] Starting Bilasölur scrape")
        urls = await discover_bilasolur_links()
        for idx, url in enumerate(urls, 1):
            await scrape_bilasolur(max_scrolls=50, start_url=url)
        update_reference_prices()
        check_for_deals()
    except Exception as e:
        log.error(f"✗ Bilasölur failed: {e}", exc_info=True)
    
    # 2-7: Bilaland, Hekla, Brimborg, BR, Íslandsbílar, Facebook
    # Each with try/except to continue on error
```

### Removed Functions
- `job_facebook_discover()` - Now part of sequential scraping
- `job_bilasolur_daily()` - Replaced by sequential scraping
- `job_bilaland_daily()` - Replaced by sequential scraping
- `job_hekla_daily()` - Replaced by sequential scraping
- `job_brimborg_daily()` - Replaced by sequential scraping
- `job_br_daily()` - Replaced by sequential scraping
- `job_islandsbilar_daily()` - Replaced by sequential scraping

### Kept Functions
- `job_facebook_scrape_batch()` - Hourly processing of discovered URLs
- All maintenance jobs (check oldest, delete incomplete, clean data, etc.)

### Scheduler Registration
```python
# Single job at midnight for all scrapers
sched.add_job(job_sequential_scraping, CronTrigger(hour=0, minute=0), id="sequential_scraping")

# Facebook batch scraping every 2 hours
sched.add_job(job_facebook_scrape_batch, CronTrigger(hour="*/2", minute=15), id="facebook_batch")

# Maintenance jobs at fixed times (unchanged)
```

## Error Handling

Each scraper in the sequence has try/except:
- If one fails, logs error and continues to next
- Ensures one broken scraper doesn't stop entire sequence
- Example: If Bilasölur crashes, Bilaland still runs

## Expected Timeline

Assuming typical scraping durations:
```
00:00 - Sequential starts
00:00-02:00 - Bilasölur (largest, ~2 hours)
02:00-02:30 - Bilaland (~30 min)
02:30-03:00 - Hekla (~30 min)
03:00-03:30 - Brimborg (~30 min)
03:30-04:00 - BR (~30 min)
04:00-04:30 - Íslandsbílar (~30 min)
04:30-05:00 - Facebook discovery (~30 min)
05:00 - Sequential scraping complete
```

All maintenance jobs (12:00-20:00) run well after scraping completes.

## Testing

To test sequential execution:
```bash
# Test with dry run or limited items
python -c "
import asyncio
from scripts.scheduler import job_sequential_scraping
asyncio.run(job_sequential_scraping())
"
```

## Deployment Notes

1. **Update on Hetzner server**:
   ```bash
   git pull origin main
   # Restart scheduler service/docker container
   ```

2. **Monitor first run**:
   - Check logs for sequential execution
   - Verify each scraper completes before next starts
   - Confirm total runtime is acceptable

3. **Adjust if needed**:
   - If total runtime too long, consider reducing `max_scrolls` or `max_pages`
   - If scrapers finish too quickly, can increase limits

## Related Files
- `scripts/scheduler.py` - Main scheduler implementation
- `check_all_active_listings.py` - Comprehensive listing checker (runs at 20:00)
- All scraper files in `scrapers/` and `scrapers/dealerships/`
