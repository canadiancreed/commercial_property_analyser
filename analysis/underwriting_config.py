"""
Loader for house underwriting assumptions (the 'underwriting' config document).

Every tunable number that governs the returns model — NOI growth, exit-cap
spread, inflation — lives in one config document so a reviewer can change the
house numbers without touching Python. (v5.0.0: the document lives in the DB
`config` table, seeded from data/seeds; a store-less caller falls back to the
embedded seed.)
"""
_CONFIG_NAME = "underwriting"

_REQUIRED_KEYS = ("noi_growth_default", "exit_cap_spread_bps", "inflation_rate",
                  "stress_rate_bump", "stress_min_dscr",
                  "confidence_uncertainty_start", "confidence_steepness", "confidence_floor",
                  "cap_rate_risk_threshold_pct", "cap_rate_risk_slope", "cap_rate_risk_max_haircut",
                  "dom_normal_days", "dom_stale_days",
                  "drop_modest_pct", "drop_large_pct", "drop_severe_pct",
                  "market_signal_verified_income_threshold_pct",
                  "dom_stale_confidence_factor", "price_drop_confidence_factor",
                  "joint_signal_confidence_factor", "thin_market_confidence_factor",
                  "market_signal_confidence_floor",
                  "amplifier_engage_min_signals", "low_income_conf_always_engages_amplifier",
                  "liquidity_distance_reference_km", "liquidity_population_reference",
                  "liquidity_weight_distance", "liquidity_weight_population",
                  "liquidity_weight_growth",
                  "liquidity_liquid_threshold", "liquidity_thin_threshold")

_store = None
_cache = None


class UnderwritingConfigError(RuntimeError):
    pass


def set_store(store):
    """Route underwriting-config reads through a DataStore's `config` table. Pass None to
    revert to the embedded seed (tests / CLI without a store)."""
    global _store, _cache
    _store = store
    _cache = None


def load_underwriting_config(force_reload: bool = False) -> dict:
    global _cache
    if _cache is not None and not force_reload:
        return _cache
    if _store is not None:
        data = _store.read_config(_CONFIG_NAME)
    else:
        from data import seeds
        import copy
        data = copy.deepcopy(seeds.CONFIG_DEFAULTS.get(_CONFIG_NAME) or {})
    missing = [k for k in _REQUIRED_KEYS if k not in data]
    if missing:
        raise UnderwritingConfigError(
            f"Underwriting config is missing required key(s): {', '.join(missing)}"
        )
    data.setdefault("exit_cap_aging_bps_per_year", 10)
    _cache = data
    return data


def get(key: str):
    return load_underwriting_config()[key]
