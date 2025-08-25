from sqlalchemy import select
from db.db_setup import SessionLocal
from db.models import CarListing
from utils.normalizer import normalize_make_model

def analyze_model_distribution():
    session = SessionLocal()
    try:
        # Get all listings
        print("Fetching car listings...")
        cars = session.execute(select(CarListing)).scalars().all()
        
        # Group by make and model
        model_counts = {}
        for car in cars:
            if not car.make or not car.model:
                continue
                
            make_norm, _, model_base = normalize_make_model(car.make, car.model)
            if not make_norm or not model_base:
                continue
                
            key = (make_norm, model_base)
            if key not in model_counts:
                model_counts[key] = {
                    'total': 0,
                    'valid': 0,
                    'sample': []
                }
            
            info = model_counts[key]
            info['total'] += 1
            
            # Check basic validity
            if (car.price and car.year and car.kilometers is not None and 
                car.year >= 1990 and car.kilometers >= 0 and car.price > 0):
                info['valid'] += 1
                info['sample'].append({
                    'price': car.price,
                    'km': car.kilometers,
                    'year': car.year
                })
        
        # Print results
        print("\nModel Distribution Analysis:")
        print("-" * 80)
        
        # Sort by total count descending
        sorted_models = sorted(model_counts.items(), key=lambda x: x[1]['total'], reverse=True)
        
        for (make, model), info in sorted_models:
            if info['total'] >= 5:  # Only show models with at least 5 entries
                print(f"\n{make} {model}:")
                print(f"  Total entries: {info['total']}")
                print(f"  Valid entries: {info['valid']}")
                
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
                    
                    if clean_count < 25:
                        print("  ** Not enough clean samples for model training (need 25) **")
    
    finally:
        session.close()

if __name__ == "__main__":
    import numpy as np
    analyze_model_distribution()
