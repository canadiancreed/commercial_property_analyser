"""
Loader for deal-screener thresholds (the 'screener' config document).

Every threshold introduced by the deal-screener upgrades — the break-even
occupancy display cap and warning line, and the price-drop-velocity /
seller-bleed triggers behind the Deal Context "Read" — lives in one config
document so a reviewer can tune the screen without touching Python. (v5.0.0: the
document lives in the DB `config` table, seeded from data/seeds; a store-less
caller falls back to the embedded seed.)
"""
_CONFIG_NAME = "screener"

_REQUIRED_KEYS = (
    "beo_display_cap",
    "beo_warning_threshold",
    "motivated_price_drop_pct",
    "motivated_max_dom_days",
    "low_monthly_bleed_threshold",
    "component_vacancy",
    "mixed_use_commercial_gross_expense_ratio",
    "commercial_majority_threshold",
)

_store = None
_cache = None


class ScreenerConfigError(RuntimeError):
    pass


def set_store(store):
    """Route screener-config reads through a DataStore's `config` table. Pass None to
    revert to the embedded seed (tests / CLI without a store)."""
    global _store, _cache
    _store = store
    _cache = None


def load_screener_config(force_reload: bool = False) -> dict:
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
        raise ScreenerConfigError(
            f"Screener config is missing required key(s): {', '.join(missing)}"
        )
    _cache = data
    return data


def get(key: str):
    return load_screener_config()[key]
