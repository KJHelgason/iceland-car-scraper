# db/models.py
from datetime import datetime
from sqlalchemy.sql import func
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
    Boolean,
    Index,
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
    is_active = Column(Boolean, nullable=False, default=True)
    image_url = Column(String, nullable=True)
    display_make = Column(String, nullable=True)  # Pretty formatted make: "Land Rover"
    display_name = Column(String, nullable=True)  # Pretty formatted model: "Range Rover Sport"


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


class DailyDeal(Base):
    __tablename__ = "daily_deals"

    id = Column(Integer, primary_key=True, index=True)

    # reference to the original listing
    listing_id = Column(Integer, ForeignKey("car_listings.id"), nullable=False)

    # core listing fields (match car_listings)
    source = Column(String)
    title = Column(String)
    make = Column(String, nullable=False)
    model = Column(String, nullable=False)
    year = Column(Integer, nullable=False)
    price = Column(BigInteger, nullable=False)
    kilometers = Column(BigInteger, nullable=False)
    url = Column(String)
    description = Column(Text)
    scraped_at = Column(DateTime(timezone=True))

    # deal metrics (these are what update_daily_deals.py writes)
    estimated_price = Column(Float, nullable=False)
    pct_below = Column(Float, nullable=False)          # percentage below estimate
    model_rmse = Column(Float)                          # nullable
    model_n = Column(Integer)                           # nullable
    model_key = Column(String)                          # nullable
    rank_score = Column(Float)                          # nullable

    # bookkeeping
    inserted_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),  # server-side default is handy
    )
    computed_at = Column(
        DateTime(timezone=True),
        nullable=False,             # script sets this explicitly
    )

# --- Price models (statistical models we trained) ---
class PriceModel(Base):
    __tablename__ = "price_models"
    id = Column(Integer, primary_key=True)

    # tiers: 'model_year', 'model', 'make', 'global'
    tier = Column(String, nullable=False)

    make_norm = Column(String, nullable=True, index=True)
    model_base = Column(String, nullable=True, index=True)

    # Per-year models store the calendar year here (nullable for pooled tiers)
    year = Column(Integer, nullable=True, index=True)

    # Display-friendly fields
    display_make = Column(String, nullable=True)   # NEW: "Land Rover"
    display_name = Column(String, nullable=True)   # Already exists — keep, but fix logic later

    coef_json = Column(Text, nullable=False)

    n_samples = Column(Integer, nullable=False, default=0)
    r2 = Column(Float, nullable=False, default=0.0)
    rmse = Column(Float, nullable=False, default=0.0)

    trained_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # ensure uniqueness for the bucket including year
        UniqueConstraint('tier', 'make_norm', 'model_base', 'year', name='price_models_unique'),
        # helpful composite indexes
        Index('ix_price_models_bucket', 'tier', 'make_norm', 'model_base'),
        Index('ix_price_models_year_bucket', 'tier', 'make_norm', 'model_base', 'year'),
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
