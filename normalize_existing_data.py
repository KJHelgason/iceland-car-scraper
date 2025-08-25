# normalize_existing_data.py
import argparse
import math
from datetime import datetime, timezone
from typing import Optional, Tuple

# Ensure project root is on path when running directly
import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parent))

from db.db_setup import SessionLocal
from db.models import CarListing
from utils.normalizer import normalize_make_model


def infer_make_model_from_title(title: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not title:
        return None, None
    parts = title.strip().split()
    if not parts:
        return None, None
    make = parts[0]
    model = " ".join(parts[1:]) if len(parts) > 1 else None
    return make, model


def normalize_all(dry_run: bool = False, limit: Optional[int] = None, batch_size: int = 200):
    session = SessionLocal()
    changed = 0
    errors = 0

    try:
        # Pull IDs first to avoid named cursor issues
        q = session.query(CarListing.id).order_by(CarListing.id.asc())
        if limit:
            q = q.limit(limit)
        id_rows = q.all()
        ids = [row[0] for row in id_rows]
        total = len(ids)
        if total == 0:
            print("No rows to process.")
            return

        print(f"Will normalize {total} rows "
              f"(dry_run={dry_run}, batch_size={batch_size}).")

        # Process in chunks
        for start in range(0, total, batch_size):
            end = min(start + batch_size, total)
            chunk_ids = ids[start:end]
            cars = (
                session.query(CarListing)
                .filter(CarListing.id.in_(chunk_ids))
                .order_by(CarListing.id.asc())
                .all()
            )

            for car in cars:
                try:
                    orig_make, orig_model = car.make, car.model
                    make, model = orig_make, orig_model

                    # Fill missing from title if necessary
                    if not make or not model:
                        t_make, t_model = infer_make_model_from_title(car.title)
                        make = make or t_make
                        model = model or t_model

                    # Normalize
                    n_make, n_model, model_base = normalize_make_model(make, model)

                    # Decide what we actually store:
                    # - make: canonical (n_make) if available
                    # - model: prefer model_base (stripped/clean), else n_model, else original
                    new_make = n_make or orig_make
                    new_model = model_base or n_model or orig_model

                    # Apply only if changed
                    row_changed = False
                    if new_make and new_make != car.make:
                        car.make = new_make
                        row_changed = True
                    if new_model and new_model != car.model:
                        car.model = new_model
                        row_changed = True

                    if row_changed:
                        changed += 1

                except Exception as e:
                    errors += 1
                    print(f"[WARN] Failed to normalize id={car.id}: {e}")

            # Commit per-batch unless dry run
            if not dry_run:
                session.commit()
                print(f"[{datetime.now(timezone.utc).isoformat()}] "
                      f"Committed batch up to row {end} "
                      f"(changed so far: {changed}, errors: {errors})")
            else:
                print(f"[DRY RUN] Processed batch up to row {end} "
                      f"(would change so far: {changed}, errors: {errors})")

        print(f"Done. Scanned {total} rows. "
              f"{'Would update' if dry_run else 'Updated'} {changed} rows. Errors {errors}.")

    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description="Normalize existing CarListing make/model values.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write changes.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of rows.")
    parser.add_argument("--batch-size", type=int, default=200, help="Rows per commit batch.")
    args = parser.parse_args()

    normalize_all(dry_run=args.dry_run, limit=args.limit, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
