# Iceland Car Scraper

Automated scraping and analysis of Icelandic car listings (Facebook Marketplace, Bilaland, Bilasölur).

## Features
- Async Playwright scraping of Facebook Marketplace (requires logged-in cookie state `fb_state.json`).
- Dealership scrapers for Bilaland and Bilasölur (including daily seed URL discovery).
- Data normalization (make/model/year/title) and reference price calculation.
- Deal detection vs model reference prices.
- CLI for one-off operations.
- Scheduler for continuous automation.
- Dockerized deployment (Playwright Chromium baked in).

## Project Structure
```
scripts/cli.py          # Typer CLI commands
scripts/scheduler.py    # APScheduler recurring jobs
deploy/Dockerfile       # Container image
deploy/docker-compose.yml
.env.example            # Environment variable template
scrapers/               # Source scrapers
analysis/               # Model training & analysis scripts
db/                     # Database models and utilities
```

## Quickstart (Local)
1. Create and fill `.env` from template:
```
cp .env.example .env
```
2. (Optional) Create venv & install:
```
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install typer[all]
```
3. Obtain Facebook cookie state (login once):
```
python save_fb_cookies.py  # Follow console instructions
```
4. Run a scraper:
```
python scripts/cli.py scrape-bilaland
python scripts/cli.py scrape-fb --max-items 5
```
5. Run scheduler continuously:
```
python scripts/scheduler.py
```

## CLI Commands
```
python scripts/cli.py --help
python scripts/cli.py scrape-fb --max-items 10
python scripts/cli.py scrape-bilaland --max-scrolls 5
python scripts/cli.py scrape-bilasolur --max-pages 100
python scripts/cli.py scrape-bilasolur-discover --max-pages 500
python scripts/cli.py update-refs
python scripts/cli.py check-deals
python scripts/cli.py normalize-existing --batch-size 200
```

## Scheduler Jobs (UTC)
| Job | Schedule | Description |
|-----|----------|-------------|
| Bilaland | Every 30 min | Scrape + update refs + deal check |
| Bilasölur | :15 and :45 | Scrape + update refs + deal check |
| Facebook | Hourly at :05 | Scrape + update refs + deal check |
| Bilasölur Discovery | 02:30 daily | Discover seed URLs then deep scrape |

Adjust timings in `scripts/scheduler.py` as needed.

## Docker Deployment
Build & run with Docker Compose (recommended for servers):
```
cd deploy
cp ../.env.example ../.env  # edit values
# (Copy fb_state.json if you have one)
docker compose build
docker compose up -d
```
View logs:
```
docker compose logs -f app
```
Run one-off command in container:
```
docker compose exec -T app python scripts/cli.py scrape-bilaland
```

### Updating
```
cd iceland-car-scraper
git pull
cd deploy
docker compose build --pull
docker compose up -d
```

### Mounting Facebook Cookie State
Uncomment the `fb_state.json` volume line in `deploy/docker-compose.yml` and ensure the file exists at repo root.

## Database
Default: SQLite stored under `data/` (host-mounted in Docker). For Postgres, set `DATABASE_URL` in `.env`:
```
DATABASE_URL=postgresql://user:password@host:5432/dbname
```

## Environment Variables
See `.env.example`.

## Backups (SQLite)
```
tar czf backup-$(date +%F).tgz data
```

## Notes
- Keep `fb_state.json` fresh if Facebook invalidates the session.
- Use modest scraping intervals to reduce risk of rate limiting.
- Logs show cycle boundaries for easier monitoring.

## Future Improvements
- Add structured tests for normalization logic.
- Integrate metrics (Prometheus / simple JSON stats endpoint).
- Add rotating file logging.
- Container health endpoint.

---
Happy scraping!
