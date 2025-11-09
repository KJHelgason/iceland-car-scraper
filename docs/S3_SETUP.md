# AWS S3 Image Storage Setup Guide

## Overview
This system downloads car images and uploads them to AWS S3 for permanent storage. Dynamic URLs from dealerships (like Bilasölur's `CarImage.aspx` endpoints) expire after 24 hours, so we need permanent hosting.

## Why S3?
- **Permanent URLs**: Images stay accessible forever
- **Fast CDN**: AWS CloudFront integration for fast global delivery
- **Cheap**: ~$0.023/GB/month for storage
- **Reliable**: 99.999999999% durability
- **Scalable**: Handle unlimited images

## Setup Steps

### 1. Create AWS Account
1. Go to https://aws.amazon.com/
2. Click "Create an AWS Account"
3. Follow the sign-up process (requires credit card)
4. Free tier includes:
   - 5GB S3 storage
   - 20,000 GET requests
   - 2,000 PUT requests per month

### 2. Create IAM User for Programmatic Access
1. Go to AWS Console → IAM → Users
2. Click "Add users"
3. User name: `iceland-car-scraper`
4. Select "Access key - Programmatic access"
5. Click "Next: Permissions"
6. Click "Attach existing policies directly"
7. Search and select: `AmazonS3FullAccess`
8. Click "Next" until "Create user"
9. **IMPORTANT**: Save the Access Key ID and Secret Access Key (shown only once!)

### 3. Configure Environment Variables
Add to your `.env` file:
```bash
AWS_ACCESS_KEY_ID=AKIA2EXAMPLEKEY12345
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
AWS_S3_BUCKET=iceland-car-images
AWS_S3_REGION=eu-north-1
```

**Region Options** (choose closest to Iceland):
- `eu-north-1` - Stockholm (RECOMMENDED - closest to Iceland)
- `eu-west-1` - Ireland
- `eu-west-2` - London
- `us-east-1` - Virginia (cheapest, but farthest)

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

This installs:
- `boto3` - AWS SDK for Python
- `aiohttp` - Async HTTP client for downloading images

### 5. Test S3 Configuration
```bash
python utils/s3_uploader.py
```

This will:
- Check if bucket exists
- Create bucket if needed
- Set public-read permissions
- Test connectivity

Expected output:
```
Testing S3 configuration...
Bucket: iceland-car-images
Region: eu-north-1
Access Key: AKIA2EXAMP...
✓ S3 bucket is accessible
```

### 6. Migrate Existing Images (Optional)
Migrate existing database images to S3:

**Dry run first** (see what would happen):
```bash
python migrate_images_to_s3.py --dry-run --limit=10
```

**Migrate specific source**:
```bash
python migrate_images_to_s3.py --sources=Bilasolur --limit=100
```

**Migrate all sources**:
```bash
python migrate_images_to_s3.py --limit=1000
```

Parameters:
- `--dry-run` or `-d`: Test without saving changes
- `--limit=N`: Max images per source (default: 100)
- `--sources=A,B,C`: Comma-separated source names

### 7. Enable S3 in Scrapers
S3 is already enabled in `bilasolur_scraper.py`. To toggle:

```python
# In scrapers/dealerships/bilasolur_scraper.py
USE_S3_STORAGE = True   # Enable S3 uploads
USE_S3_STORAGE = False  # Use temporary URLs (old behavior)
```

## How It Works

### Image Upload Flow
1. **Scraper finds image URL** (e.g., `https://bilasolur.isCarImage.aspx?s=16&c=789541&p=3777561&w=784`)
2. **Download image bytes** via `aiohttp`
3. **Generate S3 key** in format: `{source}/{year}/{make}/{model}/{listing_id}_{hash}.jpg`
   - Example: `bilasolur/2023/toyota/yaris/12345_a3f8d9.jpg`
4. **Upload to S3** with public-read access
5. **Save S3 URL** to database: `https://iceland-car-images.s3.eu-north-1.amazonaws.com/bilasolur/2023/toyota/yaris/12345_a3f8d9.jpg`

### S3 URL Structure
```
https://{bucket}.s3.{region}.amazonaws.com/{source}/{year}/{make}/{model}/{id}_{hash}.jpg
```

Benefits:
- **Organized**: Easy to browse by source, year, make, model
- **Unique**: Hash prevents duplicates
- **Permanent**: Never expires
- **Public**: Directly accessible in web browsers

## Cost Estimates

### Storage Costs (eu-north-1 Stockholm)
- **Storage**: $0.023 per GB/month
- **Requests**: 
  - PUT/POST: $0.005 per 1,000 requests
  - GET: $0.0004 per 1,000 requests
- **Data Transfer Out**: $0.09 per GB (after 100GB free tier)

### Example: 20,000 cars
- Average image: 100KB
- Total storage: 2GB = **$0.05/month**
- Monthly uploads: 1,000 new cars = **$0.005**
- Monthly views: 100,000 = **$0.04**
- **Total: ~$0.10/month** (well within free tier first year)

## Troubleshooting

### Error: "NoCredentialsError"
- Check `.env` file has `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`
- Restart your application after updating `.env`

### Error: "Access Denied"
- Verify IAM user has `AmazonS3FullAccess` policy
- Check bucket policy allows public reads

### Error: "Bucket already exists"
- Someone else owns that bucket name
- Change `AWS_S3_BUCKET` to a unique name
- Bucket names must be globally unique across all AWS accounts

### Images not uploading
- Check `USE_S3_STORAGE = True` in scraper
- Run `python utils/s3_uploader.py` to test connection
- Check logs for specific error messages

### Slow uploads
- Choose region closer to your server (eu-north-1 for Hetzner)
- Images upload asynchronously, shouldn't block scraping
- Consider increasing `asyncio` concurrency

## Security Best Practices

1. **Never commit `.env` file** - It contains secrets!
2. **Use IAM user, not root account** - Better security
3. **Limit IAM permissions** - Only S3, not all AWS services
4. **Rotate access keys** - Change every 90 days
5. **Enable bucket versioning** - Recover deleted images
6. **Set up CloudFront CDN** - Faster delivery + DDoS protection

## Advanced: CloudFront CDN Setup (Optional)

For faster image delivery worldwide:

1. Go to AWS CloudFront → Create Distribution
2. Origin Domain: Your S3 bucket
3. Origin Access: Public
4. Default Cache Behavior: Cache everything
5. Price Class: Use only North America and Europe
6. Create distribution

Then update image URLs to use CloudFront:
```python
# Instead of: https://iceland-car-images.s3.eu-north-1.amazonaws.com/...
# Use: https://d1234abcd.cloudfront.net/...
```

Benefits:
- **Faster**: Cached at edge locations worldwide
- **Cheaper**: Reduced S3 GET requests
- **Custom domain**: Use `images.yoursite.com`

## Monitoring

Check S3 usage:
1. Go to AWS Console → S3 → Your bucket
2. Click "Metrics" tab
3. View:
   - Storage (GB)
   - Requests (per day)
   - Data transfer

Set up billing alerts:
1. AWS Console → Billing → Budgets
2. Create budget: $1/month
3. Get email if exceeded

## Next Steps

1. ✅ Set up AWS account and IAM user
2. ✅ Configure `.env` with AWS credentials  
3. ✅ Test with `python utils/s3_uploader.py`
4. ✅ Migrate existing images: `python migrate_images_to_s3.py --dry-run --limit=10`
5. ✅ Enable in scrapers: `USE_S3_STORAGE = True`
6. ✅ Deploy to Hetzner
7. 🔜 (Optional) Set up CloudFront CDN
8. 🔜 (Optional) Enable bucket versioning
9. 🔜 Set up billing alerts
