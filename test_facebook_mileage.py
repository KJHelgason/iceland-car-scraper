"""
Test Facebook mileage extraction with real examples
"""
from scrapers.facebook_scraper import extract_mileage, extract_structured_data

print("="*80)
print("TEST 1: KIA Sportage - Icelandic 'Ekinn aðeins'")
print("="*80)

title1 = "Mjög vel með farinn og lítið keyrður KIA Sportage GT-Line 2017"
price1 = "ISK3,490,000"
description1 = """Details
Condition
Used - like new
Ekinn aðeins 99.000km 
Ný og lítið notuð sumardekk og nagladekk fylgja með!
Nýskoðaður án athugasemda hjá Frumherja og því 26 miði!
Nýtt í bremsum allan hringinn!
Sjálfskiptur
Dísel
Fjórhjóladrif
Nýskráning 09/2017 
Næsta skoðun 2026"""

# Test regex extraction
regex_result1 = extract_mileage(description1)
print(f"\n📊 Regex extraction: {regex_result1}")

# Test full AI extraction
print("\n🤖 Full AI extraction:")
ai_result1 = extract_structured_data(title1, price1, description1)
print(f"Result: {ai_result1}")
if ai_result1:
    print(f"  - Make: {ai_result1.get('make')}")
    print(f"  - Model: {ai_result1.get('model')}")
    print(f"  - Year: {ai_result1.get('year')}")
    print(f"  - Price: {ai_result1.get('price')}")
    print(f"  - Mileage: {ai_result1.get('mileage')} km")
else:
    print("  ❌ AI returned empty (classified as non-vehicle?)")

print("\n" + "="*80)
print("TEST 2: Mazda 3 - English with emoji")
print("="*80)

title2 = "Mazda 3 2017"
price2 = "ISK2,190,000"
description2 = """Details
Condition
Used - Good
Mazda 3 – 05/2017 – Automatic – Petrol

📅 Year: May 2017
📍 Mileage: 99,503 km
⛽ Fuel: Bensin
⚙️ Transmission: Automatic
🧰 Recently replaced: Oil, shields, and brake pads

💬 Price is negotiable"""

# Test regex extraction
regex_result2 = extract_mileage(description2)
print(f"\n📊 Regex extraction: {regex_result2}")

# Test full AI extraction
print("\n🤖 Full AI extraction:")
ai_result2 = extract_structured_data(title2, price2, description2)
print(f"Result: {ai_result2}")
if ai_result2:
    print(f"  - Make: {ai_result2.get('make')}")
    print(f"  - Model: {ai_result2.get('model')}")
    print(f"  - Year: {ai_result2.get('year')}")
    print(f"  - Price: {ai_result2.get('price')}")
    print(f"  - Mileage: {ai_result2.get('mileage')} km")
else:
    print("  ❌ AI returned empty (classified as non-vehicle?)")

print("\n" + "="*80)
print("SUMMARY")
print("="*80)
print(f"Test 1 - Regex: {'✅ PASS' if regex_result1 == 99000 else '❌ FAIL'} (expected 99000, got {regex_result1})")
print(f"Test 1 - AI: {'✅ PASS' if ai_result1 and ai_result1.get('mileage') == 99000 else '❌ FAIL'} (expected 99000, got {ai_result1.get('mileage') if ai_result1 else 'None'})")
print(f"Test 2 - Regex: {'✅ PASS' if regex_result2 == 99503 else '❌ FAIL'} (expected 99503, got {regex_result2})")
print(f"Test 2 - AI: {'✅ PASS' if ai_result2 and ai_result2.get('mileage') == 99503 else '❌ FAIL'} (expected 99503, got {ai_result2.get('mileage') if ai_result2 else 'None'})")
