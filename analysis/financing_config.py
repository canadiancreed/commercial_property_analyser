"""
Loader for global financing defaults (config/financing.json).

Down payment, interest rate, amortization (loan term), and hold period are
house-wide assumptions applied to every property rather than entered per
listing — in a real portfolio they're identical across deals. They live in this
one JSON file so changing a value (then re-analyzing) moves every property's
mortgage, cash flow, and returns. Missing file/keys are a hard error, not a
silent fallback to a buried literal: a financing assumption that quietly reverts
to a guess is worse than a loud crash.

(Expense ratio is deliberately NOT here: it is set globally *by property type*
and lease via models/constants.py EXPENSE_RATIO_DEFAULTS — NNN ~8%, hotel ~63%,
multi-family ~45% — so one portfolio-wide number would be wrong.)
"""
import json

_CONFIG_PATH = "config/financing.json"

_COMMENT = (
    "Global financing defaults applied to every property. Down payment, "
    "interest rate, amortization (loan term), and hold period are house-wide "
    "assumptions — set once here, not entered per listing (in practice they're "
    "identical across the portfolio). Change a value and re-analyze all "
    "properties (main menu 'f' offers to do this) to move every mortgage, "
    "cash-flow, and return figure. Nothing here is hardcoded in the Python. "
    "(Expense ratio is NOT here: it is set globally BY PROPERTY TYPE / lease "
    "via models/constants.py EXPENSE_RATIO_DEFAULTS, so a single number would "
    "be wrong.)"
)

_REQUIRED_KEYS = ("down_payment_pct", "interest_rate", "term_years", "hold_years")

_cache = None


class FinancingConfigError(RuntimeError):
    pass


def load_financing_config(force_reload: bool = False) -> dict:
    global _cache
    if _cache is not None and not force_reload:
        return _cache
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError as e:
        raise FinancingConfigError(
            f"Financing config not found at {_CONFIG_PATH!r} — cannot resolve "
            f"down payment / interest rate / amortization defaults."
        ) from e
    except json.JSONDecodeError as e:
        raise FinancingConfigError(
            f"Financing config at {_CONFIG_PATH!r} is not valid JSON: {e}"
        ) from e
    missing = [k for k in _REQUIRED_KEYS if k not in data]
    if missing:
        raise FinancingConfigError(
            f"Financing config at {_CONFIG_PATH!r} is missing required key(s): "
            f"{', '.join(missing)}"
        )
    _cache = data
    return data


def get(key: str):
    return load_financing_config()[key]


def save_financing_config(down_payment_pct: float, interest_rate: float,
                          term_years: int, hold_years: int) -> dict:
    """Persist new global financing defaults and refresh the module cache.

    Values are stored in decimal form (0.20, not 20) to match how the rest of
    the app carries rates. Callers that accept human-entered percentages should
    normalise before calling here.
    """
    global _cache
    data = {
        "_comment":         _COMMENT,
        "down_payment_pct": round(float(down_payment_pct), 6),
        "interest_rate":    round(float(interest_rate), 6),
        "term_years":       int(term_years),
        "hold_years":       int(hold_years),
    }
    tmp = _CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    import os
    os.replace(tmp, _CONFIG_PATH)
    _cache = data
    return data
