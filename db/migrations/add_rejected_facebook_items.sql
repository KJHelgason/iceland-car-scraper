-- Migration: Add rejected Facebook items tracking
-- Purpose: Store item IDs that are non-cars or failed, so we don't waste time discovering/scraping them again

CREATE TABLE IF NOT EXISTS rejected_facebook_items (
    id SERIAL PRIMARY KEY,
    item_id VARCHAR(255) UNIQUE NOT NULL,
    reason VARCHAR(50) NOT NULL,  -- 'non_vehicle', 'navigation_failed', 'invalid_data'
    rejected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

CREATE INDEX idx_rejected_facebook_items_item_id ON rejected_facebook_items(item_id);
CREATE INDEX idx_rejected_facebook_items_reason ON rejected_facebook_items(reason);

-- Add last_seen_at column to car_listings for automatic inactive detection
ALTER TABLE car_listings 
ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP;

-- Update existing Facebook listings to have last_seen_at = scraped_at
UPDATE car_listings 
SET last_seen_at = scraped_at 
WHERE source = 'Facebook Marketplace' 
AND last_seen_at IS NULL 
AND scraped_at IS NOT NULL;

-- Create index for efficient last_seen_at queries
CREATE INDEX IF NOT EXISTS idx_car_listings_last_seen 
ON car_listings(source, last_seen_at) 
WHERE source = 'Facebook Marketplace';
