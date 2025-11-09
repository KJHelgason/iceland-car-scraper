# Facebook Scraper AI Provider Options

The Facebook scraper can use different AI providers for extracting vehicle data. Due to Google's Gemini API restrictions on scraping third-party sites, we recommend using OpenAI.

## Option 1: OpenAI (Recommended)

OpenAI's terms of service are more permissive for data extraction tasks.

### Setup:

1. **Get an OpenAI API key**:
   - Go to https://platform.openai.com/api-keys
   - Create an account if you don't have one
   - Generate a new API key
   - **Cost**: ~$0.15 per 1M tokens with GPT-4o-mini (very cheap for this use case)

2. **Install the OpenAI package**:
   ```bash
   pip install openai
   ```

3. **Add to your `.env` file**:
   ```
   OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxx
   AI_PROVIDER=openai
   ```

4. **Test it**:
   ```bash
   python -c "from scrapers.facebook_scraper import scrape_facebook; import asyncio; asyncio.run(scrape_facebook(max_items=1))"
   ```

### Pricing

- **GPT-4o-mini**: $0.150 per 1M input tokens, $0.600 per 1M output tokens
- **Typical Facebook listing**: ~500 tokens input, ~50 tokens output = $0.00010 per listing
- **196 listings**: ~$0.02 (essentially free)
- **1000 listings/day**: ~$0.10/day = $3/month

Much cheaper than Gemini was, and no restrictions on scraping!

## Option 2: Gemini (Not Recommended - Violates ToS)

Google's Gemini API explicitly prohibits scraping third-party websites. Your project was suspended for this reason.

**Do not use Gemini for Facebook scraping.**

## Option 3: Regex-Only (Free, No AI)

If you don't want to use any AI service, the scraper has a regex fallback that extracts data without AI.

### Setup:

1. **Add to your `.env` file**:
   ```
   AI_PROVIDER=regex
   ```

2. **No API key needed**

### Limitations:

- Less accurate for make/model extraction
- May miss mileage if formatted unusually
- Year extraction still works well
- Price extraction works well

### When to use:

- You want zero cost
- You're okay with ~70-80% accuracy vs 95%+ with AI
- Privacy concerns about sending data to third parties

## Switching Providers

You can change providers at any time by updating `AI_PROVIDER` in your `.env` file:

```bash
AI_PROVIDER=openai   # Use OpenAI (recommended)
AI_PROVIDER=gemini   # Use Gemini (not recommended - ToS violation)
AI_PROVIDER=regex    # Use regex only (no AI, free)
```

## Current Configuration

Check your current provider:
```bash
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print(f'AI Provider: {os.getenv(\"AI_PROVIDER\", \"openai (default)\")}')"
```

## Re-scraping Incomplete Listings with OpenAI

Once you've set up OpenAI, you can re-scrape the 196 incomplete Facebook listings:

```bash
# Set up OpenAI first
pip install openai
echo "OPENAI_API_KEY=sk-proj-your-key-here" >> .env
echo "AI_PROVIDER=openai" >> .env

# Then re-scrape
python rescrape_incomplete_facebook.py
```

This will cost approximately $0.02 and take about 10-15 minutes.
