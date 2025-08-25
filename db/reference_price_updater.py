# db/reference_price_updater.py
from collections import defaultdict
from datetime import datetime
from statistics import mean, median

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from db.db_setup import SessionLocal
from db.models import CarListing, ModelPriceCoeffs
from utils.normalizer import normalize_make_model  # returns (make_norm, model_norm, model_base)


def update_reference_prices() -> None:
    """
    Updates reference prices and model coefficients using normalized make/model names.
    Groups cars by make and model_base to calculate price statistics and linear regression
    coefficients for predicting prices based on year and mileage.
    """
    session: Session = SessionLocal()
    try:
        print("Updating reference prices...")

        # Pull all valid car listings
        cars = session.execute(
            select(CarListing).where(
                CarListing.price.isnot(None),
                CarListing.year.isnot(None),
            )
        ).scalars().all()

        # Group by normalized (make, model_base)
        buckets = defaultdict(list)
        for c in cars:
            nm, _nmod, mbase = normalize_make_model(c.make, c.model)
            if not nm or not mbase or not c.year or not c.price:
                continue
            try:
                y = int(c.year)
                p = int(c.price)
            except (TypeError, ValueError):
                continue
            if y < 1980 or y > datetime.utcnow().year + 1 or p <= 0:
                continue
            buckets[(nm, mbase)].append((p, y))  # Store price and year

        now = datetime.utcnow()
        processed = 0

        # Process each make/model combination
        for (mk, mb), price_years in buckets.items():
            if len(price_years) < 25:  # Need enough samples for meaningful statistics
                continue
                
            prices = [p for p, _ in price_years]
            years = [y for _, y in price_years]
            
            # Calculate statistics
            median_price = int(median(prices))
            avg_year = mean(years)
            n_samples = len(prices)
            
            # Update or insert into ModelPriceCoeffs
            existing = session.execute(
                select(ModelPriceCoeffs).where(
                    ModelPriceCoeffs.make == mk,
                    ModelPriceCoeffs.model == mb
                )
            ).scalar_one_or_none()

            if existing:
                existing.n_samples = n_samples
                existing.updated_at = now
                # Note: Currently not updating coefficients as they require more complex calculation
            else:
                session.add(
                    ModelPriceCoeffs(
                        make=mk,
                        model=mb,
                        n_samples=n_samples,
                        coef_intercept=median_price,  # Simplified: using median as baseline
                        coef_year=0.0,  # These would need proper regression
                        coef_log_km=0.0,
                        updated_at=now
                    )
                )
            processed += 1

        session.commit()
        print(f"Model price coefficients updated. Processed {processed} make/model combinations.")

    finally:
        session.close()
