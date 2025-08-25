from sqlalchemy import select
from db.db_setup import SessionLocal
from db.models import CarListing
from utils.normalizer import normalize_make_model

def analyze_model_distribution():
    session = SessionLocal()
    try:
        print("Fetching car listings...")
        cars = session.execute(select(CarListing)).scalars().all()
        
        # Group by make and base model
        model_counts = {}
        make_counts = {}
        
        for car in cars:
            if not car.make or not car.model:
                continue
                
            make_norm, full_model, base_model = normalize_make_model(car.make, car.model)
            if not make_norm or not base_model:
                continue
                
            # Track make-level stats
            if make_norm not in make_counts:
                make_counts[make_norm] = {
                    'total': 0,
                    'valid': 0
                }
            make_info = make_counts[make_norm]
            make_info['total'] += 1
            
            # Track model-level stats
            key = (make_norm, base_model)
            if key not in model_counts:
                model_counts[key] = {
                    'total': 0,
                    'valid': 0,
                    'variants': set(),  # Track different variants of this base model
                    'sample': []
                }
            
            info = model_counts[key]
            info['total'] += 1
            if full_model:
                info['variants'].add(full_model)
            
            # Check if entry has valid data for training
            if (car.price and car.year and car.kilometers is not None and 
                car.year >= 1990 and car.kilometers >= 0 and car.price > 0):
                info['valid'] += 1
                make_info['valid'] += 1
                info['sample'].append({
                    'price': car.price,
                    'km': car.kilometers,
                    'year': car.year
                })
        
        # Print results
        print("\nMake-Level Statistics:")
        print("-" * 80)
        for make, info in sorted(make_counts.items()):
            if info['total'] >= 10:
                print(f"\n{make}:")
                print(f"  Total entries: {info['total']}")
                print(f"  Valid entries: {info['valid']}")
                if info['valid'] < 25:
                    print("  ** Not enough samples for make-level model (need 25) **")
        
        print("\nModel-Level Statistics:")
        print("-" * 80)
        for (make, model), info in sorted(model_counts.items(), key=lambda x: (-x[1]['total'], x[0])):
            if info['total'] >= 5:  # Show models with at least 5 entries
                print(f"\n{make} {model}:")
                print(f"  Total entries: {info['total']}")
                print(f"  Valid entries: {info['valid']}")
                
                if info['variants']:
                    print("  Variants found:")
                    for v in sorted(info['variants']):
                        print(f"    - {v}")
                
                if info['valid'] >= 5:
                    import numpy as np
                    # Calculate price stats for valid entries
                    prices = [c['price'] for c in info['sample']]
                    avg_price = sum(prices) / len(prices)
                    
                    # Calculate IQR filtered count
                    q5, q95 = np.percentile(prices, [5, 95])
                    clean_prices = [p for p in prices if q5 <= p <= q95]
                    clean_count = len(clean_prices)
                    
                    print(f"  Clean entries (after outlier removal): {clean_count}")
                    print(f"  Price range: {min(prices):,} - {max(prices):,}")
                    print(f"  Average price: {avg_price:,.0f}")
                    
                    if clean_count < 15:
                        print("  ** Not enough clean samples for model training (need 15) **")

if __name__ == "__main__":
    analyze_model_distribution()
