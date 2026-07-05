"""
Loader for house underwriting assumptions (config/underwriting.json).

Every tunable number that governs the returns model — NOI growth, exit-cap
spread, inflation — lives in this one JSON file so a reviewer can change the
house numbers without touching Python. Missing file/keys are a hard error
(not a silent fallback to a buried literal): an underwriting assumption that
quietly reverts to a guess is worse than a loud crash.
"""
import json

_CONFIG_PATH = "config/underwriting.json"

_REQUIRED_KEYS = ("noi_growth_default", "exit_cap_spread_bps", "inflation_rate",
                  "stress_rate_bump", "stress_min_dscr",
                  "confidence_uncertainty_start", "confidence_steepness", "confidence_floor",
                  "cap_rate_risk_threshold_pct", "cap_rate_risk_confidence_factor",
                  "dom_normal_days", "dom_stale_days",
                  "drop_modest_pct", "drop_large_pct", "drop_severe_pct",
                  "market_signal_verified_income_threshold_pct",
                  "dom_stale_confidence_factor", "price_drop_confidence_factor",
                  "joint_signal_confidence_factor", "thin_market_confidence_factor",
                  "market_signal_confidence_floor",
                  "liquidity_distance_reference_km", "liquidity_population_reference",
                  "liquidity_weight_distance", "liquidity_weight_population",
                  "liquidity_weight_growth",
                  "liquidity_liquid_threshold", "liquidity_thin_threshold")

_cache = None


class UnderwritingConfigError(RuntimeError):
    pass


def load_underwriting_config(force_reload: bool = False) -> dict:
    global _cache
    if _cache is not None and not force_reload:
        return _cache
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError as e:
        raise UnderwritingConfigError(
            f"Underwriting config not found at {_CONFIG_PATH!r} — cannot resolve "
            f"NOI growth / exit cap / inflation assumptions."
        ) from e
    except json.JSONDecodeError as e:
        raise UnderwritingConfigError(
            f"Underwriting config at {_CONFIG_PATH!r} is not valid JSON: {e}"
        ) from e
    missing = [k for k in _REQUIRED_KEYS if k not in data]
    if missing:
        raise UnderwritingConfigError(
            f"Underwriting config at {_CONFIG_PATH!r} is missing required key(s): "
            f"{', '.join(missing)}"
        )
    data.setdefault("exit_cap_aging_bps_per_year", 10)
    _cache = data
    return data


def get(key: str):
    return load_underwriting_config()[key]
