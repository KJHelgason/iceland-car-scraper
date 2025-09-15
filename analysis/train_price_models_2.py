# analysis/train_price_models.py
import math
import json
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, List

import numpy as np
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from db.db_setup import SessionLocal
from db.models import CarListing, PriceModel
from utils.normalizer import normalize_make_model, get_display_name, pretty_make

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────

# Sample thresholds
MIN_SAMPLES_MODEL       = 5     # pooled (make+model) minimum after trimming
MIN_SAMPLES_MAKE        = 5     # pooled (make) minimum after trimming
MIN_SAMPLES_MODEL_YEAR  = 12    # per-year (make+model+year) minimum after trimming

# Recency weighting
HALF_LIFE_DAYS = 60.0
LAMBDA = math.log(2) / HALF_LIFE_DAYS

# Robust regression (IRLS) config
IRLS_STEPS = 3
HUBER_C    = 1.345  # ~95% efficient under normal residuals

# Ridge base (scaled down as effective N grows)
RIDGE_ALPHA_BASE = 1.0

# Variation guards to avoid unstable fits
MIN_AGE_STD       = 0.25   # years, for pooled models
MIN_LOGKM_STD     = 0.10   # log-km, for pooled models
MIN_LOGKM_STD_YR  = 0.10   # log-km, for per-year models (age constant)

CURRENT_YEAR = datetime.now(timezone.utc).year


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def clean_rows(rows: List[CarListing]) -> List[CarListing]:
    """
    Keep rows with sane fields and trim price/km outliers by IQR inside the set.
    """
    if not rows:
        return []

    # Drop obviously bad
    rows = [r for r in rows if r.price and r.year and r.kilometers is not None]
    rows = [r for r in rows if 1990 <= int(r.year) <= CURRENT_YEAR and r.kilometers >= 0 and r.price > 0]

    if len(rows) < 5:
        return rows

    # IQR-like trim by price (use 5/95 pct to be robust on smallish sets)
    prices = np.array([r.price for r in rows], dtype=float)
    q1, q3 = np.percentile(prices, [5, 95])
    rows = [r for r in rows if q1 <= r.price <= q3]

    if len(rows) < 5:
        return rows

    # IQR-like trim by km
    kms = np.array([r.kilometers for r in rows], dtype=float)
    k1, k3 = np.percentile(kms, [5, 95])
    rows = [r for r in rows if k1 <= r.kilometers <= k3]

    return rows


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: Optional[datetime], fallback: datetime) -> datetime:
    if dt is None:
        return fallback
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def recency_weights(rows: List[CarListing]) -> np.ndarray:
    """
    Exponential recency weights with half-life HALF_LIFE_DAYS.
    """
    now = _now_utc()
    # age in days: now - scraped_at
    days = []
    for r in rows:
        ts = _as_aware(getattr(r, "scraped_at", None), now)
        delta_days = (now - ts).total_seconds() / 86400.0
        days.append(max(0.0, min(delta_days, 3650.0)))  # clamp 0..10 years
    days = np.array(days, dtype=float)
    return np.exp(-LAMBDA * days)


