# utils/normalizer.py
import re
import unicodedata

# Maps normalized names back to proper display format
DISPLAY_NAMES = {
    # Tesla models
    "models": "Model S",
    "model3": "Model 3",
    "modely": "Model Y",
    "modelx": "Model X",
    
    # Other EVs and hybrids
    "etron": "e-tron",
    "ipace": "I-PACE",
    "chr": "C-HR",
    "id3": "ID.3",
    "id4": "ID.4",
    "id5": "ID.5",
    
    # Base models
    "santafe": "Santa Fe",
    "grandcherokee": "Grand Cherokee",
    
    # Special cases
    "ioniq 5": "IONIQ 5",  # Already properly spaced
}

ALIASES = {
    # Brand aliases
    "vw": "volkswagen",
    "volks wagen": "volkswagen",
    "merc": "mercedes-benz",
    "merc benz": "mercedes-benz",
    "mb": "mercedes-benz",
    "bmw": "bmw",
    "toy": "toyota",
    "land rover": "land-rover",
    "lr": "land-rover",
    "rangerover": "range-rover",
    "range rover": "range-rover",
    "chevy": "chevrolet",
    "skoda": "škoda",
    
    # Model aliases - normalize common model names
    "model s": "models",
    "model y": "modely",
    "model 3": "model3",
    "model x": "modelx",
    "c-hr": "chr",
    "i-pace": "ipace",
    "e-tron": "etron",
    "q4 e-tron": "q4",
    "id.3": "id3",
    "id.4": "id4",
    "id.5": "id5",
    "glc 300": "glc",
    "gle 350": "gle",
    "gla 250": "gla",
    "cla 250": "cla",
    "proace verso": "proace",
    "proace city": "proace",
    "santa fe": "santafe",
    "grand cherokee": "grandcherokee",
    "model s 100kwh": "models",
    "ioniq5": "ioniq 5",
    "enyaq sportback": "enyaq",
    "q4 sportback": "q4",
    "q8 sportback": "q8",
}

DROP_TOKENS = {
    # Trim levels and editions
    "premium", "comfort", "sport", "gt", "gti", "gtd", "amg", "rs", 
    "m-sport", "msport", "s-line", "sline", "limited", "ultimate",
    "elegance", "advanced", "luxury", "exclusive", "standard", "prestige",
    "platinum", "style", "active", "classic", "progressive", "intense",
    "calligraphy", "cosmo", "adventure", "altitude", "acenta", "tekna",
    "optimum", "elegant", "inscription", "trailhawk", "rubicon", "sahara",
    "denali", "at4", "at4x",
    
    # Powertrains and drivetrains
    "xdrive", "4matic", "quattro", "4motion",
    "plug-in", "plugin", "phev", "hybrid", "electric", "ev", "e-tech",
    "4x4", "awd", "fwd", "rwd", "4xe", "iperformance", "recharge",
    
    # Engine types/codes
    "tsi", "tdi", "dci", "cdti", "hdi", "bluehdi", "d4", "d5", "tfsi",
    "gte", "gtx", "etsi", "mhev", "bluetec", "kwh", "73kw", "51kw",
    "75kw", "64kwh", "39kwh", "100kwh", "505h",
    
    # Body styles and features
    "long", "range", "l1", "l2", "l3", "h1", "h2", "h3", "l1h1", "l2h2",
    "l3h2", "h2l1", "edition", "package", "pack", "plus", "panorama",
    "langur", "extended", "crew", "double", "doublecab", "crewmax",
    "dual", "mega", "kasten", "manna", "angur", "vsk",
    
    # Common suffixes
    "base", "core", "pro", "performance", "power", "perfo",
    
    # Specific model variants to normalize (excluding Tesla model letters)
    "e", "se", "le", "gx", "vx", "ex",
    "r-dynamic", "bi-tone", "two-tone",
    
    # Sizes/numbers that shouldn't affect base model
    "300", "350", "250", "200", "150", "500", "320", "330", "530",
    "616", "818", "519", "460", "37-tommu"
}

def _strip_weird_spaces(s: str) -> str:
    s = s.replace("\xa0", " ").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", s).strip()

def _nfkc_lower(s: str) -> str:
    return unicodedata.normalize("NFKC", s).lower()

def normalize_make(make: str | None) -> str | None:
    if not make:
        return None
    m = _nfkc_lower(_strip_weird_spaces(make))
    m = re.sub(r"[^a-záéíóúýþæö0-9\- ]", "", m)
    m = ALIASES.get(m, m)
    return m or None

def normalize_model(model: str | None) -> str | None:
    if not model:
        return None
    m = _nfkc_lower(_strip_weird_spaces(model))
    m = re.sub(r"[^a-záéíóúýþæö0-9\-\/ ]", " ", m)
    m = re.sub(r"\s+", " ", m).strip()
    return m or None

def get_display_name(model: str | None) -> str | None:
    """Get the user-friendly display name for a normalized model name"""
    if not model:
        return None
    
    # Look up in our display names map first
    display_name = DISPLAY_NAMES.get(model)
    if display_name:
        return display_name
        
    # If no specific display name, capitalize words
    return ' '.join(word.capitalize() for word in model.split())

def model_base(model: str | None) -> str | None:
    """Get the base model name by removing trim levels and normalizing common variants"""
    m = normalize_model(model)
    if not m:
        return None
        
    # First check for known model aliases
    for alias, normalized in ALIASES.items():
        if m.startswith(alias):
            return normalized
            
    # Split into tokens and filter out modifiers
    tokens = []
    for t in m.split():
        # Skip known modifiers and trim levels
        if t in DROP_TOKENS:
            continue
        # Skip pure numbers and short alphanumeric codes
        if re.fullmatch(r"[0-9]+", t):
            continue
        if re.fullmatch(r"[0-9]{1,2}[a-z]", t) and len(t) <= 3:
            continue
        tokens.append(t)
            
    if not tokens:
        return None
        
    # For most cases, first token is the base model
    result = tokens[0]
    
    # Special handling for Tesla models
    if len(tokens) > 1 and tokens[0] == "model":
        model_variant = tokens[1].lower()
        if model_variant in {"s", "3", "x", "y"}:
            # Handle "model s", "model 3", etc.
            return f"model{model_variant}"
        
    # Return None for Tesla's bare "model" to prevent it from being used
    if len(tokens) == 1 and tokens[0] == "model":
        return None
    
    return result

def normalize_title(title: str | None) -> str | None:
    if not title:
        return None
    t = _nfkc_lower(_strip_weird_spaces(title))
    t = re.sub(r"(kr\.?|isk)\s*[\d\.\s]+", "", t)
    t = re.sub(r"[\u2600-\u27BF\uE000-\uF8FF]+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t or None

def normalize_make_model(make: str | None, model: str | None):
    nm = normalize_make(make)
    nmod = normalize_model(model)
    return nm, nmod, model_base(nmod)
