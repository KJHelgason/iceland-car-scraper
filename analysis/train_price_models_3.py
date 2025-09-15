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

MIN_SAMPLES_MODEL       = 5     # pooled (make+model) minimum after trimming
MIN_SAMPLES_MAKE        = 5     # pooled (make) minimum after trimming
MIN_SAMPLES_MODEL_YEAR  = 12    # per-year (make+model+year) minimum after trimming

HALF_LIFE_DAYS = 60.0
LAMBDA = math.log(2) / HALF_LIFE_DAYS

IRLS_STEPS = 3
HUBER_C    = 1.345

RIDGE_ALPHA_BASE = 1.0

MIN_AGE_STD       = 0.25
MIN_LOGKM_STD     = 0.10
MIN_LOGKM_STD_YR  = 0.10

CURRENT_YEAR = datetime.now(timezone.utc).year

# Family pooling rules: add rows to extra “family” buckets (in addition to their specific model)
# For your request: all Mercedes-Benz models whose normalized model_base starts with "e"
FAMILY_RULES: Dict[Tuple[str, str], Dict] = {
    # key = (make_norm, family_base) -> rule
    ("mercedes-benz", "e"): {
        "match": lambda model_base: isinstance(model_base, str) and model_base.startswith("e"),
        # You can exclude something by adding an "exclude": lambda mb: ...
    },
    # You can add more families later, e.g. ("audi","a"): {"match": lambda mb: mb.startswith("a")}
}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def clean_rows(rows: List[CarListing]) -> List[CarListing]:
    if not rows:
        return []
    rows = [r for r in rows if r.price and r.year and r.kilometers is not None]
    rows = [r for r in rows if 1990 <= int(r.year) <= CURRENT_YEAR and r.kilometers >= 0 and r.price > 0]
    if len(rows) < 5:
        return rows

    prices = np.array([r.price for r in rows], dtype=float)
    q1, q3 = np.percentile(prices, [5, 95])
    rows = [r for r in rows if q1 <= r.price <= q3]
    if len(rows) < 5:
        return rows

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
    now = _now_utc()
    days = []
    for r in rows:
        ts = _as_aware(getattr(r, "scraped_at", None), now)
        delta_days = (now - ts).total_seconds() / 86400.0
        days.append(max(0.0, min(delta_days, 3650.0)))
    days = np.array(days, dtype=float)
    return np.exp(-LAMBDA * days)

def make_design_pooled(rows: List[CarListing]):
    ages = np.array([CURRENT_YEAR - int(r.year) for r in rows], dtype=float)
    logkm = np.log1p(np.array([r.kilometers for r in rows], dtype=float))
    age_logkm = ages * logkm
    X = np.column_stack([np.ones(len(rows)), ages, logkm, age_logkm])
    y = np.array([r.price for r in rows], dtype=float)
    w = recency_weights(rows)
    return X, y, w, ages, logkm

def make_design_single_year(rows: List[CarListing]):
    logkm = np.log1p(np.array([r.kilometers for r in rows], dtype=float))
    X = np.column_stack([np.ones(len(rows)), logkm])
    y = np.array([r.price for r in rows], dtype=float)
    w = recency_weights(rows)
    return X, y, w, logkm

def kish_effective_n(w: np.ndarray) -> float:
    s1 = float(np.sum(w))
    s2 = float(np.sum(w ** 2))
    return (s1 * s1) / s2 if s2 > 0 else 0.0

def huber_weights(residuals: np.ndarray, scale: float, c: float = HUBER_C) -> np.ndarray:
    if scale <= 1e-9:
        return np.ones_like(residuals)
    r = residuals / (scale * c)
    w = np.ones_like(r)
    mask = np.abs(r) > 1.0
    w[mask] = 1.0 / np.clip(np.abs(r[mask]), 1e-9, None)
    return np.clip(w, 0.0, 1.0)

def weighted_ridge(X: np.ndarray, y: np.ndarray, w: np.ndarray, alpha: float) -> np.ndarray:
    W = np.diag(w)
    XtW = X.T @ W
    A = XtW @ X
    I = np.eye(X.shape[1]); I[0, 0] = 0.0
    A_reg = A + alpha * I
    b = XtW @ y
    coef = np.linalg.pinv(A_reg) @ b
    return coef

def weighted_metrics(X: np.ndarray, y: np.ndarray, w: np.ndarray, coef: np.ndarray):
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

