"""
S3 Image Uploader Utility
Handles downloading car images and uploading to AWS S3 with proper naming.
Includes image validation and optimization for web display.
"""

import asyncio
import hashlib
import io
import os
import re
from typing import Optional, Tuple
from urllib.parse import urlparse

import boto3
import aiohttp
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

# S3 Configuration from environment variables
S3_BUCKET = os.getenv('AWS_S3_BUCKET', 'iceland-car-images')
S3_REGION = os.getenv('AWS_S3_REGION', 'eu-north-1')  # Stockholm region (closest to Iceland)
AWS_ACCESS_KEY = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')

# Image optimization settings
MAX_WIDTH = 800  # Max width for listing images
MAX_HEIGHT = 600  # Max height for listing images
JPEG_QUALITY = 85  # JPEG compression quality (1-100)
MIN_WIDTH = 200  # Minimum acceptable width
MIN_HEIGHT = 150  # Minimum acceptable height

# Initialize S3 client (will be created when needed)
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


def sanitize_filename(text: str) -> str:
    """Convert text to safe filename."""
    # Remove special characters, keep alphanumeric and spaces
    text = re.sub(r'[^\w\s-]', '', text.lower())
    # Replace spaces with hyphens
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-')


def generate_s3_key(listing_id: int, make: str, model: str, year: int, url: str) -> str:
    """
    Generate a unique S3 key for the image.
    Format: {source}/{year}/{make}/{model}/{listing_id}_{hash}.jpg
    
    Example: bilasolur/2023/toyota/yaris/12345_a3f8d9.jpg
    """
    # Extract source from URL or use default
    if 'bilasolur' in url.lower():
        source = 'bilasolur'
    elif 'bilaland' in url.lower():
        source = 'bilaland'
    elif 'facebook' in url.lower():
        source = 'facebook'
    elif 'hekla' in url.lower():
        source = 'hekla'
    elif 'brimborg' in url.lower():
        source = 'brimborg'
    elif 'br.is' in url.lower():
        source = 'br'
    elif 'islandsbilar' in url.lower():
        source = 'islandsbilar'
    else:
        source = 'other'
    
    # Create hash of URL for uniqueness (first 6 chars)
    url_hash = hashlib.md5(url.encode()).hexdigest()[:6]
    
    # Sanitize make and model
    make_clean = sanitize_filename(make or 'unknown')
    model_clean = sanitize_filename(model or 'unknown')
    year_str = str(year) if year else 'unknown'
    
    # Build key path
    key = f"{source}/{year_str}/{make_clean}/{model_clean}/{listing_id}_{url_hash}.jpg"
    
    return key


