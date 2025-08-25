# db/models.py
from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    BigInteger,
    ForeignKey,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


# --- (Legacy) Per-model coefficients table (you already had this) ---
class ModelPriceCoeffs(Base):
    __tablename__ = "model_price_coeffs"
    __table_args__ = (UniqueConstraint("make", "model", name="uq_modelprice_make_model"),)

    id = Column(Integer, primary_key=True, index=True)
    make = Column(String, nullable=False)
    model = Column(String, nullable=False)

    n_samples = Column(Integer, nullable=False)
    coef_intercept = Column(Float, nullable=False)
    coef_year = Column(Float, nullable=False)
    coef_log_km = Column(Float, nullable=False)

    rmse_pct = Column(Float)   # RMSE as percentage in price space
    r2 = Column(Float)         # R^2 in log-price space

    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


# --- Core scraped listing ---
class CarListing(Base):
    __tablename__ = "car_listings"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String)
    title = Column(String)
    make = Column(String)
    model = Column(String)
    year = Column(Integer)
    price = Column(BigInteger)
    kilometers = Column(BigInteger)
    url = Column(String, unique=True)
    description = Column(String)
    scraped_at = Column(DateTime)


# --- Reference prices (used by deal checker) ---
# Aggregate stats by normalized make + model_base (nullable to allow make-only rows).
class ReferencePrice(Base):
    __tablename__ = "reference_prices"

    id = Column(Integer, primary_key=True, index=True)
    make = Column(String, index=True, nullable=False)          # normalized make
    model_base = Column(String, index=True, nullable=True)     # normalized "base" model (trimless)
    min_price = Column(BigInteger)
    median_price = Column(BigInteger)
    max_price = Column(BigInteger)
    sample_size = Column(Integer)
    last_updated = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("make", "model_base", name="uq_reference_make_modelbase"),
    )


# --- Price models (statistical models we trained) ---
class PriceModel(Base):
    __tablename__ = "price_models"

    id = Column(Integer, primary_key=True)
    tier = Column(String, index=True)            # "model" | "make" | "global"
    make_norm = Column(String, index=True, nullable=True)
    model_base = Column(String, index=True, nullable=True)
    display_name = Column(String, nullable=True)  # User-friendly display name for the model

    # coefficients for: intercept + beta_age + beta_logkm + beta_age_logkm
    coef_json = Column(Text)  # JSON string: {"intercept":..., "beta_age":..., "beta_logkm":..., "beta_age_logkm":...}

    n_samples = Column(Integer)
    r2 = Column(Float)
    rmse = Column(Float)
    trained_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("tier", "make_norm", "model_base", name="uq_price_models_bucket"),
    )


# --- Deal logging (for alerts under 15–30%, etc.) ---
class DealLog(Base):
    __tablename__ = "deal_logs"

    id = Column(Integer, primary_key=True, index=True)
    listing_id = Column(Integer, ForeignKey("car_listings.id", ondelete="CASCADE"), unique=True, index=True)
    make = Column(String)
    model = Column(String)
    year = Column(Integer)
    price = Column(BigInteger)
    baseline_price = Column(BigInteger)  # the baseline used (e.g., median or midpoint of min/max)
    percent_below = Column(Float)        # e.g., 27.5 means 27.5% below baseline
    severity = Column(String)            # "deal" | "strong_deal"
    notes = Column(Text)                 # optional summary
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    listing = relationship("CarListing", lazy="joined")


# --- Manual review queue (>=70% below baseline, likely outliers) ---
class ManualReview(Base):
    __tablename__ = "manual_reviews"

    id = Column(Integer, primary_key=True, index=True)
    listing_id = Column(Integer, ForeignKey("car_listings.id", ondelete="CASCADE"), unique=True, index=True)
    reason = Column(String)   # e.g., ">=70% below baseline"
    details = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    listing = relationship("CarListing", lazy="joined")
