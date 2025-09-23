"""Command-line interface for running scraping, updating reference prices, and deal checks.
Usage examples:
  python scripts/cli.py scrape-fb --max-items 5
  python scripts/cli.py scrape-bilaland
  python scripts/cli.py update-refs
"""
import os
import sys
import asyncio
import typer

# Ensure project root (parent of this scripts directory) is on sys.path when executed directly
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Import application functions
from scrapers.facebook_scraper import scrape_facebook  # async
from scrapers.dealerships.bilaland_scraper import scrape_bilaland  # async
from scrapers.dealerships.bilasolur_scraper import scrape_bilasolur  # async
from scrapers.dealerships.bilasolur_seed_links import discover_bilasolur_links  # async
from db.reference_price_updater import update_reference_prices
from deal_checker import check_for_deals
from normalize_existing_data import normalize_all
from cleaners.clean_data import run_all_cleaners as clean_data
from analysis.update_daily_deals import update_daily_deals
from analysis.train_price_models_3 import train_and_store as train_price_models

app = typer.Typer(help="Car scraper automation CLI")

@app.command("scrape-fb")
def cmd_scrape_fb(max_items: int = typer.Option(10, help="Max listings to visit")):
    """Scrape Facebook Marketplace (requires valid fb_state.json)."""
    asyncio.run(scrape_facebook(max_items=max_items))

@app.command("scrape-bilaland")
def cmd_scrape_bilaland(max_scrolls: int = typer.Option(5, help="Number of scroll iterations")):
    """Scrape Bilaland listings."""
    asyncio.run(scrape_bilaland(max_scrolls=max_scrolls))

@app.command("scrape-bilasolur")
def cmd_scrape_bilasolur(max_pages: int = typer.Option(100, help="Max pages to traverse")):
    """Scrape Bilasölur listings."""
    asyncio.run(scrape_bilasolur(max_pages=max_pages))

@app.command("scrape-bilasolur-discover")
def cmd_scrape_bilasolur_discover(max_pages: int = typer.Option(500, help="Max pages after discovery")):
    """Discover Bilasölur listing URLs, then scrape them."""
    urls = asyncio.run(discover_bilasolur_links())
    typer.echo(f"Discovered {len(urls)} seed URLs")
    asyncio.run(scrape_bilasolur(start_urls=urls, max_pages=max_pages))

@app.command("clean-data")
def cmd_clean_data():
    """Run the daily data cleaning process."""
    clean_data()

@app.command("rebuild-deals")
def cmd_rebuild_daily_deals():
    """Rebuild the daily deals table."""
    update_daily_deals()

@app.command("train-models")
def cmd_train_price_models():
    """Train price prediction models."""
    train_price_models()

@app.command("update-refs")
def cmd_update_refs():
    """Recalculate reference prices for all models."""
    update_reference_prices()

@app.command("check-deals")
def cmd_check_deals():
    """Check for deals vs reference prices."""
    check_for_deals()

@app.command("normalize-existing")
def cmd_normalize_existing(
    dry_run: bool = typer.Option(False, help="Do not persist changes"),
    limit: int = typer.Option(None, help="Limit number of rows processed"),
    batch_size: int = typer.Option(200, help="Rows per commit"),
):
    """Normalize existing DB records for make/model/title."""
    normalize_all(dry_run=dry_run, limit=limit, batch_size=batch_size)

if __name__ == "__main__":
    app()
