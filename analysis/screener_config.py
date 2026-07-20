"""
Loader for deal-screener thresholds (config/screener_config.json).

Every threshold introduced by the deal-screener upgrades — the break-even
occupancy display cap and warning line, and the price-drop-velocity /
seller-bleed triggers behind the Deal Context "Read" — lives in this one JSON
file so a reviewer can tune the screen without touching Python. Missing
file/keys are a hard error (not a silent fallback to a buried literal), matching
underwriting.json / financing.json.
"""
import json

_CONFIG_PATH = "config/screener_config.json"

_REQUIRED_KEYS = (
    "beo_display_cap",
    "beo_warning_threshold",
    "motivated_price_drop_pct",
    "motivated_max_dom_days",
    "low_monthly_bleed_threshold",
)

_cache = None


class ScreenerConfigError(RuntimeError):
    pass


def load_screener_config(force_reload: bool = False) -> dict:
    global _cache
    if _cache is not None and not force_reload:
        return _cache
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError as e:
        raise ScreenerConfigError(
            f"Screener config not found at {_CONFIG_PATH!r} — cannot resolve "
            f"break-even / price-drop-velocity thresholds."
        ) from e
    except json.JSONDecodeError as e:
        raise ScreenerConfigError(
            f"Screener config at {_CONFIG_PATH!r} is not valid JSON: {e}"
        ) from e
    missing = [k for k in _REQUIRED_KEYS if k not in data]
    if missing:
        raise ScreenerConfigError(
            f"Screener config at {_CONFIG_PATH!r} is missing required key(s): "
            f"{', '.join(missing)}"
        )
    _cache = data
    return data


def get(key: str):
    return load_screener_config()[key]