def make_design_pooled(rows: List[CarListing]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Pooled model design: price ~ 1 + age + logkm + age*logkm
    Returns X, y, w_recency, ages, logkm
    """
    ages = np.array([CURRENT_YEAR - int(r.year) for r in rows], dtype=float)
    logkm = np.log1p(np.array([r.kilometers for r in rows], dtype=float))
    age_logkm = ages * logkm

    X = np.column_stack([np.ones(len(rows)), ages, logkm, age_logkm])
    y = np.array([r.price for r in rows], dtype=float)
    w = recency_weights(rows)
    return X, y, w, ages, logkm


def make_design_single_year(rows: List[CarListing]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Per-year model design: price ~ 1 + logkm  (age constant within a given year)
    Returns X, y, w_recency, logkm
    """
    logkm = np.log1p(np.array([r.kilometers for r in rows], dtype=float))
    X = np.column_stack([np.ones(len(rows)), logkm])
    y = np.array([r.price for r in rows], dtype=float)
    w = recency_weights(rows)
    return X, y, w, logkm


def kish_effective_n(w: np.ndarray) -> float:
    """Kish effective sample size for weights."""
    s1 = float(np.sum(w))
    s2 = float(np.sum(w ** 2))
    return (s1 * s1) / s2 if s2 > 0 else 0.0


def huber_weights(residuals: np.ndarray, scale: float, c: float = HUBER_C) -> np.ndarray:
    """
    Huber IRLS weights. residuals are raw (y - yhat).
    scale is robust scale (e.g., 1.4826 * MAD).
    """
    if scale <= 1e-9:
        return np.ones_like(residuals)
    r = residuals / (scale * c)
    w = np.ones_like(r)
    mask = np.abs(r) > 1.0
    w[mask] = 1.0 / np.clip(np.abs(r[mask]), 1e-9, None)  # c*scale/|res| up to the normalization factor
    return np.clip(w, 0.0, 1.0)


def weighted_ridge(X: np.ndarray, y: np.ndarray, w: np.ndarray, alpha: float) -> np.ndarray:
    """
    Closed-form ridge: (X' W X + alpha I)^-1 X' W y
    No regularization on intercept.
    """
    W = np.diag(w)
    XtW = X.T @ W
    A = XtW @ X
    I = np.eye(X.shape[1])
    I[0, 0] = 0.0  # don't regularize intercept
    A_reg = A + alpha * I
    b = XtW @ y
    coef = np.linalg.pinv(A_reg) @ b
    return coef


def weighted_metrics(X: np.ndarray, y: np.ndarray, w: np.ndarray, coef: np.ndarray) -> Tuple[float, float, float]:
    """
    Weighted R² and RMSE with Kish effective N for df.
    """
    yhat = X @ coef
    w = np.asarray(w, dtype=float)
    w_sum = float(np.sum(w)) if np.sum(w) > 0 else 1.0

    y_bar = float(np.sum(w * y) / w_sum)

    ss_res = float(np.sum(w * (y - yhat) ** 2))
    ss_tot = float(np.sum(w * (y - y_bar) ** 2))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    p = X.shape[1]
    n_eff = kish_effective_n(w)
    dof = max(n_eff - p, 1.0)
    rmse = math.sqrt(ss_res / dof)

    return r2, rmse, n_eff


def robust_ridge(X: np.ndarray, y: np.ndarray, w_recency: np.ndarray) -> Tuple[np.ndarray, float, float, np.ndarray]:
    """
    IRLS with Huber weights on top of recency weights.
    Returns coef, r2, rmse, final_weights.
    """
    w = np.asarray(w_recency, dtype=float).copy()
    coef = None

    for _ in range(IRLS_STEPS):
        n_eff = max(kish_effective_n(w), 1.0)
        # dynamic ridge: more data -> less regularization
        alpha = RIDGE_ALPHA_BASE * (4.0 / max(n_eff, 4.0))
        coef = weighted_ridge(X, y, w, alpha)
        yhat = X @ coef
        resid = y - yhat

        # robust scale via MAD
        med = float(np.median(resid))
        mad = float(np.median(np.abs(resid - med))) if len(resid) > 0 else 0.0
        scale = 1.4826 * mad if mad > 0 else (np.std(resid) or 1.0)

        w_rob = huber_weights(resid, scale, HUBER_C)
        # Combine recency and robust weights
        w = w_recency * w_rob
        # Normalize to max=1 for numerical stability
        w = w / (np.max(w) or 1.0)

    r2, rmse, _ = weighted_metrics(X, y, w, coef)
    return coef, r2, rmse, w


# ──────────────────────────────────────────────────────────────────────────────
# Upsert
# ──────────────────────────────────────────────────────────────────────────────

def upsert_model(
    session: Session,
    tier: str,
    make_norm: Optional[str],
    model_base_s: Optional[str],
    coef: np.ndarray,
    n: int,
    r2: float,
    rmse: float,
    year: Optional[int] = None,
):
    coef_json = {
        "intercept": float(coef[0]),
        "beta_age": float(coef[1]) if len(coef) > 2 else 0.0,
        "beta_logkm": float(coef[2] if len(coef) > 2 else coef[1]),
        "beta_age_logkm": float(coef[3]) if len(coef) > 3 else 0.0,
    }

    # Display strings:
    # - display_name: user-facing model name (no year appended anymore)
    # - display_make: user-facing make name with proper casing/hyphens acronyms
    if model_base_s:
        display_name = get_display_name(model_base_s) or model_base_s
    elif make_norm:
        # fall back to pretty make if we have no model_base
        display_name = pretty_make(make_norm) or (make_norm.capitalize() if make_norm else "Global")
    else:
        display_name = "Global"

    display_make = pretty_make(make_norm) if make_norm else None

    # Delete existing row for this bucket (tier, make_norm, model_base, year)
    session.execute(
        delete(PriceModel).where(
            PriceModel.tier == tier,
            (PriceModel.make_norm.is_(None) if make_norm is None else PriceModel.make_norm == make_norm),
            (PriceModel.model_base.is_(None) if model_base_s is None else PriceModel.model_base == model_base_s),
            (PriceModel.year.is_(None) if year is None else PriceModel.year == year),
        )
    )

    session.add(
        PriceModel(
            tier=tier,
            make_norm=make_norm,
            model_base=model_base_s,
            display_name=display_name,   # stays without year
            display_make=display_make,   # NEW: pretty make for frontend
            coef_json=json.dumps(coef_json),
            n_samples=n,
            r2=r2,
            rmse=rmse,
            trained_at=datetime.now(timezone.utc),
            year=year,                   # per-year when provided
        )
    )


# ──────────────────────────────────────────────────────────────────────────────
# Trainers
# ──────────────────────────────────────────────────────────────────────────────

def train_for_group_pooled(session, rows, tier, make_norm=None, model_base_s=None):
    rows = clean_rows(rows)
    if len(rows) < 8:
        return False, "too_few_after_trim"

    X_full, y, w_recency, ages, logkm = make_design_pooled(rows)

    age_std = float(np.std(ages))
    km_std  = float(np.std(logkm))

    # Helper to fit any X and write out coef_json in full 4-term form
    def _fit_and_upsert(X, map_to_full):
        coef, r2, rmse, _ = robust_ridge(X, y, w_recency)
        # map coef vector into full [intercept, beta_age, beta_logkm, beta_age_logkm]
        b0, b1, b2, b3 = map_to_full(coef)
        upsert_model(
            session,
            tier,
            make_norm,
            model_base_s,
            np.array([b0, b1, b2, b3], dtype=float),
            len(rows),
            r2,
            rmse,
            year=None
        )
        return True, {"n": len(rows), "r2": r2, "rmse": rmse}

    try:
        if age_std >= MIN_AGE_STD and km_std >= MIN_LOGKM_STD:
            # Full model: 1 + age + logkm + age*logkm
            return _fit_and_upsert(
                X_full,
                lambda c: (c[0], c[1], c[2], c[3])
            )
        elif km_std >= MIN_LOGKM_STD:
            # Reduced: 1 + logkm
            X = np.column_stack([np.ones(len(rows)), logkm])
            return _fit_and_upsert(
                X,
                lambda c: (c[0], 0.0, c[1], 0.0)
            )
        elif age_std >= MIN_AGE_STD:
            # Reduced: 1 + age
            X = np.column_stack([np.ones(len(rows)), ages])
            return _fit_and_upsert(
                X,
                lambda c: (c[0], c[1], 0.0, 0.0)
            )
        else:
            # Intercept-only fallback
            X = np.ones((len(rows), 1))
            return _fit_and_upsert(
                X,
                lambda c: (c[0], 0.0, 0.0, 0.0)
            )
    except Exception:
        return False, "ridge_fail"


def train_for_group_single_year(
    session: Session,
    rows: List[CarListing],
    make_norm: str,
    model_base_s: str,
    year: int
) -> Tuple[bool, object]:
    """
    Fit per-year model: price ~ 1 + logkm   (age constant within year)
    Stored as tier='model_year', with PriceModel.year = year
    """
    rows = clean_rows(rows)
    if len(rows) < MIN_SAMPLES_MODEL_YEAR:
        return False, "too_few_year_rows"

    X, y, w_recency, logkm = make_design_single_year(rows)

    # Variation guard
    if np.std(logkm) < MIN_LOGKM_STD_YR:
        return False, "insufficient_km_variation"

    try:
        coef, r2, rmse, _ = robust_ridge(X, y, w_recency)
    except Exception:
        return False, "ridge_fail"

    upsert_model(session, "model_year", make_norm, model_base_s, coef, len(rows), r2, rmse, year=year)
    return True, {"n": len(rows), "r2": r2, "rmse": rmse}


# ──────────────────────────────────────────────────────────────────────────────
# Public entrypoint
# ──────────────────────────────────────────────────────────────────────────────

def train_and_store(
    min_samples_model: int = MIN_SAMPLES_MODEL,
    min_samples_make: int = MIN_SAMPLES_MAKE,
    min_samples_model_year: int = MIN_SAMPLES_MODEL_YEAR,
):
    """
    Trains & stores models at four tiers now:
      - model_year (per make+model+year, when enough data)
      - model (pooled across years for make+model)
      - make  (pooled)
      - global (pooled)

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

        # Normalize into buckets
        enriched: List[Tuple[CarListing, Optional[str], Optional[str]]] = []
        for c in cars:
            nm, _nmod, mbase = normalize_make_model(c.make, c.model)
            enriched.append((c, nm, mbase))

        # Global set
        global_rows = [c for (c, _nm, _mb) in enriched]

        # Make buckets and Model-base buckets
        by_make: Dict[str, List[CarListing]] = {}
        by_model: Dict[Tuple[str, str], List[CarListing]] = {}

        for c, nm, mb in enriched:
            if nm:
                by_make.setdefault(nm, []).append(c)
            if nm and mb:
                by_model.setdefault((nm, mb), []).append(c)

        # ── Train per-year (model_year) for each (make, model_base) ───────────
        for (mk, mb), rows in by_model.items():
            # (Optional) special case: skip bare "model" for Tesla
            if mk == "tesla" and mb == "model":
                continue

            # group by calendar year
            by_year: Dict[int, List[CarListing]] = {}
            for r in rows:
                if r.year:
                    by_year.setdefault(int(r.year), []).append(r)

            for yr, yr_rows in by_year.items():
                if len(yr_rows) >= min_samples_model_year:
                    ok, _ = train_for_group_single_year(session, yr_rows, mk, mb, yr)
                    if ok:
                        updated += 1
                    else:
                        skipped += 1

        # ── Train pooled MODEL tier (across years) ────────────────────────────
        for (mk, mb), rows in by_model.items():
            if mk == "tesla" and mb == "model":
                continue

            if len(rows) >= min_samples_model:
                ok, _ = train_for_group_pooled(session, rows, "model", mk, mb)
                if ok:
                    updated += 1
                else:
                    skipped += 1

        # ── Train pooled MAKE tier ────────────────────────────────────────────
        for mk, rows in by_make.items():
            if len(rows) >= min_samples_make:
                ok, _ = train_for_group_pooled(session, rows, "make", mk, None)
                if ok:
                    updated += 1
                else:
                    skipped += 1

        # ── Train pooled GLOBAL tier (always one) ─────────────────────────────
        ok, _ = train_for_group_pooled(session, global_rows, "global", None, None)
        if ok:
            updated += 1
        else:
            skipped += 1

        session.commit()
        return updated, skipped

    finally:
        session.close()


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Ensure project root on PYTHONPATH when calling directly
    import sys, pathlib
    sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
    up, sk = train_and_store()
    print(f"Trained & stored models. Updated: {up}, Skipped: {sk}")
