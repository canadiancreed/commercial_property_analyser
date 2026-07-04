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

_REQUIRED_KEYS = ("noi_growth_default", "exit_cap_spread_bps", "inflation_rate")

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
