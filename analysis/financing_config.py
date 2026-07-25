"""
Loader + resolver for global financing assumptions (config/financing.json).

TWO LAYERS:
  • ``defaults``        — house-wide down payment / interest rate / amortization /
                          hold period (edited via main menu 'f'). Hard-fail on a
                          missing key: a financing assumption that quietly reverts
                          to a guess is worse than a loud crash.
  • ``property_types``  — OPTIONAL per-type overrides (max_ltv → down payment,
                          rate band midpoint → interest rate, amort_years → term).
                          This is the same logic PR #55 used for expense ratio —
                          one flat number would be wrong across asset classes. A
                          missing/empty map reproduces pre-per-type behavior
                          exactly (defaults apply to everything).

Resolution (``get_financing``) shallow-merges the resolved per-type block over
``defaults`` and derives the three scalars the pipeline consumes. ``hold_years``
lives in ``defaults`` ONLY — never per type. ALL routing lives here and nowhere
else: ``retail_office`` → ``office`` alias resolution, the multi-family unit-count
split (1-4 vs 5+), and the multi_family_5plus small-balance-conventional-vs-CMHC
decision.

(Expense ratio is deliberately NOT here: it is set globally *by property type*
and lease via models/constants.py EXPENSE_RATIO_DEFAULTS.)
"""
import json
import os

_CONFIG_PATH = "config/financing.json"

_COMMENT = (
    "Global financing assumptions. TWO LAYERS: 'defaults' holds the house-wide "
    "down payment / interest rate / amortization / hold period (edited via main "
    "menu 'f'); 'property_types' optionally overrides down payment (via max_ltv), "
    "rate (band midpoint), and amortization (amort_years) PER PROPERTY TYPE — the "
    "same logic PR #55 applied to expense ratio (one number would be wrong across "
    "asset classes). Resolution = a per-type block shallow-merged over defaults "
    "(analysis/financing_config.py get_financing). hold_years lives in 'defaults' "
    "ONLY — never per type. A missing/empty 'property_types' map reproduces "
    "pre-per-type behavior exactly (defaults apply to everything). Nothing here is "
    "hardcoded in the Python. Change a value and re-analyze (menu 'f' offers to) "
    "to move every mortgage / cash-flow / return figure."
)

_REQUIRED_DEFAULT_KEYS = ("down_payment_pct", "interest_rate", "term_years", "hold_years")

# App property-type strings (normalised) that route to the multi-family blocks,
# split by unit count. "residential" (single/small rental) sits here too — the
# 1-4 vs 5+ boundary, not the label, decides which lending regime applies.
_MULTIFAMILY_TYPES = frozenset({"multi_family", "multifamily", "residential"})
_MULTIFAMILY_5PLUS_UNITS = 5

_cache = None


class FinancingConfigError(RuntimeError):
    pass


# ── Raw load / defaults ────────────────────────────────────────────────────

def _load_raw(force_reload: bool = False) -> dict:
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
    _cache = data
    return data


def _defaults(raw: dict) -> dict:
    """Return the validated ``defaults`` block. Falls back to a legacy flat file
    (the four keys at top level) so an un-migrated config still loads."""
    d = raw["defaults"] if isinstance(raw.get("defaults"), dict) else raw
    missing = [k for k in _REQUIRED_DEFAULT_KEYS if k not in d]
    if missing:
        raise FinancingConfigError(
            f"Financing config at {_CONFIG_PATH!r} is missing required "
            f"default(s): {', '.join(missing)}"
        )
    return d


def load_financing_config(force_reload: bool = False) -> dict:
    """Backward-compatible accessor: returns the flat ``defaults`` block (the four
    house-wide scalars), exactly as before the two-layer restructure."""
    return _defaults(_load_raw(force_reload))


def get(key: str):
    return load_financing_config()[key]


# ── Per-type resolution ────────────────────────────────────────────────────

