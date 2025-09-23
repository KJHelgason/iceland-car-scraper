"""Async scheduler for recurring scraping and processing jobs.
Run: python scripts/scheduler.py
Jobs:
  - Bilaland cycle every 6 hours
  - Bilasölur cycle every 6 hours
  - Facebook cycle every 3 hours
  - Bilasölur discovery daily at 02:30 UTC
  - Clean data daily at 02:00 UTC
  - Rebuild daily deals daily at 03:00 UTC
  - Train price prediction models daily at 04:00 UTC
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
from scrapers.dealerships.bilaland_scraper import scrape_bilaland
from scrapers.dealerships.bilasolur_scraper import scrape_bilasolur
from scrapers.dealerships.bilasolur_seed_links import discover_bilasolur_links
from db.reference_price_updater import update_reference_prices
from deal_checker import check_for_deals

# New maintenance jobs
from cleaners.clean_data import run_all_cleaners as clean_data
from analysis.update_daily_deals import update_daily_deals
from analysis.train_price_models_3 import train_and_store as train_price_models

# ---- Job definitions ----
async def job_bilaland_cycle():
    log.info("Starting Bilaland cycle")
    await scrape_bilaland(max_scrolls=5)
    update_reference_prices()
    check_for_deals()
    log.info("Finished Bilaland cycle")

async def job_bilasolur_cycle():
    log.info("Starting Bilasölur cycle")
    await scrape_bilasolur(max_pages=100)
    update_reference_prices()
    check_for_deals()
    log.info("Finished Bilasölur cycle")

async def job_fb_cycle():
    log.info("Starting Facebook cycle")
    await scrape_facebook(max_items=10)
    update_reference_prices()
    check_for_deals()
    log.info("Finished Facebook cycle")

async def job_bilasolur_discover_and_scrape():
    log.info("Starting Bilasölur discovery")
    urls = await discover_bilasolur_links()
    log.info("Discovered %d seed URLs", len(urls))
    await scrape_bilasolur(start_urls=urls, max_pages=500)
    log.info("Finished Bilasölur discovery+scrape")

# ---- Maintenance job wrappers ----
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

    # ---- Register jobs with staggered minutes ----
    sched.add_job(job_bilaland_cycle, CronTrigger(hour="*/6", minute=0), id="bilaland")           # every 6h at :00
    sched.add_job(job_bilasolur_cycle, CronTrigger(hour="*/6", minute=5), id="bilasolar")        # every 6h at :05
    sched.add_job(job_fb_cycle, CronTrigger(hour="*/3", minute=10), id="facebook")               # every 3h at :10

    # Daily jobs (already staggered by hour)
    sched.add_job(job_bilasolur_discover_and_scrape,
                  CronTrigger(hour=2, minute=30),
                  id="bilasolar_discover")
    sched.add_job(job_rebuild_daily_deals,
                  CronTrigger(hour=3, minute=0),
                  id="rebuild_deals")
    sched.add_job(job_clean_data,
                  CronTrigger(hour=4, minute=0),
                  id="clean_data")
    sched.add_job(job_train_price_models,
                  CronTrigger(hour=5, minute=0),
                  id="train_price_models")

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