async def download_image(url: str, timeout: int = 15) -> Optional[bytes]:
    """
    Download image from URL.
    Returns image bytes or None if failed.
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=timeout) as response:
                if response.status == 200:
                    content_type = response.headers.get('Content-Type', '')
                    if 'image' in content_type or url.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                        return await response.read()
                    else:
                        print(f"  ⚠ URL is not an image: {content_type}")
                        return None
                else:
                    print(f"  ✗ Failed to download (status {response.status}): {url}")
                    return None
    except asyncio.TimeoutError:
        print(f"  ✗ Timeout downloading: {url}")
        return None
    except Exception as e:
        print(f"  ✗ Error downloading: {e}")
        return None


def validate_and_optimize_image(image_bytes: bytes) -> Optional[Tuple[bytes, int, int]]:
    """
    Validate image size/quality and optimize for web display.
    Returns (optimized_bytes, width, height) or None if invalid.
    """
    try:
        # Open image
        img = Image.open(io.BytesIO(image_bytes))
        
        # Get original dimensions
        orig_width, orig_height = img.size
        
        # Validate minimum size
        if orig_width < MIN_WIDTH or orig_height < MIN_HEIGHT:
            print(f"  ⚠ Image too small: {orig_width}x{orig_height} (min {MIN_WIDTH}x{MIN_HEIGHT})")
            return None
        
        # Convert to RGB if needed (for JPEG compatibility)
        if img.mode in ('RGBA', 'LA', 'P'):
            # Create white background for transparency
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Calculate new dimensions (maintain aspect ratio)
        if orig_width > MAX_WIDTH or orig_height > MAX_HEIGHT:
            # Calculate scaling factor
            width_ratio = MAX_WIDTH / orig_width
            height_ratio = MAX_HEIGHT / orig_height
            scale_factor = min(width_ratio, height_ratio)
            
            new_width = int(orig_width * scale_factor)
            new_height = int(orig_height * scale_factor)
            
            # Resize with high-quality algorithm
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            print(f"  ℹ Resized: {orig_width}x{orig_height} → {new_width}x{new_height}")
        else:
            new_width, new_height = orig_width, orig_height
            print(f"  ℹ Size OK: {new_width}x{new_height} (no resize needed)")
        
        # Optimize and save to bytes
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=JPEG_QUALITY, optimize=True)
        optimized_bytes = output.getvalue()
        
        # Calculate size reduction
        orig_size_kb = len(image_bytes) / 1024
        new_size_kb = len(optimized_bytes) / 1024
        reduction = ((orig_size_kb - new_size_kb) / orig_size_kb * 100) if orig_size_kb > 0 else 0
        
        print(f"  ℹ Optimized: {orig_size_kb:.1f}KB → {new_size_kb:.1f}KB ({reduction:.1f}% reduction)")
        
        return optimized_bytes, new_width, new_height
        
    except Exception as e:
        print(f"  ✗ Error validating/optimizing image: {e}")
        return None


def upload_to_s3(image_bytes: bytes, s3_key: str, content_type: str = 'image/jpeg') -> Optional[str]:
    """
    Upload image bytes to S3.
    Returns public URL or None if failed.
    """
    try:
        s3_client = get_s3_client()
        
        # Upload without ACL (use bucket's default settings)
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=image_bytes,
            ContentType=content_type,
            CacheControl='max-age=31536000',  # Cache for 1 year
        )
        
        # Generate public URL (will work if bucket allows public access)
        public_url = f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{s3_key}"
        
        return public_url
        
    except ClientError as e:
        print(f"  ✗ S3 upload error: {e}")
        return None
    except Exception as e:
        print(f"  ✗ Error uploading to S3: {e}")
        return None


async def download_and_upload_image(
    image_url: str,
    listing_id: int,
    make: str,
    model: str,
    year: int,
    source_url: str
) -> Optional[str]:
    """
    Download image from URL, validate/optimize, and upload to S3.
    Returns S3 URL or None if failed.
    
    Args:
        image_url: URL of the image to download
        listing_id: Database ID of the listing
        make: Car make (for S3 path organization)
        model: Car model (for S3 path organization)
        year: Car year (for S3 path organization)
        source_url: Source website URL (to determine source)
    
    Returns:
        S3 public URL or None if failed
    """
    # Download image
    image_bytes = await download_image(image_url)
    if not image_bytes:
        return None
    
    # Validate and optimize
    result = validate_and_optimize_image(image_bytes)
    if not result:
        return None
    
    optimized_bytes, width, height = result
    
    # Generate S3 key
    s3_key = generate_s3_key(listing_id, make, model, year, source_url)
    
    # Upload to S3 (always JPEG after optimization)
    s3_url = upload_to_s3(optimized_bytes, s3_key, content_type='image/jpeg')
    
    return s3_url


def check_s3_bucket_exists() -> bool:
    """Check if S3 bucket exists and is accessible."""
    try:
        s3_client = get_s3_client()
        s3_client.head_bucket(Bucket=S3_BUCKET)
        return True
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == '404':
            print(f"Bucket '{S3_BUCKET}' does not exist")
        elif error_code == '403':
            print(f"Access denied to bucket '{S3_BUCKET}'")
        else:
            print(f"Error checking bucket: {e}")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False


def create_s3_bucket() -> bool:
    """Create S3 bucket if it doesn't exist."""
    try:
        s3_client = get_s3_client()
        
        # Create bucket with location constraint
        if S3_REGION == 'us-east-1':
            s3_client.create_bucket(Bucket=S3_BUCKET)
        else:
            s3_client.create_bucket(
                Bucket=S3_BUCKET,
                CreateBucketConfiguration={'LocationConstraint': S3_REGION}
            )
        
        print(f"✓ Created bucket '{S3_BUCKET}' in {S3_REGION}")
        
        # Try to enable public access (may fail if account blocks it - that's OK)
        try:
            # Delete public access block to allow public reads
            s3_client.delete_public_access_block(Bucket=S3_BUCKET)
            
            # Set bucket policy to allow public read access
            bucket_policy = {
                "Version": "2012-10-17",
                "Statement": [{
                    "Sid": "PublicReadGetObject",
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": "s3:GetObject",
                    "Resource": f"arn:aws:s3:::{S3_BUCKET}/*"
                }]
            }
            
            import json
            s3_client.put_bucket_policy(
                Bucket=S3_BUCKET,
                Policy=json.dumps(bucket_policy)
            )
            print(f"✓ Enabled public access for bucket")
        except ClientError as e:
            # Public access blocked - that's OK, images will still work with CloudFront or presigned URLs
            print(f"⚠ Could not enable public access (account may block public policies)")
            print(f"  Images will upload successfully but may need CloudFront or presigned URLs")
        
        return True
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'BucketAlreadyOwnedByYou':
            print(f"✓ Bucket '{S3_BUCKET}' already exists")
            return True
        else:
            print(f"✗ Error creating bucket: {e}")
            return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


if __name__ == "__main__":
    """Test S3 connection and bucket setup."""
    print("Testing S3 configuration...")
    print(f"Bucket: {S3_BUCKET}")
    print(f"Region: {S3_REGION}")
    print(f"Access Key: {AWS_ACCESS_KEY[:10]}..." if AWS_ACCESS_KEY else "Not set")
    print()
    
    if check_s3_bucket_exists():
        print("✓ S3 bucket is accessible")
    else:
        print("Creating S3 bucket...")
        if create_s3_bucket():
            print("✓ S3 bucket created successfully")
        else:
            print("✗ Failed to create S3 bucket")
