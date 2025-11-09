-- Migration: Add image_url column to car_listings table
-- Date: 2025-10-26
-- Description: Adds nullable image_url column to store primary listing image URLs

ALTER TABLE car_listings ADD COLUMN IF NOT EXISTS image_url VARCHAR;

-- Optional: Add index if frequently querying by image presence
-- CREATE INDEX idx_car_listings_has_image ON car_listings(image_url) WHERE image_url IS NOT NULL;
