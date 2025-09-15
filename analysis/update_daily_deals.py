# analysis/update_daily_deals.py
import math
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from db.db_setup import SessionLocal
from db.models import CarListing, PriceModel, DailyDeal
from utils.normalizer import normalize_make_model  # uses your trained buckets

# -------- Config ----------
TOP_N = 10
MIN_PRICE = 50_000
LOOKBACK_HOURS = 24      # primary window (matches your UI default)
EXTENDED_DAYS = 7        # extended fallback
CHEAPEST_MULTIPLIER = 3  # fetch more than needed before ranking

CURRENT_YEAR = datetime.now(timezone.utc).year


# -------- Helpers (match your TS logic) ----------

def _to_model_base_for_search(model: str) -> str:
    """
    Very close to your TS toModelBase/canonicalizeModelForSearch fallback:
    take first cleaned token as a broad 'model_base'.
    """
    if not model:
        return ""
    cleaned = re.sub(r"[^a-z0-9\s-]", " ", model.lower()).strip()
    parts = cleaned.split()
    return parts[0] if parts else ""


def _safe_coef(raw) -> Dict[str, float]:
    if isinstance(raw, str):
        import json
        obj = json.loads(raw)
    else:
        obj = raw or {}
    return {
        "intercept": float(obj.get("intercept", 0.0)),
        "beta_age": float(obj.get("beta_age", 0.0)),
        "beta_logkm": float(obj.get("beta_logkm", 0.0)),
        "beta_age_logkm": float(obj.get("beta_age_logkm", 0.0)),
    }


def _estimate_price(coef_json, year: Optional[int], km: Optional[int]) -> float:
    c = _safe_coef(coef_json)
    age = (CURRENT_YEAR - int(year)) if year else 0
    logkm = math.log(1 + max(0, km or 0))
    return (
        c["intercept"]
        + c["beta_age"] * age
        + c["beta_logkm"] * logkm
        + c["beta_age_logkm"] * (age * logkm)
    )


# -------- PriceModel index (one DB pass; then dict lookups) ----------

class ModelIndex:
    def __init__(self, rows: List[PriceModel]):
        self.model_map: Dict[Tuple[str, str], PriceModel] = {}
        self.make_map: Dict[str, PriceModel] = {}
        self.global_model: Optional[PriceModel] = None

        for pm in rows:
            tier = getattr(pm, "tier", None)
            mk = getattr(pm, "make_norm", None)
            mb = getattr(pm, "model_base", None)
            if tier == "model" and mk and mb:
                self.model_map[(mk, mb)] = pm
            elif tier == "make" and mk and not mb:
                self.make_map[mk] = pm
            elif tier == "global" and not mk and not mb:
                self.global_model = pm

    def find_best(self, make: str, model: str) -> Optional[PriceModel]:
        nm, _nmod, mb = normalize_make_model(make, model)
        if not mb and model:
            mb = _to_model_base_for_search(model)
        return (
            self.model_map.get((nm or "", mb or ""))
            or (self.make_map.get(nm or "") if nm else None)
            or self.global_model
        )


# -------- Core selection logic (mirrors your TS) ----------

