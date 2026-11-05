"""
Live base-rate feed: the Bank of Canada 5-year Government of Canada benchmark
bond yield, the ONE sourced number behind commercial-mortgage pricing.

WHY THIS, WHY A FEED
--------------------
Commercial mortgage rates are not published anywhere as a single authoritative
series — a lender quotes ``reference rate + credit spread``. The reference rate
IS public and sourceable: the Government of Canada 5-year benchmark bond yield,
published daily by the Bank of Canada. So this module fetches that yield and the
rest of the stack prices every asset class off it:

    rate(type) = GoC-5yr-yield  +  per-type credit spread

The per-type spread stays a hand-maintained estimate in config/financing.json
(spreads are small and stable; it's the *level* that moves with the market, and
the level is now sourced). See analysis/financing_config.py for how the fetched
base shifts the stored rate bands.

SOURCE
    Bank of Canada — Valet API (open, unauthenticated, no key required).
    Group  : bond_yields_benchmark   (daily GoC benchmark yields, 2/3/5/7/10yr)
    Series : BD.CDN.5YR.DQ.YLD        (the 5-year, our base)
    Context: V39079                   (target for the overnight / policy rate)
    Terms  : attribution required; "not an endorsement by the Bank of Canada".

REFRESH
    Re-run scripts/fetch_interest_rates.py, or let the desktop app refresh on
    boot (throttled to once/day, offline-safe — a failed fetch leaves the last
    good json/interest_rates.json untouched and the engine falls back to it, or
    ultimately to the anchor baked into config/financing.json).

This module imports nothing project-specific and never raises into a caller that
uses refresh_interest_rates() — it is safe to call on every startup.
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone

OUT_PATH = os.path.join("json", "interest_rates.json")

_VALET = "https://www.bankofcanada.ca/valet"
_BENCHMARK_GROUP = f"{_VALET}/observations/group/bond_yields_benchmark/json?recent=1"
_POLICY_OBS = f"{_VALET}/observations/V39079/json?recent=1"

BASE_SERIES = "BD.CDN.5YR.DQ.YLD"
POLICY_SERIES = "V39079"
_CURVE = {
    "2yr": "BD.CDN.2YR.DQ.YLD",
    "3yr": "BD.CDN.3YR.DQ.YLD",
    "5yr": "BD.CDN.5YR.DQ.YLD",
    "7yr": "BD.CDN.7YR.DQ.YLD",
    "10yr": "BD.CDN.10YR.DQ.YLD",
}

SOURCE_NAME = "Bank of Canada, Valet API"
SOURCE_URL = "https://www.bankofcanada.ca/valet/observations/group/bond_yields_benchmark/json"
SERIES_LABEL = "Government of Canada benchmark bond yield, 5-year"
ATTRIBUTION = ("Source: Bank of Canada. This does not constitute an endorsement "
               "by the Bank of Canada of this product.")

_USER_AGENT = "commercial-property-analyser (interest-rate fetch)"


# ── Network ────────────────────────────────────────────────────────────────

def _get_json(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _pct(v):
    """Valet returns yields as percent strings ('3.49'); store as a fraction."""
    return round(float(v) / 100.0, 6)


def fetch_base_rate(timeout: float = 8.0) -> dict:
    """Fetch the latest GoC 5-year benchmark yield (+ curve + policy rate for
    context). Returns a payload dict. Raises on any network / parse failure —
    callers that must not fail use refresh_interest_rates() instead."""
    data = _get_json(_BENCHMARK_GROUP, timeout)
    obs = data.get("observations") or []
    if not obs:
        raise ValueError("Valet returned no bond-yield observations.")
    latest = obs[-1]
    as_of = latest.get("d")
    if BASE_SERIES not in latest or "v" not in latest[BASE_SERIES]:
        raise ValueError(f"5-year series {BASE_SERIES} missing from the latest observation.")
    base_rate = _pct(latest[BASE_SERIES]["v"])

    curve = {}
    for label, sid in _CURVE.items():
        cell = latest.get(sid) or {}
        if "v" in cell:
            curve[label] = _pct(cell["v"])

    policy_rate = None
    try:
        pdata = _get_json(_POLICY_OBS, timeout)
        pobs = pdata.get("observations") or []
        if pobs and POLICY_SERIES in pobs[-1]:
            policy_rate = _pct(pobs[-1][POLICY_SERIES]["v"])
    except Exception:
        pass  # context only — a missing policy rate never fails the fetch

    now = datetime.now(timezone.utc)
    return {
        "_meta": {
            "description": ("Government of Canada 5-year benchmark bond yield — the sourced base "
                            "rate for commercial-mortgage pricing. Per-type rates = this base + a "
                            "per-asset-class credit spread (config/financing.json)."),
            "source": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "series": BASE_SERIES,
            "series_label": SERIES_LABEL,
            "unit": "fraction (0.0349 == 3.49%)",
            "attribution": ATTRIBUTION,
            "refresh": ("Re-run scripts/fetch_interest_rates.py, or the desktop app refreshes on "
                        "boot (once/day, offline-safe). Re-analyze to push new rates into stored results."),
        },
        "base_rate": base_rate,
        "as_of": as_of,
        "status": "fetched",
        "fetched_at": now.isoformat(timespec="seconds"),
        "last_updated": now.date().isoformat(),
        "context": {
            "policy_rate": policy_rate,
            "policy_rate_series": POLICY_SERIES,
            "yield_curve": curve,
        },
    }


# ── Persistence ──────────────────────────────────────────────────────────────

def write_interest_rates(payload: dict, path: str = OUT_PATH) -> str:
    """Atomically write the payload (tmp + os.replace) so a crash mid-write never
    leaves a truncated file."""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return path


def _age_hours(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            stamp = json.load(f).get("fetched_at")
        if not stamp:
            return None
        then = datetime.fromisoformat(stamp)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - then).total_seconds() / 3600.0
    except Exception:
        return None


def refresh_interest_rates(path: str = OUT_PATH, max_age_hours: float = 24.0,
                           timeout: float = 8.0, force: bool = False) -> tuple[bool, str]:
    """Offline-safe refresh. Skips when the existing file is younger than
    ``max_age_hours``; otherwise fetches and writes. NEVER raises and never
    clobbers a good file on failure. Returns (changed, reason)."""
    if not force:
        age = _age_hours(path)
        if age is not None and age < max_age_hours:
            return False, f"fresh ({age:.1f}h old; threshold {max_age_hours:.0f}h)"
    try:
        payload = fetch_base_rate(timeout=timeout)
    except Exception as e:
        return False, f"fetch failed ({type(e).__name__}: {e}) — kept existing file"
    write_interest_rates(payload, path)
    return True, (f"updated: GoC 5yr = {payload['base_rate']*100:.3g}% "
                  f"(as of {payload.get('as_of')})")
