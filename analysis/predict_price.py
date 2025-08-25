# analysis/predict_price.py
import os
import json
import math
from dataclasses import dataclass
from typing import Optional, Tuple
from datetime import datetime, timezone

import numpy as np

# Ensure project root on path for direct execution
if __name__ == "__main__" and __package__ is None:
    import sys, pathlib
    sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from db.db_setup import SessionLocal
from db.models import PriceModel
from utils.normalizer import normalize_make_model

CURRENT_YEAR = datetime.now(timezone.utc).year

@dataclass
class Coefs:
    intercept: float
    beta_age: float
    beta_logkm: float
    beta_age_logkm: float

def _load_bucket(session, tier: str, make_norm: Optional[str], model_base: Optional[str]) -> Optional[Tuple[Coefs, float, str]]:
    """
    Returns (coefs, rmse, bucket_key) for the requested bucket or None.
    """
    q = session.query(PriceModel).filter(PriceModel.tier == tier)
    if make_norm is None:
        q = q.filter(PriceModel.make_norm.is_(None))
    else:
        q = q.filter(PriceModel.make_norm == make_norm)
    if model_base is None:
        q = q.filter(PriceModel.model_base.is_(None))
    else:
        q = q.filter(PriceModel.model_base == model_base)

    pm = q.order_by(PriceModel.trained_at.desc()).first()
    if not pm:
        return None

    coefs_dict = json.loads(pm.coef_json)
    coefs = Coefs(
        intercept=coefs_dict["intercept"],
        beta_age=coefs_dict["beta_age"],
        beta_logkm=coefs_dict["beta_logkm"],
        beta_age_logkm=coefs_dict["beta_age_logkm"],
    )
    bucket_key = f"{tier}:{pm.make_norm or '-'}::{pm.model_base or '-'}"
    return coefs, float(pm.rmse or 0.0), bucket_key

def _best_bucket(session, make: Optional[str], model: Optional[str]) -> Tuple[Optional[Tuple[Coefs, float, str]], str]:
    """
    Tries (model) → (make) → (global). Returns ((coefs, rmse, bucket_key), tier_used).
    """
    nm, nmod, mb = normalize_make_model(make, model)

    # 1) model tier
    if nm and mb:
        res = _load_bucket(session, "model", nm, mb)
        if res:
            return res, "model"

    # 2) make tier
    if nm:
        res = _load_bucket(session, "make", nm, None)
        if res:
            return res, "make"

    # 3) global tier
    res = _load_bucket(session, "global", None, None)
    if res:
        return res, "global"

    return None, "none"

def _features(year: int, kilometers: int):
    # guardrails
    year = int(year)
    kilometers = max(0, int(kilometers))
    age = max(0.0, float(CURRENT_YEAR - year))
    logkm = float(np.log1p(kilometers))
    age_logkm = age * logkm
    return age, logkm, age_logkm

def _predict_from_coefs(coefs: Coefs, year: int, kilometers: int) -> float:
    age, logkm, age_logkm = _features(year, kilometers)
    y = (
        coefs.intercept
        + coefs.beta_age * age
        + coefs.beta_logkm * logkm
        + coefs.beta_age_logkm * age_logkm
    )
    return float(y)

def predict_price(make: Optional[str], model: Optional[str], year: int, kilometers: int, session=None):
    """
    Returns:
      {
        'predicted_price': int | None,
        'tier_used': 'model' | 'make' | 'global' | 'none',
        'bucket': 'tier:make::model_base',
        'rmse': float | None,
        'band': {'low': int, 'high': int} | None
      }
    """
    close_session = False
    if session is None:
        session = SessionLocal()
        close_session = True

    try:
        picked, tier = _best_bucket(session, make, model)
        if not picked:
            return {
                "predicted_price": None,
                "tier_used": "none",
                "bucket": None,
                "rmse": None,
                "band": None,
            }

        coefs, rmse, bucket_key = picked
        pred = _predict_from_coefs(coefs, year, kilometers)
        pred_int = int(round(max(0, pred)))
        band = {
            "low": int(round(max(0, pred - rmse))),
            "high": int(round(max(0, pred + rmse))),
        }
        return {
            "predicted_price": pred_int,
            "tier_used": tier,
            "bucket": bucket_key,
            "rmse": rmse,
            "band": band,
        }
    finally:
        if close_session:
            session.close()

# ---------------- CLI ----------------
def _cli():
    import argparse
    p = argparse.ArgumentParser(description="Predict fair car price using trained price_models.")
    p.add_argument("--make", required=False, help="e.g. volkswagen")
    p.add_argument("--model", required=False, help='e.g. "golf gti"')
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--km", type=int, required=True, help="kilometers")
    args = p.parse_args()

    res = predict_price(args.make, args.model, args.year, args.km)
    print("Prediction:")
    for k, v in res.items():
        print(f"  {k}: {v}")

if __name__ == "__main__":
    _cli()
