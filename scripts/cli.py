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
from scrapers.facebook_seed_links import discover_facebook_links  # async
from scrapers.dealerships.bilaland_scraper import scrape_bilaland  # async
from scrapers.dealerships.bilasolur_scraper import scrape_bilasolur  # async
from scrapers.dealerships.islandsbilar_scraper import scrape_islandsbilar  # async
from scrapers.dealerships.hekla_scraper import scrape_hekla  # async
from scrapers.dealerships.brimborg_scraper import scrape_brimborg  # async
from scrapers.dealerships.br_scraper import scrape_br  # async
from scrapers.dealerships.bilasolur_seed_links import discover_bilasolur_links  # async
from scrapers.dealerships.bilaland_seed_links import discover_bilaland_links  # async
from scrapers.dealerships.hekla_seed_links import discover_hekla_links  # async
from scrapers.dealerships.brimborg_seed_links import discover_brimborg_links  # async
from scrapers.dealerships.br_seed_links import discover_br_links  # async
from db.reference_price_updater import update_reference_prices
from deal_checker import check_for_deals
from normalize_existing_data import normalize_all
from cleaners.clean_data import run_all_cleaners as clean_data
from analysis.update_daily_deals import update_daily_deals
from analysis.train_price_models_3 import train_and_store as train_price_models
from check_oldest_listings import check_oldest_listings
from delete_incomplete_listings import delete_incomplete_listings

app = typer.Typer(help="Car scraper automation CLI")

@app.command("scrape-fb")
def cmd_scrape_fb(max_items: int = typer.Option(10, help="Max listings to visit")):
    """Scrape Facebook Marketplace (requires valid fb_state.json)."""
    asyncio.run(scrape_facebook(max_items=max_items))

@app.command("scrape-fb-discover")
def cmd_scrape_fb_discover(
    max_scrolls: int = typer.Option(50, help="Scroll iterations to discover URLs"),
    max_items: int = typer.Option(None, help="Max listings to scrape (optional)")
):
    """Discover Facebook Marketplace listing URLs, then scrape them."""
    urls = asyncio.run(discover_facebook_links(max_scrolls=max_scrolls))
    typer.echo(f"Discovered {len(urls)} seed URLs")
    
    if urls:
        items_to_scrape = max_items if max_items else len(urls)
        typer.echo(f"Scraping {min(items_to_scrape, len(urls))} listings...")
        asyncio.run(scrape_facebook(max_items=items_to_scrape, start_urls=urls))

@app.command("scrape-bilaland")
def cmd_scrape_bilaland(max_scrolls: int = typer.Option(5, help="Number of scroll iterations")):
    """Scrape Bilaland listings."""
    asyncio.run(scrape_bilaland(max_scrolls=max_scrolls))

@app.command("scrape-bilaland-discover")
def cmd_scrape_bilaland_discover(max_scrolls: int = typer.Option(10, help="Scroll iterations per discovered URL")):
    """Discover Bilaland listing URLs by make, then scrape each one."""
    urls = asyncio.run(discover_bilaland_links())
    typer.echo(f"Discovered {len(urls)} seed URLs")
    
    for idx, url in enumerate(urls, 1):
        typer.echo(f"[{idx}/{len(urls)}] Scraping {url}")
        asyncio.run(scrape_bilaland(max_scrolls=max_scrolls, start_url=url))

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

@app.command("scrape-islandsbilar")
def cmd_scrape_islandsbilar(max_pages: int = typer.Option(20, help="Max pages to scrape")):
    """Scrape Íslandsbílar listings."""
    asyncio.run(scrape_islandsbilar(max_pages=max_pages))

@app.command("scrape-hekla")
def cmd_scrape_hekla(max_pages: int = typer.Option(20, help="Max pages to scrape")):
    """Scrape Hekla used car listings."""
    asyncio.run(scrape_hekla(max_pages=max_pages))

@app.command("scrape-hekla-discover")
def cmd_scrape_hekla_discover(max_pages: int = typer.Option(100, help="Max pages per discovered URL")):
    """Discover Hekla listing URLs by make, then scrape each one."""
    urls = asyncio.run(discover_hekla_links())
    typer.echo(f"Discovered {len(urls)} seed URLs")
    
    for idx, url in enumerate(urls, 1):
        typer.echo(f"[{idx}/{len(urls)}] Scraping {url}")
        asyncio.run(scrape_hekla(max_pages=max_pages, start_url=url))

@app.command("scrape-brimborg")
def cmd_scrape_brimborg(max_pages: int = typer.Option(20, help="Max pages to scrape")):
    """Scrape Brimborg used car listings."""
    asyncio.run(scrape_brimborg(max_pages=max_pages))

@app.command("scrape-brimborg-discover")
def cmd_scrape_brimborg_discover(max_pages: int = typer.Option(100, help="Max pages per discovered URL")):
    """Discover Brimborg listing URLs by make, then scrape each one."""
    urls = asyncio.run(discover_brimborg_links())
    typer.echo(f"Discovered {len(urls)} seed URLs")
    
    for idx, url in enumerate(urls, 1):
        typer.echo(f"[{idx}/{len(urls)}] Scraping {url}")
        asyncio.run(scrape_brimborg(max_pages=max_pages, start_url=url))

@app.command("scrape-br")
def cmd_scrape_br(max_scrolls: int = typer.Option(20, help="Max scrolls to load listings")):
    """Scrape BR (br.is) used car listings."""
    asyncio.run(scrape_br(max_scrolls=max_scrolls))

@app.command("scrape-br-discover")
def cmd_scrape_br_discover(max_scrolls: int = typer.Option(20, help="Max scrolls per discovered URL")):
    """Discover BR listing URLs by make, then scrape each one."""
    urls = asyncio.run(discover_br_links())
    typer.echo(f"Discovered {len(urls)} seed URLs")
    
    for idx, url in enumerate(urls, 1):
        typer.echo(f"[{idx}/{len(urls)}] Scraping {url}")
        asyncio.run(scrape_br(max_scrolls=max_scrolls, start_url=url))

@app.command("clean-data")
def cmd_clean_data():
    """Run the daily data cleaning process."""
    clean_data()

@app.command("check-oldest")
def cmd_check_oldest(limit_per_source: int = typer.Option(100, help="Listings to check per source")):
    """Check oldest active listings to mark inactive ones."""
    asyncio.run(check_oldest_listings(limit_per_source=limit_per_source))

@app.command("delete-incomplete")
def cmd_delete_incomplete(batch_size: int = typer.Option(100, help="Batch size for commits")):
    """Delete incomplete inactive listings."""
    asyncio.run(delete_incomplete_listings(batch_size=batch_size))

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
