"""Async scheduler for recurring scraping and processing jobs.
Run: python scripts/scheduler.py
Jobs:
  - Daily scraping sequence starting at midnight (runs sequentially, each waits for previous):
    - 00:00: Start sequence
      1. Bilasölur (largest scraper)
      2. Bilaland
      3. Hekla
      4. Brimborg
      5. BR
      6. Íslandsbílar
      7. Facebook discovery
  - Facebook: Scrape 10 listings every 2 hours throughout the day
  - Maintenance (fixed times after scraping expected to complete):
    - 12:00 (check oldest listings - daily sample)
    - 13:00 (delete incomplete)
    - 14:00 (rebuild deals)
    - 16:00 (clean data)
    - 18:00 (train price models)
    - 20:00 (comprehensive check of ALL active listings - DAILY)
Environment:
  LOG_LEVEL, TZ, GOOGLE_API_KEY, DATABASE_URL
"""
import asyncio
import logging
import os
import sys
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Add project root to sys.path for script execution context
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("scheduler")

from scrapers.facebook_scraper import scrape_facebook
from scrapers.facebook_seed_links import discover_facebook_links
from scrapers.dealerships.bilaland_scraper import scrape_bilaland
from scrapers.dealerships.bilaland_seed_links import discover_bilaland_links
from scrapers.dealerships.bilasolur_scraper import scrape_bilasolur
from scrapers.dealerships.bilasolur_seed_links import discover_bilasolur_links
from scrapers.dealerships.islandsbilar_scraper import scrape_islandsbilar
from scrapers.dealerships.hekla_scraper import scrape_hekla
from scrapers.dealerships.hekla_seed_links import discover_hekla_links
from scrapers.dealerships.brimborg_scraper import scrape_brimborg
from scrapers.dealerships.brimborg_seed_links import discover_brimborg_links
from scrapers.dealerships.br_scraper import scrape_br
from scrapers.dealerships.br_seed_links import discover_br_links
from db.reference_price_updater import update_reference_prices
from deal_checker import check_for_deals

# New maintenance jobs
from cleaners.clean_data import run_all_cleaners as clean_data
from analysis.update_daily_deals import update_daily_deals
from analysis.train_price_models_3 import train_and_store as train_price_models
from check_oldest_listings import check_oldest_listings
from delete_incomplete_listings import delete_incomplete_listings
from check_all_active_listings import check_all_active_listings

# ---- Job definitions ----

# Facebook: Global seed URLs variable
facebook_seed_urls = []

async def job_sequential_scraping():
    """
    Run all scrapers sequentially starting at midnight.
    Each scraper waits for the previous one to complete.
    """
    log.info("="*70)
    log.info("Starting sequential daily scraping sequence")
    log.info("="*70)
    
    # 1. Bilasölur (largest, runs first)
    try:
        log.info("[1/7] Starting Bilasölur scrape")
        urls = await discover_bilasolur_links()
        log.info(f"Discovered {len(urls)} Bilasölur seed URLs")
        for idx, url in enumerate(urls, 1):
            log.info(f"Scraping Bilasölur URL {idx}/{len(urls)}")
            await scrape_bilasolur(max_scrolls=50, start_url=url)
        update_reference_prices()
        check_for_deals()
        log.info("✓ Bilasölur complete")
    except Exception as e:
        log.error(f"✗ Bilasölur failed: {e}", exc_info=True)
    
    # 2. Bilaland
    try:
        log.info("[2/7] Starting Bilaland scrape")
        urls = await discover_bilaland_links()
        log.info(f"Discovered {len(urls)} Bilaland seed URLs")
        for idx, url in enumerate(urls, 1):
            log.info(f"Scraping Bilaland URL {idx}/{len(urls)}")
            await scrape_bilaland(max_scrolls=10, start_url=url)
        update_reference_prices()
        check_for_deals()
        log.info("✓ Bilaland complete")
    except Exception as e:
        log.error(f"✗ Bilaland failed: {e}", exc_info=True)
    
    # 3. Hekla
    try:
        log.info("[3/7] Starting Hekla scrape")
        urls = await discover_hekla_links()
        log.info(f"Discovered {len(urls)} Hekla seed URLs")
        for idx, url in enumerate(urls, 1):
            log.info(f"Scraping Hekla URL {idx}/{len(urls)}")
            await scrape_hekla(max_pages=10, start_url=url)
        update_reference_prices()
        check_for_deals()
        log.info("✓ Hekla complete")
    except Exception as e:
        log.error(f"✗ Hekla failed: {e}", exc_info=True)
    
    # 4. Brimborg
    try:
        log.info("[4/7] Starting Brimborg scrape")
        urls = await discover_brimborg_links()
        log.info(f"Discovered {len(urls)} Brimborg seed URLs")
        for idx, url in enumerate(urls, 1):
            log.info(f"Scraping Brimborg URL {idx}/{len(urls)}")
            await scrape_brimborg(max_pages=10, start_url=url)
        update_reference_prices()
        check_for_deals()
        log.info("✓ Brimborg complete")
    except Exception as e:
        log.error(f"✗ Brimborg failed: {e}", exc_info=True)
    
    # 5. BR
    try:
        log.info("[5/7] Starting BR scrape")
        urls = await discover_br_links()
        log.info(f"Discovered {len(urls)} BR seed URLs")
        for idx, url in enumerate(urls, 1):
            log.info(f"Scraping BR URL {idx}/{len(urls)}")
            await scrape_br(max_scrolls=20, start_url=url)
        update_reference_prices()
        check_for_deals()
        log.info("✓ BR complete")
    except Exception as e:
        log.error(f"✗ BR failed: {e}", exc_info=True)
    
    # 6. Íslandsbílar
    try:
        log.info("[6/7] Starting Íslandsbílar scrape")
        await scrape_islandsbilar(max_pages=50)
        update_reference_prices()
        check_for_deals()
        log.info("✓ Íslandsbílar complete")
    except Exception as e:
        log.error(f"✗ Íslandsbílar failed: {e}", exc_info=True)
    
    # 7. Facebook URL discovery
    global facebook_seed_urls
    try:
        log.info("[7/7] Starting Facebook URL discovery")
        facebook_seed_urls = await discover_facebook_links(max_scrolls=50)
        log.info(f"✓ Facebook discovery complete: {len(facebook_seed_urls)} URLs")
    except Exception as e:
        log.error(f"✗ Facebook discovery failed: {e}", exc_info=True)
    
    log.info("="*70)
    log.info("Sequential scraping sequence complete")
    log.info("="*70)

