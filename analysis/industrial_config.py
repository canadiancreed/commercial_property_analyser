"""
Loaders for the industrial size-band multipliers and the (heuristic) component
premiums, plus the size-tier resolution logic.

Both coefficient sets live in JSON so every number is tunable and carries a
source field, rather than being hardcoded magic constants. Module-level defaults
mirror the shipped JSON so the analyser still works if a file is missing.
"""
import json
import os

_SIZE_BANDS_PATH = "json/industrial_size_bands.json"
_PREMIUMS_PATH   = "json/industrial_premiums.json"

# Defaults mirror the shipped JSON (see json/industrial_size_bands.json).
_DEFAULT_BANDS = [
    {"label": "small-bay", "sqft_min": 0,      "sqft_max": 25000,  "multiplier": 1.08, "confidence": "MED"},
    {"label": "mid-size",  "sqft_min": 25000,  "sqft_max": 100000, "multiplier": 0.95, "confidence": "MED"},
    {"label": "big-box",   "sqft_min": 100000, "sqft_max": None,   "multiplier": 1.00, "confidence": "LOW"},
]

_DEFAULT_OVERRIDES = {
    "office_ratio_small_bay":  0.30,
    "doors_per_10k_small_bay": 1.5,
}

_DEFAULT_PREMIUMS = {
    "clear_height_premium_per_ft": {"value": 0.02, "base_ft": 18, "cap_pct": 0.20},
    "office_premium_ratio":        {"value": 1.40},
    "yard_rate_ratio":             {"value": 0.15},
    "dock_door_annual":            {"value": 1200},
    "drive_in_door_annual":        {"value": 600},
}


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_size_bands() -> list:
    data = _read(_SIZE_BANDS_PATH)
    if data and isinstance(data.get("bands"), list) and data["bands"]:
        return data["bands"]
    return _DEFAULT_BANDS


def _override_thresholds() -> dict:
    data = _read(_SIZE_BANDS_PATH) or {}
    meta = data.get("_meta", {})
    return {
        "office_ratio_small_bay":  meta.get("office_ratio_small_bay",  _DEFAULT_OVERRIDES["office_ratio_small_bay"]),
        "doors_per_10k_small_bay": meta.get("doors_per_10k_small_bay", _DEFAULT_OVERRIDES["doors_per_10k_small_bay"]),
    }


def load_premiums() -> dict:
    data = _read(_PREMIUMS_PATH)
    out = {k: dict(v) for k, v in _DEFAULT_PREMIUMS.items()}
    if data:
        for k in out:
            if isinstance(data.get(k), dict) and "value" in data[k]:
                out[k].update(data[k])
    return out


def resolve_size_band(total_sq_ft, dock_doors=0, drive_in_doors=0, office_sqft=0) -> tuple:
    """
    Returns (label, multiplier, downgrade).

    The band is chosen by total_sq_ft. The relationship is non-monotonic
    (Colliers: small-bay highest, big-box second, mid-size trough), so the
    multipliers are not a straight decline.

    `downgrade` is True when a large footprint shows small-bay signals (high
    door density or high office ratio) — i.e. it is likely multi-tenant
    small-bay product whose footprint is misleading. In that case it is
    reclassified toward small-bay and the caller should drop confidence a level.
    """
    bands = load_size_bands()
    sqft  = total_sq_ft or 0

    band = None
    for b in bands:
        lo = b.get("sqft_min", 0) or 0
        hi = b.get("sqft_max")
        if sqft >= lo and (hi is None or sqft < hi):
            band = b
            break
    if band is None:
        band = bands[-1]

    label = band["label"]
    mult  = band.get("multiplier", 1.0)

    downgrade = False
    if label != "small-bay" and sqft > 0:
        thr           = _override_thresholds()
        doors         = (dock_doors or 0) + (drive_in_doors or 0)
        doors_per_10k = doors / (sqft / 10000.0)
        office_ratio  = (office_sqft or 0) / sqft
        if doors_per_10k >= thr["doors_per_10k_small_bay"] or office_ratio >= thr["office_ratio_small_bay"]:
            small = next((b for b in bands if b["label"] == "small-bay"), None)
            if small is not None:
                label = small["label"]
                mult  = small.get("multiplier", 1.0)
            downgrade = True

    return label, mult, downgrade


_CONFIDENCE_ORDER = ["LOW", "MED", "HIGH"]


def _downgrade_level(level: str) -> str:
    try:
        i = _CONFIDENCE_ORDER.index(level)
    except ValueError:
        return "LOW"
    return _CONFIDENCE_ORDER[max(0, i - 1)]


def industrial_confidence(rate_source, is_detailed: bool, size_downgrade: bool = False) -> str:
    """
    Combine the two quality axes into HIGH / MED / LOW.

      rate_source : 'Src' (sourced market rate) or 'Est' (estimate) or None.
      is_detailed : building details were entered.
      size_downgrade : footprint/tenancy signals conflict (knocks down one level).

    Matrix:
      Src + details  -> HIGH
      Src + no detail-> MED
      Est + details  -> MED
      Est + no detail-> LOW
    """
    sourced = (rate_source == "Src")
    if sourced and is_detailed:
        level = "HIGH"
    elif sourced or is_detailed:
        level = "MED"
    else:
        level = "LOW"
    if size_downgrade and level != "LOW":
        level = _downgrade_level(level)
    return level
