"""
S3 Image Cleanup Utility
Handles deletion of orphaned images from S3 when listings are deleted.
"""

import os
import re
from typing import List, Optional
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

# S3 Configuration
S3_BUCKET = os.getenv('AWS_S3_BUCKET', 'iceland-car-images')
S3_REGION = os.getenv('AWS_S3_REGION', 'eu-north-1')
AWS_ACCESS_KEY = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')

# Initialize S3 client
_s3_client = None


def get_s3_client():
    """Get or create S3 client."""
    global _s3_client
    if _s3_client is None:
        if not AWS_ACCESS_KEY or not AWS_SECRET_KEY:
            raise ValueError(
                "AWS credentials not found. Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY "
                "in your .env file or environment variables."
            )
        
        _s3_client = boto3.client(
            's3',
            region_name=S3_REGION,
            aws_access_key_id=AWS_ACCESS_KEY,
            aws_secret_access_key=AWS_SECRET_KEY
        )
    return _s3_client


def extract_s3_key_from_url(image_url: str) -> Optional[str]:
    """
    Extract the S3 key from a full S3 URL.
    
    Example:
        Input: https://iceland-car-images.s3.eu-north-1.amazonaws.com/bilasolur/2021/skoda/enyaq-style-plus/10562_506f0b.jpg
        Output: bilasolur/2021/skoda/enyaq-style-plus/10562_506f0b.jpg
    """
    if not image_url:
        return None
    
    # Check if it's an S3 URL
    if S3_BUCKET not in image_url:
        return None
    
    # Parse URL and extract path
    parsed = urlparse(image_url)
    # Remove leading slash
    key = parsed.path.lstrip('/')
    
    return key if key else None


def delete_s3_image(image_url: str) -> bool:
    """
    Delete an image from S3 given its full URL.
    
    Args:
        image_url: Full S3 URL of the image
        
    Returns:
        True if deleted successfully, False otherwise
    """
    if not image_url:
        return False
    
    s3_key = extract_s3_key_from_url(image_url)
    if not s3_key:
        print(f"[S3] Skipping non-S3 URL: {image_url[:100]}")
        return False
    
    try:
        s3_client = get_s3_client()
        s3_client.delete_object(Bucket=S3_BUCKET, Key=s3_key)
        print(f"[S3] Deleted: {s3_key}")
        return True
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', '')
        if error_code == '404' or error_code == 'NoSuchKey':
            print(f"[S3] Image not found (already deleted?): {s3_key}")
            return False
        else:
            print(f"[S3] Error deleting {s3_key}: {e}")
            return False
    except Exception as e:
        print(f"[S3] Unexpected error deleting {s3_key}: {e}")
        return False


def delete_s3_images_batch(image_urls: List[str]) -> int:
    """
    Delete multiple images from S3.
    
    Args:
        image_urls: List of full S3 URLs
        
    Returns:
        Number of images successfully deleted
    """
    if not image_urls:
        return 0
    
    deleted_count = 0
    for url in image_urls:
        if delete_s3_image(url):
            deleted_count += 1
    
    return deleted_count


def find_orphaned_images():
    """
    Find images in S3 that don't have corresponding database entries.
    This is useful for cleanup but should be run carefully.
    
    Returns:
        List of orphaned S3 keys
    """
    from db.db_setup import SessionLocal
    from db.models import CarListing
    
    print("[S3] Finding orphaned images...")
    
    # Get all image URLs from database
    session = SessionLocal()
    db_image_urls = session.query(CarListing.image_url).filter(
        CarListing.image_url.isnot(None)
    ).all()
    session.close()
    
    # Extract S3 keys
    db_keys = set()
    for (url,) in db_image_urls:
        key = extract_s3_key_from_url(url)
        if key:
            db_keys.add(key)
    
    print(f"[S3] Found {len(db_keys)} images referenced in database")
    
    # List all objects in S3
    s3_client = get_s3_client()
    paginator = s3_client.get_paginator('list_objects_v2')
    
    s3_keys = set()
    for page in paginator.paginate(Bucket=S3_BUCKET):
        if 'Contents' in page:
            for obj in page['Contents']:
                s3_keys.add(obj['Key'])
    
    print(f"[S3] Found {len(s3_keys)} images in S3 bucket")
    
    # Find orphans
    orphaned = s3_keys - db_keys
    
    print(f"[S3] Found {len(orphaned)} orphaned images")
    
    return list(orphaned)


def cleanup_orphaned_images(dry_run: bool = True) -> int:
    """
    Delete orphaned images from S3.
    
    Args:
        dry_run: If True, only print what would be deleted
        
    Returns:
        Number of images deleted (or would be deleted if dry_run)
    """
    orphaned = find_orphaned_images()
    
    if not orphaned:
        print("[S3] No orphaned images to clean up")
        return 0
    
    if dry_run:
        print(f"[S3] DRY RUN: Would delete {len(orphaned)} orphaned images")
        print("[S3] Sample orphaned keys:")
        for key in orphaned[:10]:
            print(f"  - {key}")
        if len(orphaned) > 10:
            print(f"  ... and {len(orphaned) - 10} more")
        return len(orphaned)
    
    # Actually delete
    print(f"[S3] Deleting {len(orphaned)} orphaned images...")
    s3_client = get_s3_client()
    deleted = 0
    
    for key in orphaned:
        try:
            s3_client.delete_object(Bucket=S3_BUCKET, Key=key)
            deleted += 1
            if deleted % 100 == 0:
                print(f"[S3] Deleted {deleted}/{len(orphaned)}...")
        except Exception as e:
            print(f"[S3] Error deleting {key}: {e}")
    
    print(f"[S3] Deleted {deleted} orphaned images")
    return deleted


if __name__ == "__main__":
    # Test finding orphaned images
    orphaned = find_orphaned_images()
    print(f"\nFound {len(orphaned)} orphaned images")
    
    if orphaned:
        print("\nSample orphaned keys:")
        for key in orphaned[:20]:
            print(f"  {key}")
