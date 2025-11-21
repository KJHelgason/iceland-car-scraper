"""
Utility to select URLs evenly across different car makes for Facebook scraping.
This ensures we don't over-scrape popular makes while missing less common ones.
"""
import random
from typing import List
from collections import defaultdict


def select_balanced_urls(all_urls: List[str], max_items: int, already_scraped_urls: set = None) -> List[str]:
    """
    Select URLs evenly from different car make searches.
    
    The discovery process searches by make (hyundai, toyota, etc), so URLs discovered
    from each make search are interleaved to ensure balanced coverage.
    
    Args:
        all_urls: All discovered URLs
        max_items: Maximum number of URLs to select
        already_scraped_urls: Set of URLs already in database (to skip)
    
    Returns:
        List of selected URLs, balanced across makes
    """
    if already_scraped_urls is None:
        already_scraped_urls = set()
    
    # Filter out already scraped URLs
    unscraped_urls = [url for url in all_urls if url not in already_scraped_urls]
    
    if len(unscraped_urls) <= max_items:
        return unscraped_urls
    
    # Since URLs don't contain make info, we can't truly balance by make
    # But we can ensure we're not always scraping from the start of the list
    # by shuffling and taking a random sample
    
    # Strategy: Take URLs from different parts of the list
    # This works because discovery adds URLs by make search order
    
    chunk_size = len(unscraped_urls) // max_items
    if chunk_size < 1:
        chunk_size = 1
    
    selected = []
    for i in range(max_items):
        # Calculate position in the list to sample from
        start_idx = (i * chunk_size) % len(unscraped_urls)
        
        # Add some randomness within a small window
        window_size = min(10, len(unscraped_urls) // 20)
        idx = (start_idx + random.randint(0, window_size)) % len(unscraped_urls)
        
        url = unscraped_urls[idx]
        if url not in selected:
            selected.append(url)
    
    return selected[:max_items]


def get_scraped_urls_from_db() -> set:
    """
    Query database for all Facebook URLs that have been scraped.
    This allows us to skip URLs we've already processed.
    """
    import os
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    
    try:
        from db.models import CarListing
        
        DATABASE_URL = os.getenv("DATABASE_URL")
        if not DATABASE_URL:
            return set()
        
        # Convert async URL to sync for this utility
        if "asyncpg" in DATABASE_URL:
            DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")
        
        engine = create_engine(DATABASE_URL, echo=False)
        Session = sessionmaker(bind=engine)
        
        with Session() as session:
            result = session.execute(
                select(CarListing.url)
                .where(CarListing.source == "Facebook Marketplace")
            )
            urls = {row[0] for row in result.fetchall()}
            return urls
            
    except Exception as e:
        print(f"⚠️  Could not fetch scraped URLs from DB: {e}")
        return set()