def _type_key(property_type, units):
    """Map an app property-type string (or a canonical financing key) to a
    property_types key. Multi-family/residential split by unit count. Returns a
    normalised key; callers treat a key absent from property_types as "defaults"."""
    if not property_type:
        return None
    p = property_type.strip().lower().replace(" ", "_").replace("-", "_")
    if p in ("multi_family_1_4", "multi_family_5plus"):
        return p  # canonical, explicit — unit count already baked in
    if p in _MULTIFAMILY_TYPES:
        return ("multi_family_5plus"
                if (units is not None and units >= _MULTIFAMILY_5PLUS_UNITS)
                else "multi_family_1_4")
    return p  # office / retail / industrial / mixed_use / hotel / retail_office


def _resolve_alias_key(key, ptypes):
    """Follow ``{"alias": X}`` chains generically to the concrete block key."""
    seen = set()
    while (key in ptypes and isinstance(ptypes[key], dict)
           and "alias" in ptypes[key] and key not in seen):
        seen.add(key)
        key = ptypes[key]["alias"]
    return key


def _derive_scalars(block: dict) -> dict:
    """Translate a rich per-type block (max_ltv / rate band / amort_years) into
    the three pipeline scalars. hold_years is intentionally not derived here."""
    out = {}
    if "max_ltv" in block:
        out["down_payment_pct"] = round(1 - block["max_ltv"], 6)
    if "rate_low" in block and "rate_high" in block:
        out["interest_rate"] = (block["rate_low"] + block["rate_high"]) / 2
    if "amort_years" in block:
        out["term_years"] = block["amort_years"]
    return out


def conventional_max_ltv(property_type=None, units=None) -> float:
    """The conventional (non-CMHC) max LTV for a type — used to size the routing
    loan estimate. Falls back to the house default when no type block applies."""
    raw = _load_raw()
    ptypes = raw.get("property_types") or {}
    key = _type_key(property_type, units)
    if key:
        key = _resolve_alias_key(key, ptypes)
    block = ptypes.get(key) if key else None
    if isinstance(block, dict) and "max_ltv" in block:
        return block["max_ltv"]
    return 1 - _defaults(raw)["down_payment_pct"]


