from sqlalchemy import delete
from db.db_setup import SessionLocal
from db.models import PriceModel
from train_price_models_3 import train_and_store

def retrain_all():
    """Clear existing price models and retrain with new normalization rules"""
    session = SessionLocal()
    try:
        print("Clearing existing price models...")
        # Delete all existing price models
        session.execute(delete(PriceModel))
        session.commit()
        print("Existing models cleared.")
    finally:
        session.close()

    print("\nRetraining models with new normalization rules...")
    updated, skipped = train_and_store()
    print(f"Training complete. Models updated: {updated}, Skipped: {skipped}")

if __name__ == "__main__":
    retrain_all()