async def job_facebook_scrape_batch():
    """
    Scrape Facebook listings from discovered URLs in batches.
    Runs hourly, processing 10 listings at a time.
    """
    global facebook_seed_urls
    if not facebook_seed_urls:
        log.warning("No Facebook seed URLs available. Skipping batch scrape.")
        return
    
    log.info(f"Starting Facebook batch scrape (10 listings from {len(facebook_seed_urls)} total)")
    await scrape_facebook(max_items=10, start_urls=facebook_seed_urls)
    update_reference_prices()
    check_for_deals()
    log.info("Finished Facebook batch scrape")

# ---- Maintenance job wrappers ----
async def job_check_oldest_listings():
    log.info("Starting check of oldest active listings")
    await check_oldest_listings(limit_per_source=100)
    log.info("Finished checking oldest active listings")

async def job_check_all_active_listings():
    """Comprehensive check of ALL active listings (runs weekly)."""
    log.info("Starting comprehensive check of all active listings")
    await check_all_active_listings(limit_per_source=None, batch_size=50)
    log.info("Finished comprehensive check of all active listings")

async def job_delete_incomplete_listings():
    log.info("Starting deletion of incomplete inactive listings")
    await delete_incomplete_listings(batch_size=100)
    log.info("Finished deleting incomplete inactive listings")

async def job_clean_data():
    log.info("Starting daily data cleaning")
    await asyncio.to_thread(clean_data)
    log.info("Finished daily data cleaning")

async def job_rebuild_daily_deals():
    log.info("Starting rebuild of daily deals")
    await asyncio.to_thread(update_daily_deals)
    log.info("Finished rebuild of daily deals")

async def job_train_price_models():
    log.info("Starting training of price prediction models")
    await asyncio.to_thread(train_price_models)
    log.info("Finished training of price prediction models")

# ---- Main scheduler orchestration ----
def main():
    tz = os.getenv("TZ", "UTC")
    sched = AsyncIOScheduler(timezone=tz)

    # ---- Daily sequential scraping (starts at midnight) ----
    # All scrapers run in sequence: Bilasolur → Bilaland → Hekla → Brimborg → BR → Islandsbilar → Facebook Discovery
    sched.add_job(job_sequential_scraping, CronTrigger(hour=0, minute=0), id="sequential_scraping")
    
    # ---- Facebook batch scraping (hourly throughout the day) ----
    # Scrapes 10 listings per hour from discovered URLs
    sched.add_job(job_facebook_scrape_batch, CronTrigger(hour="*/2", minute=15), id="facebook_batch")  # Every 2 hours at :15

    # ---- Daily maintenance jobs (afternoon/evening when scraping is done) ----
    sched.add_job(job_check_oldest_listings,
                  CronTrigger(hour=12, minute=0),
                  id="check_oldest")
    sched.add_job(job_delete_incomplete_listings,
                  CronTrigger(hour=13, minute=0),
                  id="delete_incomplete")
    sched.add_job(job_rebuild_daily_deals,
                  CronTrigger(hour=14, minute=0),
                  id="rebuild_deals")
    sched.add_job(job_clean_data,
                  CronTrigger(hour=16, minute=0),
                  id="clean_data")
    sched.add_job(job_train_price_models,
                  CronTrigger(hour=18, minute=0),
                  id="train_price_models")
    
    # ---- Comprehensive active listings check (daily at 20:00, after scraping and training) ----
    sched.add_job(job_check_all_active_listings,
                  CronTrigger(hour=20, minute=0),
                  id="check_all_active_daily")

    # ---- Runner ----
    async def runner():
        sched.start()
        log.info("Scheduler started (timezone=%s)", tz)
        try:
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, SystemExit):
            log.info("Scheduler shutting down...")
            sched.shutdown(wait=False)

    asyncio.run(runner())


if __name__ == "__main__":
    main()