def get_financing(property_type=None, units=None, loan_estimate=None) -> dict:
    """Resolve the merged financing block for a property.

    Returns the four pipeline scalars (down_payment_pct / interest_rate /
    term_years / hold_years) plus the rich per-type fields (max_ltv, dscr_floor,
    fixed_expense_fraction, cmhc, …) and routing metadata (financing_scenario,
    small_balance_flag). With no matching type block the result is the defaults
    unchanged — pre-per-type behavior.

    ``loan_estimate`` (a dollar loan size) is used ONLY to route
    multi_family_5plus: at or above the CMHC min_practical_loan the MLI Select
    block becomes the primary scenario; below it, conventional is primary and
    CMHC is flagged as a secondary (small-balance) option.
    """
    raw = _load_raw()
    defaults = _defaults(raw)
    ptypes = raw.get("property_types") or {}

    result = dict(defaults)  # down_payment_pct, interest_rate, term_years, hold_years
    result["stress_test_bump"] = raw.get("stress_test_bump", 0.0)
    result["verified_date"]    = raw.get("verified_date")
    # Residential fallback covenant for types that qualify on borrower GDS/TDS
    # (null dscr_floor) — used by the financing-robustness margins (Fix 6).
    residential_covenant = raw.get("residential_covenant_dscr", 1.1)

    type_key = _type_key(property_type, units)
    if type_key:
        type_key = _resolve_alias_key(type_key, ptypes)
    block = ptypes.get(type_key) if type_key else None

    if not isinstance(block, dict):
        # Unknown/absent type → defaults only (pre-per-type behavior).
        result.update({
            "type_key": type_key, "source": "defaults",
            "financing_scenario": "default",
            "max_ltv": round(1 - defaults["down_payment_pct"], 6),
            "rate_low": None, "rate_high": None, "amort_years": defaults["term_years"],
            "dscr_floor": None, "covenant_dscr": residential_covenant,
            "fixed_expense_fraction": None,
            "cmhc_eligible": False, "cmhc": None,
            "small_balance_flag": False, "notes": "",
        })
        return result

    cmhc = block.get("cmhc")
    active = block                     # conventional block by default
    scenario = "type"
    small_balance_flag = False

    if type_key == "multi_family_5plus" and isinstance(cmhc, dict):
        min_practical = cmhc.get("min_practical_loan")
        use_mli = (loan_estimate is not None and min_practical is not None
                   and loan_estimate >= min_practical)
        if use_mli:
            active = {**block, **cmhc["mli_select"]}   # MLI overrides ltv/rate/amort/dscr
            scenario = "mli_select"
        else:
            scenario = "conventional"
            small_balance_flag = (min_practical is not None and loan_estimate is not None
                                  and loan_estimate < min_practical)

    result.update(_derive_scalars(active))     # down_payment_pct / interest_rate / term_years
    result.update({
        "type_key": type_key, "source": "property_type",
        "financing_scenario": scenario,
        "max_ltv": active.get("max_ltv"),
        "rate_low": active.get("rate_low"), "rate_high": active.get("rate_high"),
        "amort_years": active.get("amort_years"),
        "dscr_floor": active.get("dscr_floor"),
        # Covenant DSCR (Fix 6 robustness) == the resolved lending dscr_floor
        # (scenario-aware: 1.10 under MLI Select, else the conventional floor).
        # Null-floor types (1-4 residential, GDS/TDS-qualified) use the fallback.
        "covenant_dscr": active.get("dscr_floor") or residential_covenant,
        # fixed_expense_fraction is a property of the ASSET CLASS, so it always
        # comes from the parent type block — never the MLI sub-block (which omits it).
        "fixed_expense_fraction": block.get("fixed_expense_fraction"),
        "cmhc_eligible": block.get("cmhc_eligible", False),
        "cmhc": cmhc,
        "small_balance_flag": small_balance_flag,
        "notes": block.get("notes", ""),
    })
    return result


def resolve_financing(price, property_type=None, units=None) -> dict:
    """Convenience wrapper: sizes the routing loan estimate from the asking price
    (price × the conventional LTV) and returns the fully-routed merged block.
    This is the single entry point the pipeline (_record_to_prop, the analyzer)
    uses so the loan-estimate routing lives entirely inside this module."""
    loan_estimate = (price or 0) * conventional_max_ltv(property_type, units)
    return get_financing(property_type, units, loan_estimate=loan_estimate)


# ── Persistence (menu 'f' edits the defaults layer only) ───────────────────

def save_financing_config(down_payment_pct: float, interest_rate: float,
                          term_years: int, hold_years: int) -> dict:
    """Persist new global financing *defaults* and refresh the module cache. The
    per-type ``property_types`` map, ``stress_test_bump`` and ``verified_date``
    are preserved untouched — menu 'f' edits the defaults layer only.

    Values are stored in decimal form (0.20, not 20). Callers that accept
    human-entered percentages should normalise before calling here.
    """
    global _cache
    raw = dict(_load_raw())
    data = {"_comment": _COMMENT}
    data["defaults"] = {
        "down_payment_pct": round(float(down_payment_pct), 6),
        "interest_rate":    round(float(interest_rate), 6),
        "term_years":       int(term_years),
        "hold_years":       int(hold_years),
    }
    if "stress_test_bump" in raw:
        data["stress_test_bump"] = raw["stress_test_bump"]
    if "verified_date" in raw:
        data["verified_date"] = raw["verified_date"]
    if "property_types" in raw:
        data["property_types"] = raw["property_types"]

    tmp = _CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, _CONFIG_PATH)
    _cache = data
    return data
