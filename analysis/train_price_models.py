# analysis/train_price_models.py
import os
import math
import json
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from db.db_setup import SessionLocal
from db.models import CarListing, PriceModel
from utils.normalizer import normalize_make_model, get_display_name

# ---- Config ----
MIN_SAMPLES_MODEL = 5 #15 # Lowered since we're using base models
MIN_SAMPLES_MAKE = 5  #25 # Lowered accordingly

HALF_LIFE_DAYS = 60.0
LAMBDA = math.log(2) / HALF_LIFE_DAYS  # recency decay
RIDGE_ALPHA = 1.0  # small regularization

CURRENT_YEAR = datetime.now(timezone.utc).year


# ---- Helpers ----
def clean_rows(rows):
    """Keep rows with sane fields and trim price/km outliers by IQR inside the set."""
    if not rows:
        return []

    # Drop obviously bad
    rows = [r for r in rows if r.price and r.year and r.kilometers is not None]
    rows = [r for r in rows if 1990 <= r.year <= CURRENT_YEAR and r.kilometers >= 0 and r.price > 0]

    if len(rows) < 5:
        return rows

    # IQR by price (use 5/95 pct to be robust on smallish sets)
    prices = np.array([r.price for r in rows], dtype=float)
    q1, q3 = np.percentile(prices, [5, 95])
    rows = [r for r in rows if q1 <= r.price <= q3]

    # IQR by km
    kms = np.array([r.kilometers for r in rows], dtype=float)
    k1, k3 = np.percentile(kms, [5, 95])
    rows = [r for r in rows if k1 <= r.kilometers <= k3]

    return rows


def make_design(rows):
    """Return X, y, weights for ridge: price ~ 1 + age + logkm + age*logkm"""
    ages = np.array([CURRENT_YEAR - r.year for r in rows], dtype=float)
    logkm = np.log1p(np.array([r.kilometers for r in rows], dtype=float))
    age_logkm = ages * logkm

    X = np.column_stack([np.ones(len(rows)), ages, logkm, age_logkm])
    y = np.array([r.price for r in rows], dtype=float)

    # recency weights
    now = datetime.now(timezone.utc)
    days = np.array(
        [
            (now - (r.scraped_at.replace(tzinfo=timezone.utc) if r.scraped_at and r.scraped_at.tzinfo is None else (r.scraped_at or now))).days
            for r in rows
        ],
        dtype=float,
    )
    w = np.exp(-LAMBDA * np.clip(days, 0, 3650))  # cap at ~10 years
    return X, y, w


def weighted_ridge(X, y, w, alpha):
    """Closed-form (X' W X + alpha I)^-1 X' W y"""
    W = np.diag(w)
    XtW = X.T @ W
    A = XtW @ X
    I = np.eye(X.shape[1])
    I[0, 0] = 0.0  # don't regularize intercept
    A_reg = A + alpha * I
    b = XtW @ y
    coef = np.linalg.pinv(A_reg) @ b
    yhat = X @ coef
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2)) or 1.0
    r2 = 1.0 - ss_res / ss_tot
    rmse = math.sqrt(ss_res / max(len(y) - X.shape[1], 1))
    return coef, r2, rmse


def upsert_model(session: Session, tier: str, make_norm: str | None, model_base_s: str | None,
                 coef, n, r2, rmse):
    coef_json = {
        "intercept": float(coef[0]),
        "beta_age": float(coef[1]),
        "beta_logkm": float(coef[2]),
        "beta_age_logkm": float(coef[3]),
    }
    
    # Get display name for the model
    display_name = None
    if model_base_s:
        display_name = get_display_name(model_base_s)
    elif make_norm:
        # For make-level models, capitalize the make
        display_name = make_norm.capitalize()
    else:
        # For global model
        display_name = "Global"
    
    # Delete existing row for this (tier, make_norm, model_base) bucket (acts as upsert)
    session.execute(
        delete(PriceModel).where(
            PriceModel.tier == tier,
            (PriceModel.make_norm.is_(None) if make_norm is None else PriceModel.make_norm == make_norm),
            (PriceModel.model_base.is_(None) if model_base_s is None else PriceModel.model_base == model_base_s),
        )
    )
    session.add(
        PriceModel(
            tier=tier,
            make_norm=make_norm,
            model_base=model_base_s,
            display_name=display_name,
            coef_json=json.dumps(coef_json),
            n_samples=n,
            r2=r2,
            rmse=rmse,
            trained_at=datetime.now(timezone.utc),
        )
    )


def train_for_group(session: Session, rows, tier, make_norm=None, model_base_s=None):
    rows = clean_rows(rows)
    if len(rows) < 8:  # need enough after trimming to be stable
        return False, "too_few_after_trim"

    X, y, w = make_design(rows)
    try:
        coef, r2, rmse = weighted_ridge(X, y, w, RIDGE_ALPHA)
    except Exception:
        return False, "ridge_fail"

    upsert_model(session, tier, make_norm, model_base_s, coef, len(rows), r2, rmse)
    return True, {"n": len(rows), "r2": r2, "rmse": rmse}


# ---- Public entrypoint (for main.py) ----
def train_and_store(min_samples_model: int = MIN_SAMPLES_MODEL, min_samples_make: int = MIN_SAMPLES_MAKE):
    """
    Trains & stores models at three tiers: model, make, global.
    Returns (updated_count, skipped_count).
    """
    session = SessionLocal()
    updated = 0
    skipped = 0
    try:
        # Pull everything once
        cars = (
            session.execute(
                select(CarListing).where(
                    CarListing.price.isnot(None),
                    CarListing.year.isnot(None),
                    CarListing.kilometers.isnot(None),
                )
            )
            .scalars()
            .all()
        )

        # normalize into buckets
        enriched = []
        for c in cars:
            nm, nmod, mbase = normalize_make_model(c.make, c.model)
            enriched.append((c, nm, mbase))

        # Global set
        global_rows = [c for (c, nm, mb) in enriched]

        # Make buckets
        by_make = {}
        # Model-base buckets
        by_model = {}

        for c, nm, mb in enriched:
            if nm:
                by_make.setdefault(nm, []).append(c)
            if nm and mb:
                by_model.setdefault((nm, mb), []).append(c)

        # Train MODEL tier
        for (mk, mb), rows in by_model.items():
            # Skip standalone "model" for Tesla since it should always be model{s,3,x,y}
            if mk == "tesla" and mb == "model":
                continue
                
            if len(rows) >= min_samples_model:
                ok, _ = train_for_group(session, rows, "model", mk, mb)
                if ok:
                    updated += 1
                else:
                    skipped += 1

        # Train MAKE tier
        for mk, rows in by_make.items():
            if len(rows) >= min_samples_make:
                ok, _ = train_for_group(session, rows, "make", mk, None)
                if ok:
                    updated += 1
                else:
                    skipped += 1

        # Train GLOBAL tier (always one)
        ok, _ = train_for_group(session, global_rows, "global", None, None)
        if ok:
            updated += 1
        else:
            skipped += 1

        session.commit()
        return updated, skipped
    finally:
        session.close()


# ---- CLI entrypoint ----
if __name__ == "__main__":
    # Ensure project root on PYTHONPATH when calling directly
    import sys, pathlib
    sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
    up, sk = train_and_store()
    print(f"Trained & stored models. Updated: {up}, Skipped: {sk}")
