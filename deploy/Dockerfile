# Container image for automated scraping scheduler
# Using official Playwright image for all browser dependencies
FROM mcr.microsoft.com/playwright/python:v1.54.0-jammy

WORKDIR /app

# Install dependencies first for layer caching
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir typer[all]

# Copy application code
COPY . /app

ENV PYTHONUNBUFFERED=1 \
    TZ=UTC

# Default command launches the async scheduler
CMD ["python", "scripts/scheduler.py"]
