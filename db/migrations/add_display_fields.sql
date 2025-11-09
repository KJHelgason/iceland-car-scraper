-- Add display_make and display_name columns to car_listings
-- These columns store properly capitalized/formatted versions for display on the website

ALTER TABLE car_listings 
ADD COLUMN IF NOT EXISTS display_make VARCHAR,
ADD COLUMN IF NOT EXISTS display_name VARCHAR;

-- Create index for faster queries on display fields
CREATE INDEX IF NOT EXISTS idx_car_listings_display_make ON car_listings(display_make);
CREATE INDEX IF NOT EXISTS idx_car_listings_display_name ON car_listings(display_name);
