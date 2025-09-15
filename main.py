import asyncio
from scrapers.dealerships.bilasolur_scraper import scrape_bilasolur
from scrapers.dealerships.bilaland_scraper import scrape_bilaland
from scrapers.facebook_scraper import scrape_facebook
from db.reference_price_updater import update_reference_prices
from deal_checker import check_for_deals
from analysis.train_price_models import train_and_store
from scrapers.dealerships.bilasolur_seed_links import discover_bilasolur_links
from cleaners.clean_data import run_all_cleaners
from analysis.update_daily_deals import update_daily_deals

if __name__ == "__main__":
    print("Choose an option:")
    print("1 - Scrape Facebook Marketplace for deals")
    print("2 - Scrape Bilasolur & update reference prices")
    print("3 - Scrape Bilaland & update reference prices")
    print("4 - Update reference prices only")
    print("5 - View recent logged deals")
    print("6 - Run all dealership scrapers")
    print("7 - Train price prediction models")
    print("8 - Discover Bilasolur category URLs and scrape")
    print("9 - Clean data (remove non-cars, dead URLs, duplicates)")
    print("10 - Rebuild daily deals (Top 10)")
    choice = input("Enter choice: ").strip()

    if choice == "1":
        print("Starting Facebook Marketplace scrape...")
        asyncio.run(scrape_facebook(max_items=5))
        check_for_deals()
        print("Scrape finished.")
    elif choice == "2":
        print("Starting Bilasolur scrape...")
        asyncio.run(scrape_bilasolur(max_pages=1))
        update_reference_prices()
        print("Scrape & reference update finished.")
    elif choice == "3":
        print("Starting Bilaland scrape...")
        asyncio.run(scrape_bilaland(max_scrolls=4))
        update_reference_prices()
        print("Scrape & reference update finished.")
    elif choice == "4":
        update_reference_prices()
        print("Reference prices refreshed.")
    elif choice == "5":
        view_recent_deals()
    elif choice == "6":
        print("All Dealership Scrapers have been started.")
        print("Starting Bilasolur scrape...")
        asyncio.run(scrape_bilasolur(max_pages=1000))
        print("Starting Bilaland scrape...")
        asyncio.run(scrape_bilaland(max_scrolls=500))
        print("Updating reference prices...")
        update_reference_prices()
    elif choice == "7":
        print("Training price prediction models...")
        updated, skipped = train_and_store()
        print(f"Models trained and stored. Updated: {updated}, Skipped: {skipped}")
    elif choice == "8":
        print("Discovering Bilasolur category URLs...")
        urls = asyncio.run(discover_bilasolur_links())
        print(f"Discovered {len(urls)} URLs. Starting scrape...")
        asyncio.run(scrape_bilasolur(start_urls=urls, max_pages=500))
    elif choice == "9":
        print("Running cleaners (this may open headless browsers)…")
        run_all_cleaners()
        print("Cleaners finished.")
    elif choice == "10":
        print("Updating daily deals...")
        update_daily_deals()
    else:
        print("Invalid choice.")