def robust_ridge(X: np.ndarray, y: np.ndarray, w_recency: np.ndarray):
    w = np.asarray(w_recency, dtype=float).copy()
    coef = None
    for _ in range(IRLS_STEPS):
        n_eff = max(kish_effective_n(w), 1.0)
        alpha = RIDGE_ALPHA_BASE * (4.0 / max(n_eff, 4.0))
        coef = weighted_ridge(X, y, w, alpha)
        yhat = X @ coef
        resid = y - yhat
        med = float(np.median(resid))
        mad = float(np.median(np.abs(resid - med))) if len(resid) > 0 else 0.0
        scale = 1.4826 * mad if mad > 0 else (np.std(resid) or 1.0)
        w_rob = huber_weights(resid, scale, HUBER_C)
        w = w_recency * w_rob
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

    if model_base_s:
        display_name = get_display_name(model_base_s) or model_base_s
    elif make_norm:
        display_name = pretty_make(make_norm) or (make_norm.capitalize() if make_norm else "Global")
    else:
        display_name = "Global"

    display_make = pretty_make(make_norm) if make_norm else None

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
            display_name=display_name,
            display_make=display_make,
            coef_json=json.dumps(coef_json),
            n_samples=n,
            r2=r2,
            rmse=rmse,
            trained_at=datetime.now(timezone.utc),
            year=year,
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

    def _fit_and_upsert(X, map_to_full):
        coef, r2, rmse, _ = robust_ridge(X, y, w_recency)
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
            return _fit_and_upsert(X_full, lambda c: (c[0], c[1], c[2], c[3]))
        elif km_std >= MIN_LOGKM_STD:
            X = np.column_stack([np.ones(len(rows)), logkm])
            return _fit_and_upsert(X, lambda c: (c[0], 0.0, c[1], 0.0))
        elif age_std >= MIN_AGE_STD:
            X = np.column_stack([np.ones(len(rows)), ages])
            return _fit_and_upsert(X, lambda c: (c[0], c[1], 0.0, 0.0))
        else:
            X = np.ones((len(rows), 1))
            return _fit_and_upsert(X, lambda c: (c[0], 0.0, 0.0, 0.0))
    except Exception:
        return False, "ridge_fail"

def train_for_group_single_year(
    session: Session,
    rows: List[CarListing],
    make_norm: str,
    model_base_s: str,
    year: int
):
    rows = clean_rows(rows)
    if len(rows) < MIN_SAMPLES_MODEL_YEAR:
        return False, "too_few_year_rows"

    X, y, w_recency, logkm = make_design_single_year(rows)
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
    Trains & stores models at four tiers:
      - model_year (per make+model+year)
      - model (pooled make+model)
      - make  (pooled)
      - global (pooled)
    Also adds “family” pooled buckets per FAMILY_RULES (e.g., Mercedes ‘e’).
    Returns (updated_count, skipped_count).
    """
    session = SessionLocal()
    updated = 0
    skipped = 0

    try:
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

        # Normalize
        enriched: List[Tuple[CarListing, Optional[str], Optional[str]]] = []
        for c in cars:
            nm, _nmod, mbase = normalize_make_model(c.make, c.model)
            enriched.append((c, nm, mbase))

        global_rows = [c for (c, _nm, _mb) in enriched]

        by_make: Dict[str, List[CarListing]] = {}
        by_model: Dict[Tuple[str, str], List[CarListing]] = {}
        by_family: Dict[Tuple[str, str], List[CarListing]] = {}

        for c, nm, mb in enriched:
            if nm:
                by_make.setdefault(nm, []).append(c)
            if nm and mb:
                by_model.setdefault((nm, mb), []).append(c)

                # Family routing (in addition to specific model)
                for (fam_make, fam_base), rule in FAMILY_RULES.items():
                    if nm == fam_make and rule.get("match", lambda _: False)(mb):
                        by_family.setdefault((fam_make, fam_base), []).append(c)

        # Per-year model for each (make, model_base)
        for (mk, mb), rows in by_model.items():
            if mk == "tesla" and mb == "model":
                continue
            by_year: Dict[int, List[CarListing]] = {}
            for r in rows:
                if r.year:
                    by_year.setdefault(int(r.year), []).append(r)
            for yr, yr_rows in by_year.items():
                if len(yr_rows) >= min_samples_model_year:
                    ok, _ = train_for_group_single_year(session, yr_rows, mk, mb, yr)
                    if ok: updated += 1
                    else:  skipped += 1

        # Pooled MODEL tier (specific)
        for (mk, mb), rows in by_model.items():
            if mk == "tesla" and mb == "model":
                continue
            if len(rows) >= min_samples_model:
                ok, _ = train_for_group_pooled(session, rows, "model", mk, mb)
                if ok: updated += 1
                else:  skipped += 1

        # Pooled FAMILY tier (e.g., Mercedes ‘e’)
        # We store these as regular MODEL tier with model_base equal to the family key ("e"),
        # which is fine because we still keep specific model buckets separately.
        for (mk, fam_base), rows in by_family.items():
            if len(rows) >= min_samples_model:
                ok, _ = train_for_group_pooled(session, rows, "model", mk, fam_base)
                if ok: updated += 1
                else:  skipped += 1

        # MAKE tier
        for mk, rows in by_make.items():
            if len(rows) >= min_samples_make:
                ok, _ = train_for_group_pooled(session, rows, "make", mk, None)
                if ok: updated += 1
                else:  skipped += 1

        # GLOBAL tier
        ok, _ = train_for_group_pooled(session, global_rows, "global", None, None)
        if ok: updated += 1
        else:  skipped += 1

        session.commit()
        return updated, skipped
    finally:
        session.close()


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, pathlib
    sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
    up, sk = train_and_store()
    print(f"Trained & stored models. Updated: {up}, Skipped: {sk}")
