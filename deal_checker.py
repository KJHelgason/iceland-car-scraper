# deal_checker.py
import math
from datetime import datetime
from sqlalchemy import select, and_
from sqlalchemy.orm import Session
from sqlalchemy import desc
from db.db_setup import SessionLocal
from db.models import CarListing, ReferencePrice, DealLog, ManualReview
#from utils.normalizer import normalize_make_model
from utils.normalizer import normalize_make, model_base as model_base_fn


# Thresholds (percent below baseline)
TIER_GOOD_MIN = 15   # 15–30% => good deal
TIER_GOOD_MAX = 30
TIER_STRONG_MIN = 31 # 31–69% => strong deal
TIER_STRONG_MAX = 69
TIER_SUSPECT_MIN = 70  # ≥70% => suspected bad data -> manual review only

def _pick_baseline(ref: ReferencePrice) -> int | None:
    """
    Choose a baseline price for comparison.
    Prefer median_price; if missing, fallback to average of min/max.
    """
    if getattr(ref, "median_price", None):
        return int(ref.median_price)
    if ref.min_price is not None and ref.max_price is not None:
        return int((ref.min_price + ref.max_price) / 2)
    return None

def _already_logged(session: Session, listing_id: int) -> bool:
    return session.execute(
        select(DealLog.id).where(DealLog.listing_id == listing_id)
    ).first() is not None

def _already_in_manual_review(session: Session, listing_id: int) -> bool:
    return session.execute(
        select(ManualReview.id).where(ManualReview.listing_id == listing_id)
    ).first() is not None

def _ref_cols():
    """
    Return the actual columns to use from ReferencePrice, regardless of whether
    your table uses (make, model) or (make_norm, model_base), and whether the
    timestamp is last_updated or updated_at.
    """
    make_col = getattr(ReferencePrice, "make", None) or getattr(ReferencePrice, "make_norm", None)
    model_col = getattr(ReferencePrice, "model", None) or getattr(ReferencePrice, "model_base", None)
    year_col = getattr(ReferencePrice, "year", None)
    ts_col = (
        getattr(ReferencePrice, "last_updated", None)
        or getattr(ReferencePrice, "updated_at", None)
        or ReferencePrice.id  # fallback ordering
    )
    if make_col is None or model_col is None:
        raise RuntimeError(
            "ReferencePrice table is missing required columns. "
            "Expected (make & model) or (make_norm & model_base)."
        )
    return make_col, model_col, year_col, ts_col

def _find_reference(session, make_raw: str | None, model_raw: str | None, year: int | None = None):
    """
    Get the best ReferencePrice row for this make/model(/year).
    - normalizes inputs,
    - matches whichever columns your table has,
    - if multiple rows exist, returns the most recently updated one.
    """
    make_norm = normalize_make(make_raw)
    model_base_norm = model_base_fn(model_raw)

    if not make_norm or not model_base_norm:
        return None

    make_col, model_col, year_col, ts_col = _ref_cols()

    q = (
        session.query(ReferencePrice)
        .filter(make_col == make_norm)
        .filter(model_col == model_base_norm)
    )
    if year_col is not None and year is not None:
        q = q.filter(year_col == year)

    # prefer newest if duplicates
    return q.order_by(desc(ts_col), desc(ReferencePrice.id)).first()

def check_for_deals():
    session = SessionLocal()
    try:
        # Pull latest Facebook listings that have price + year (and optionally km)
        # You can adjust filters if you want to include dealership listings in deal alerts too.
        listings = session.execute(
            select(CarListing).where(
                CarListing.source == "Facebook Marketplace",
                CarListing.price.isnot(None),
                CarListing.year.isnot(None)
            )
        ).scalars().all()

        created_logs = 0
        created_manual = 0
        skipped = 0

        for car in listings:
            # Skip if we already processed this listing
            if _already_logged(session, car.id) or _already_in_manual_review(session, car.id):
                skipped += 1
                continue

            ref = _find_reference(session, car.make, car.model)
            if not ref:
                # No reference available
                skipped += 1
                continue

            baseline = _pick_baseline(ref)
            if not baseline or baseline <= 0:
                skipped += 1
                continue

            price = car.price
            if not price or price <= 0:
                skipped += 1
                continue

            # percent below baseline (positive number means cheaper than baseline)
            pct_below = (baseline - price) / baseline * 100.0

            # Ignore tiny deviations / or above-baseline prices
            if pct_below < TIER_GOOD_MIN:
                skipped += 1
                continue

            # Prepare a human friendly summary
            summary = (
                f"{car.make or ''} {car.model or ''} ({car.year or ''}) — "
                f"Price: {price:,} ISK vs baseline {baseline:,} ISK "
                f"({pct_below:.1f}% below)"
            ).strip()

            # Route by severity
            if pct_below >= TIER_SUSPECT_MIN:
                # ≥70% off baseline => likely data error or too-good-to-be-true.
                if not _already_in_manual_review(session, car.id):
                    session.add(ManualReview(
                        listing_id=car.id,
                        reason=">=70% below baseline",
                        details=summary,
                        created_at=datetime.utcnow()
                    ))
                    created_manual += 1
                # Do not notify via DealLog per your rule
                continue

            # Otherwise, log as deal (good/strong)
            if pct_below <= TIER_GOOD_MAX:
                severity = "deal"  # 15–30%
            elif TIER_STRONG_MIN <= pct_below <= TIER_STRONG_MAX:
                severity = "strong_deal"  # 31–69%
            else:
                # In case thresholds change or float math hits edge; treat as strong_deal
                severity = "strong_deal"

            if not _already_logged(session, car.id):
                session.add(DealLog(
                    listing_id=car.id,
                    make=car.make,
                    model=car.model,
                    year=car.year,
                    price=price,
                    baseline_price=baseline,
                    percent_below=round(pct_below, 2),
                    severity=severity,
                    created_at=datetime.utcnow(),
                    notes=summary
                ))
                created_logs += 1

        session.commit()
        print(f"Deal check complete. New logs: {created_logs}, Manual reviews: {created_manual}, Skipped: {skipped}")

    finally:
        session.close()