def _fetch_candidates(session: Session, since_iso: str, limit: int) -> List[CarListing]:
    q = (
        session.execute(
            select(CarListing)
            .where(
                CarListing.price.isnot(None),
                CarListing.price > MIN_PRICE,
                CarListing.scraped_at.isnot(None),
                CarListing.scraped_at >= since_iso,
            )
            .order_by(CarListing.scraped_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return q


def _fetch_cheapest(session: Session, limit: int) -> List[CarListing]:
    q = (
        session.execute(
            select(CarListing)
            .where(
                CarListing.price.isnot(None),
                CarListing.price > MIN_PRICE,
            )
            .order_by(CarListing.price.asc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return q


def _enrich_and_rank(rows: List[CarListing], idx: ModelIndex) -> List[dict]:
    enriched = []
    for r in rows:
        # basic sanity for model lookup
        if not (r and isinstance(r.make, str) and isinstance(r.model, str)):
            continue
        if r.kilometers is None or r.price is None:
            continue

        pm = idx.find_best(r.make, r.model)
        if not pm or not getattr(pm, "coef_json", None):
            continue

        est = _estimate_price(pm.coef_json, r.year, r.kilometers)
        est = max(est, (r.price or 0) * 0.1)  # tiny floor

        diff = est - (r.price or 0)
        pct = (diff / est) * 100 if est > 0 else 0.0
        rmse = float(getattr(pm, "rmse", 0.0) or 0.0)
        n = int(getattr(pm, "n_samples", 0) or 0)

        z = (diff / rmse) if rmse > 1e-9 else 0.0
        tscore = z * math.sqrt(n if n > 0 else 1.0)
        rank = tscore if math.isfinite(tscore) else pct

        enriched.append(
            {
                "row": r,
                "estimated_price": est,
                "pct_below": pct,
                "model_rmse": rmse or None,
                "model_n": n or None,
                "model_key": f"{getattr(pm, 'make_norm', 'global')}|{getattr(pm, 'model_base', 'base')}",
                "rank_score": rank,
            }
        )

    # same sort as your TS (rank desc, then pct desc)
    enriched.sort(key=lambda d: (-(d["rank_score"] or float("-inf")), -(d["pct_below"] or float("-inf"))))
    return enriched


def _load_price_models(session: Session) -> ModelIndex:
    pms = session.execute(select(PriceModel)).scalars().all()
    return ModelIndex(pms)


def update_daily_deals(
    top_n: int = TOP_N,
    lookback_hours: int = LOOKBACK_HOURS,
    extended_days: int = EXTENDED_DAYS,
    cheapest_multiplier: int = CHEAPEST_MULTIPLIER,
) -> Tuple[int, int]:
    """
    Returns (inserted_count, scanned_count)
    """
    session = SessionLocal()
    inserted = 0
    scanned = 0
    try:
        idx = _load_price_models(session)

        all_enriched: List[dict] = []

        # Stage 1: last X hours (grab a bit more than needed, like frontend)
        since_primary = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()
        primary_rows = _fetch_candidates(session, since_primary, top_n * cheapest_multiplier)
        scanned += len(primary_rows)
        all_enriched.extend(_enrich_and_rank(primary_rows, idx))

        # Stage 2: extend to last 7 days if needed
        if len(all_enriched) < top_n:
            since_ext = (datetime.now(timezone.utc) - timedelta(days=extended_days)).isoformat()
            ext_rows = _fetch_candidates(session, since_ext, 600)  # same as your TS
            scanned += len(ext_rows)
            all_enriched.extend(_enrich_and_rank(ext_rows, idx))

        # Stage 3: cheapest fallback (still requires a model)
        if len(all_enriched) < top_n:
            cheap_rows = _fetch_cheapest(session, top_n * cheapest_multiplier)
            scanned += len(cheap_rows)
            all_enriched.extend(_enrich_and_rank(cheap_rows, idx))

        # Deduplicate by listing id (keep best-ranked per id)
        best_by_id: Dict[int, dict] = {}
        for d in all_enriched:
            r: CarListing = d["row"]
            prev = best_by_id.get(r.id)
            if (prev is None) or ((d["rank_score"] or -1e18) > (prev["rank_score"] or -1e18)):
                best_by_id[r.id] = d

        deduped = list(best_by_id.values())

        # STRICT VALIDATION: require fully present fields
        valid = []
        for d in deduped:
            r: CarListing = d["row"]
            if not (r.make and r.model):
                continue
            if r.year is None or r.kilometers is None or r.price is None:
                continue
            valid.append(d)

        # Sort again (rank desc, then pct desc), then slice to top_n
        valid.sort(key=lambda x: (-(x["rank_score"] or float("-inf")), -(x["pct_below"] or float("-inf"))))
        top = valid[:top_n]

        # Replace daily_deals atomically
        session.execute(delete(DailyDeal))
        now = datetime.now(timezone.utc)
        for d in top:
            r: CarListing = d["row"]
            session.add(
                DailyDeal(
                    listing_id=r.id,
                    source=r.source,
                    title=r.title,
                    make=r.make,
                    model=r.model,
                    year=r.year,
                    price=r.price,
                    kilometers=r.kilometers,
                    url=r.url,
                    description=r.description,
                    scraped_at=r.scraped_at,
                    estimated_price=float(d["estimated_price"]),
                    pct_below=float(d["pct_below"]),
                    model_rmse=(float(d["model_rmse"]) if d["model_rmse"] is not None else None),
                    model_n=(int(d["model_n"]) if d["model_n"] is not None else None),
                    model_key=d["model_key"],
                    rank_score=float(d["rank_score"]) if d["rank_score"] is not None else None,
                    inserted_at=now,
                    computed_at=now,  # <-- ensure NOT NULL satisfied
                )
            )
        session.commit()
        inserted = len(top)
        return inserted, scanned
    finally:
        session.close()


if __name__ == "__main__":
    # Ensure project root on PYTHONPATH when calling directly
    import sys, pathlib
    sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

    ins, scn = update_daily_deals()
    print(f"Daily deals updated. Inserted: {ins}, Scanned candidates: {scn}")
