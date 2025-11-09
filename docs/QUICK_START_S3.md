# Quick Start: S3 Image Storage

## You Already Have AWS Account ✅

## Step 1: Get AWS Credentials (5 minutes)

1. **Go to AWS IAM Console:**
   - https://console.aws.amazon.com/iam/

2. **Create IAM User:**
   - Click "Users" → "Add users"
   - Username: `iceland-car-scraper`
   - Access type: ✅ Access key - Programmatic access
   - Click "Next: Permissions"

3. **Set Permissions:**
   - Click "Attach existing policies directly"
   - Search and select: `AmazonS3FullAccess`
   - Click "Next" until "Create user"

4. **Save Credentials:**
   ```
   Access Key ID: AKIA2EXAMPLEKEY12345
   Secret Access Key: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
   ```
   ⚠️ **Save these now - shown only once!**

## Step 2: Configure Environment (1 minute)

Add to `.env` file:
```bash
AWS_ACCESS_KEY_ID=AKIA2EXAMPLEKEY12345
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
AWS_S3_BUCKET=iceland-car-images
AWS_S3_REGION=eu-north-1
```

## Step 3: Install & Test (2 minutes)

```bash
# Install dependencies
pip install boto3 aiohttp pillow

# Test connection and create bucket
python utils/s3_uploader.py
```

Expected output:
```
Testing S3 configuration...
Bucket: iceland-car-images
Region: eu-north-1
✓ S3 bucket is accessible
```

## Step 4: Re-scrape Images (varies)

**Why re-scrape?** Your existing Bilasölur URLs are expired (dynamic `CarImage.aspx`).
We need to visit each listing page to get fresh image URLs.

### Test First (2 minutes)
```bash
# Dry run with 5 listings
python rescrape_images_to_s3.py --dry-run --limit=5 --sources=Bilasolur
```

### Start Small (10 minutes)
```bash
# Process 50 Bilasölur listings
python rescrape_images_to_s3.py --sources=Bilasolur --limit=50
```

**What happens:**
1. Visits each listing page
2. Extracts fresh image URL
3. Downloads image
4. Validates size (min 200x150, rejects tiny images)
5. Optimizes (resize to 800x600, 85% JPEG quality)
6. Uploads to S3
7. Updates database with permanent S3 URL

**Output example:**
```
[1/50] TOYOTA YARIS
  URL: https://bilasolur.is/CarDetails.aspx?...
  ℹ Fresh image URL: https://bilasolur.isCarImage.aspx?s=16&c=789541...
  ℹ Size OK: 800x600 (no resize needed)
  ℹ Optimized: 145.2KB → 52.3KB (64.0% reduction)
  ✓ Uploaded to S3: https://iceland-car-images.s3.eu-north-1.amazonaws.com/bilasolur/2023/toyota/yaris/12345_a3f8d9.jpg
```

### Process All Sources

**Bilasölur** (expired URLs - must re-scrape):
```bash
python rescrape_images_to_s3.py --sources=Bilasolur --limit=1000
# ~11,000 listings × 0.8s = ~2.5 hours
```

**Other sources** (URLs might still work - can use direct migration):
```bash
# Try direct migration first (faster)
python migrate_images_to_s3.py --sources=Bilaland,Facebook --limit=500

# If URLs expired, use re-scrape
python rescrape_images_to_s3.py --sources=Bilaland,Facebook --limit=500
```

## Step 5: Enable in Scraper (already done!)

S3 is already enabled in `bilasolur_scraper.py`:
```python
USE_S3_STORAGE = True  # ✓ Already enabled
```

New listings will automatically upload to S3!

## Image Optimization Details

**Settings:**
- Max dimensions: 800×600 (perfect for web listings)
- Min dimensions: 200×150 (reject low-quality)
- JPEG quality: 85% (excellent visual quality)
- Maintains aspect ratio

**Results:**
- Original: ~150KB average
- Optimized: ~50KB average
- **67% file size reduction!**
- Faster page loads
- Lower bandwidth costs

## Costs

**Your database (13,745 active cars):**
- Storage: ~0.7GB × $0.023/GB = **$0.016/month**
- Bandwidth: ~$0.05/month
- **Total: ~$0.07/month**

**Free tier covers:**
- 5GB storage
- 20,000 requests/month
- **You'll pay $0 for the first year!**

## Troubleshooting

### "NoCredentialsError"
- Check `.env` has `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`
- Restart terminal/script after updating `.env`

### "AccessDenied"
- Verify IAM user has `AmazonS3FullAccess` policy
- Check bucket name is unique (try different name)

### "Image too small"
- Normal - some listings have placeholder images
- These are rejected automatically
- Listing still saved, just no image

### Slow processing
- Normal - visiting each page takes ~0.8s
- 1000 listings = ~15 minutes
- Can run in background
- Commits every 10 listings (safe to interrupt)

## Next Steps After Setup

1. **Deploy to Hetzner:**
   - Copy `.env` with AWS credentials
   - `pip install boto3 aiohttp pillow`
   - Restart scheduler

2. **Set billing alert:**
   - AWS Console → Billing → Budgets
   - Create budget: $1/month
   - Email notification

3. **Monitor first day:**
   - Check new listings have S3 URLs
   - Verify images load on website
   - Check AWS billing dashboard

4. **(Optional) CloudFront CDN:**
   - Faster global delivery
   - Lower costs
   - See `docs/S3_SETUP.md`

## Commands Reference

```bash
# Test S3 connection
python utils/s3_uploader.py

# Re-scrape (for expired URLs)
python rescrape_images_to_s3.py --sources=Bilasolur --limit=100

# Migrate (for valid URLs)
python migrate_images_to_s3.py --sources=Bilaland --limit=100

# Dry run (test without saving)
python rescrape_images_to_s3.py --dry-run --limit=5

# Process all sources
python rescrape_images_to_s3.py --limit=1000
```

## Support

- **Full guide:** `docs/S3_SETUP.md`
- **Technical details:** `docs/S3_IMPLEMENTATION.md`
- **AWS S3 Console:** https://console.aws.amazon.com/s3/
- **AWS IAM Console:** https://console.aws.amazon.com/iam/

---

**Ready to start?** Run:
```bash
python utils/s3_uploader.py
```
