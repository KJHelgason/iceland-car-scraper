"""Async scheduler for recurring scraping and processing jobs.
Run: python scripts/scheduler.py
Jobs:
  - Bilaland cycle every 30 minutes
  - Bilasölur cycle at minute 15 and 45 each hour
  - Facebook cycle hourly at minute 5
  - Bilasölur discovery daily at 02:30 UTC
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

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("scheduler")

from scrapers.facebook_scraper import scrape_facebook
from scrapers.dealerships.bilaland_scraper import scrape_bilaland
from scrapers.dealerships.bilasolur_scraper import scrape_bilasolur
from scrapers.dealerships.bilasolur_seed_links import discover_bilasolur_links
from db.reference_price_updater import update_reference_prices
from deal_checker import check_for_deals

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

# ---- Main scheduler orchestration ----
def main():
    tz = os.getenv("TZ", "UTC")
    sched = AsyncIOScheduler(timezone=tz)
    # Stagger dealership jobs
    sched.add_job(lambda: asyncio.create_task(job_bilaland_cycle()), CronTrigger(minute="*/30"), id="bilaland")
    sched.add_job(lambda: asyncio.create_task(job_bilasolur_cycle()), CronTrigger(minute="15,45"), id="bilasolar")
    # Hourly Facebook
    sched.add_job(lambda: asyncio.create_task(job_fb_cycle()), CronTrigger(minute=5), id="facebook")
    # Daily discovery
    sched.add_job(lambda: asyncio.create_task(job_bilasolur_discover_and_scrape()), CronTrigger(hour=2, minute=30), id="bilasolar_discover")

    sched.start()
    log.info("Scheduler started (timezone=%s)", tz)
    try:
        asyncio.get_event_loop().run_forever()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler shutting down...")
        sched.shutdown(wait=False)

if __name__ == "__main__":
    main()
