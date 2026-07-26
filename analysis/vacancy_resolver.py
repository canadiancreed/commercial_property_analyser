"""
Region-keyed vacancy resolver (v3.7).

Replaces the flat per-type vacancy constant (models/constants.VACANCY_RATE_DEFAULTS,
formerly consulted directly by analysis/analyzer._resolve_vacancy_rate) with a lookup
resolved by an always-terminating 4-tier fallback chain, sourced from two versioned
downloads (refresh = re-run the fetch scripts, never hand-edit):

  * json/vacancy_rates.json         - CMHC Rental Market Survey apartment vacancy,
                                      keyed by StatCan CMA/CA code (and, for
                                      standalone-surveyed centres, by CSD code), with a
                                      reliability code per figure + provincial floors.
  * json/geographic_crosswalk.json  - StatCan Geographic Attribute File (92-151-X):
                                      CSD -> CMA/CA -> province, plus a normalized name
                                      index for the one unavoidable name-based hop.

Join:  deal city+province -> CSD code -> CMA/CA code -> vacancy.
Only the first hop (city name -> CSD code) is name-based, because deal data carries no
codes; every hop after that is code-to-code.

Fallback chain (top-down, first hit wins):

  tier 1  region          CSD maps to a directly-surveyed CMHC region        (raw figure)
  tier 2  parent_cma      CSD sits in a surveyed CMA/CA (not surveyed alone)  (raw figure)
  tier 3  provincial_avg  outside any surveyed region -> provincial average   (raw figure)
  tier 4  constant_floor  nothing resolved -> max(type constant, national)    [ALARM]

Type awareness: CMHC RMS measures RESIDENTIAL vacancy only. Residential asset classes
(multi-family, residential, and the residential component of mixed-use) draw tiers 1-3
from the survey. Commercial classes (office/retail/industrial/hotel/...) have no
regional survey wired in this version, so they resolve straight to their per-type
sourced constant - stamp ``type_default``, ``normal=True`` (an expected baseline, kept
distinct from the residential tier-4 ``constant_floor`` alarm so the tripwire stays
meaningful). A future commercial regional feed slots into tiers 1-3 for those types
with no change to this resolver.

Conservative floor: ONLY tier 4 (the genuine no-real-data / pipeline-break case) uses
max(type_constant, national) so a data gap never flatters a deal. Tiers 1-3 all report
their real CMHC figure raw — including a provincial average below the 3% constant, which
is real data, not a gap. (Flooring tier 3 would overwrite genuine sub-constant provinces
with the stale default, re-creating the blanket constant this pipeline removes.)

Tripwire: tier 4 with ``normal=False`` (a residential deal that fell all the way through
to the constant floor) means the fetch/join broke that run - count it, surface it, never
ship silently. Every property has a province, so tier 3 always resolves in healthy
operation.
"""
import json
from dataclasses import dataclass
from typing import Optional

from models.constants import (
    VACANCY_RATE_DEFAULTS,
    CANADIAN_PROVINCES,
    PROVINCE_NAME_TO_CODE,
)

_VACANCY_PATH = "json/vacancy_rates.json"
_CROSSWALK_PATH = "json/geographic_crosswalk.json"

# Property types whose vacancy CMHC RMS actually measures. Everything else is
# "commercial domain" and resolves to its per-type constant (no regional survey wired).
_RESIDENTIAL_TYPES = frozenset({"multi-family", "residential"})

# Reliability codes that trigger demotion to the parent tier (a technically-present-but-
# unreliable regional number is skipped). "d" is CMHC's own "use with caution" letter
# (HMIP portal); "e" is StatCan's equivalent quality flag on the republished series
# (the reachable channel — see scripts/fetch_vacancy_rates.py). The figure's code is
# always carried through and recorded regardless (VacancyResolution.demoted_from).
_DEMOTE_RELIABILITY = frozenset({"d", "e"})

# Unknown property type falls back to the same 5% the legacy resolver used.
_UNKNOWN_TYPE_CONSTANT = 0.05

_vacancy_cache = None
_crosswalk_cache = None


class VacancyDataError(RuntimeError):
    pass


@dataclass(frozen=True)
class VacancyResolution:
    """The result of resolving a property's vacancy rate. ``rate`` is the number the
    underwriting uses; every other field is provenance so the report/record can show
    how that number was reached and how much to trust it."""
    rate: float
    tier: int                       # 0 = explicit override, 1-4 = chain tier
    stamp: str                      # region | parent_cma | provincial_avg | constant_floor | override
    reliability: Optional[str]      # CMHC reliability code (a/b/c/d) or None
    geo_name: str                   # human label, e.g. "Kingston CMA" / "ON (provincial avg)"
    normal: bool                    # False only when the tier-4 alarm fires
    attribution: Optional[str]      # CMHC license string when a CMHC-sourced figure was used
    domain: str                     # "residential" | "commercial"
    demoted_from: Optional[str] = None  # label of a higher-tier figure skipped for poor
    #                                     reliability, e.g. "Kingston CMA (rel. d)"; None
    #                                     when no demotion occurred. Makes a demoted deal
    #                                     distinguishable from a genuine no-regional-data one.

    def provenance(self) -> str:
        """Compact one-line provenance for the report row, e.g.
        '3.1% · Kingston CMA · CMHC RMS (rel. a)' or '14.0% · type default'. A demotion
        appends '· demoted from <region> (rel. d)' so the skipped figure is never silent."""
        bits = [self.geo_name]
        if self.attribution:
            src = "CMHC RMS"
            if self.reliability:
                src += f" (rel. {self.reliability})"
            bits.append(src)
        # Tier 3 is not an official CMHC provincial rate — there is no provincial RMS cut,
        # so it is a derived unweighted mean of the surveyed centres in the province
        # (universe weights aren't published on the reachable StatCan WDS channel). Say so
        # inline wherever the figure surfaces, not only in the data file's _meta.
        if self.stamp == "provincial_avg":
            bits.append("derived: unweighted avg of surveyed centres")
        if self.demoted_from:
            bits.append(f"demoted from {self.demoted_from}")
        if not self.normal:
            bits.append("⚠ FLOOR — data gap")
        return " · ".join(b for b in bits if b)


# ── Data loading (hard-fail on a missing/corrupt file, like the other loaders) ──

def _load_json(path: str, what: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError as e:
        raise VacancyDataError(
            f"{what} not found at {path!r} — the regional vacancy pipeline cannot "
            f"resolve vacancy. Run the fetch script to (re)build it."
        ) from e
    except json.JSONDecodeError as e:
        raise VacancyDataError(f"{what} at {path!r} is not valid JSON: {e}") from e


def _load_vacancy(force_reload: bool = False) -> dict:
    global _vacancy_cache
    if _vacancy_cache is None or force_reload:
        _vacancy_cache = _load_json(_VACANCY_PATH, "Vacancy-rates data")
    return _vacancy_cache


def _load_crosswalk(force_reload: bool = False) -> dict:
    global _crosswalk_cache
    if _crosswalk_cache is None or force_reload:
        _crosswalk_cache = _load_json(_CROSSWALK_PATH, "Geographic crosswalk")
    return _crosswalk_cache


def reset_cache() -> None:
    """Drop the module caches. Used by tests that swap the data-file paths."""
    global _vacancy_cache, _crosswalk_cache
    _vacancy_cache = None
    _crosswalk_cache = None


# ── Normalization ──────────────────────────────────────────────────────────────

def _normalize_province(province: Optional[str]) -> str:
    p = (province or "").strip()
    if p.upper() in CANADIAN_PROVINCES:
        return p.upper()
    return PROVINCE_NAME_TO_CODE.get(p.lower(), p.upper())


def _normalize_name(city: Optional[str]) -> str:
    """Fold a city name to its index key form: lowercase, punctuation dropped,
    whitespace collapsed. So 'St. Marys', 'St Marys' and 'ST MARYS' all agree, and
    'St. John's' matches the deal-data 'St Johns'."""
    s = (city or "").strip().lower()
    out = []
    for ch in s:
        if ch.isalnum() or ch.isspace():
            out.append(ch)
        # drop '.', "'", '-', etc. entirely so "st. john's" -> "st johns"
    return " ".join("".join(out).split())


def _domain(property_type: Optional[str]) -> str:
    return "residential" if (property_type or "").strip().lower() in _RESIDENTIAL_TYPES else "commercial"


def _type_constant(property_type: Optional[str]) -> float:
    return VACANCY_RATE_DEFAULTS.get((property_type or "").strip().lower(), _UNKNOWN_TYPE_CONSTANT)


# ── Chain helpers ──────────────────────────────────────────────────────────────

def _usable_region(entry) -> bool:
    return isinstance(entry, dict) and isinstance(entry.get("vacancy_rate"), (int, float))


def _demoted(entry: dict, demote_unreliable: bool) -> bool:
    return demote_unreliable and (entry.get("reliability") in _DEMOTE_RELIABILITY)


def _demotion_label(entry: dict) -> str:
    """A short label for a figure skipped due to poor reliability, carrying the region
    and its grade, e.g. 'Brockville CA (rel. d)'. This is what the demoted-from provenance
    shows so the skipped figure and its grade survive the demotion instead of vanishing."""
    name = entry.get("name") or "region"
    level = entry.get("geo_level")
    label = f"{name} {level}".strip() if level else name
    rel = entry.get("reliability")
    return f"{label} (rel. {rel})" if rel else label


def _lookup_csd(xwalk: dict, city: str, prov: str) -> Optional[str]:
    key = f"{_normalize_name(city)}|{prov}"
    return xwalk.get("name_index", {}).get(key)


def _region_resolution(entry: dict, tier: int, stamp: str, attribution: Optional[str],
                       demoted_from: Optional[str] = None) -> VacancyResolution:
    return VacancyResolution(
        rate=float(entry["vacancy_rate"]),
        tier=tier,
        stamp=stamp,
        reliability=entry.get("reliability"),
        geo_name=entry.get("name") or stamp,
        normal=True,
        attribution=attribution,
        domain="residential",
        demoted_from=demoted_from,
    )


# ── Public API ─────────────────────────────────────────────────────────────────

def resolve_vacancy(city: Optional[str], province: Optional[str],
                    property_type: Optional[str], *,
                    demote_unreliable: bool = True) -> VacancyResolution:
    """Resolve a property's vacancy rate through the 4-tier chain. Never raises for a
    lookup miss — it always terminates (tier 3 in healthy operation, tier 4 alarm if
    even the province can't be resolved). Only a missing/corrupt data FILE raises."""
    vac = _load_vacancy()
    xwalk = _load_crosswalk()
    prov = _normalize_province(province)
    type_constant = _type_constant(property_type)
    attribution = vac.get("_meta", {}).get("attribution")

    # Commercial domain: no regional survey source wired this version. Resolve to the
    # per-type sourced constant. Distinct stamp ``type_default`` (not ``constant_floor``)
    # keeps this EXPECTED baseline separate from the residential tier-4 alarm, so the
    # batch tripwire and source-mix stay meaningful. ``normal=True`` — never an alarm.
    if _domain(property_type) == "commercial":
        return VacancyResolution(
            rate=type_constant, tier=4, stamp="type_default",
            reliability=None, geo_name="type default",
            normal=True, attribution=None, domain="commercial",
        )

    regions = vac.get("regions", {})
    csd_code = _lookup_csd(xwalk, city, prov)
    # A poor-reliability ("d") figure skipped on the way down is recorded here so the
    # demotion is visible on whatever tier we ultimately land on — never discarded.
    demoted_from = None

    if csd_code is not None:
        csd = xwalk.get("csd", {}).get(csd_code, {})
        cma_ca_code = csd.get("cma_ca_code")
        # Tier 1 — the CSD itself is a surveyed region.
        entry = regions.get(csd_code)
        if _usable_region(entry):
            if _demoted(entry, demote_unreliable):
                demoted_from = demoted_from or _demotion_label(entry)
            else:
                return _region_resolution(entry, 1, "region", attribution, demoted_from)
        # Tier 2 — the CSD's parent CMA/CA is surveyed.
        if cma_ca_code is not None:
            entry = regions.get(str(cma_ca_code))
            if _usable_region(entry):
                if _demoted(entry, demote_unreliable):
                    demoted_from = demoted_from or _demotion_label(entry)
                else:
                    return _region_resolution(entry, 2, "parent_cma", attribution, demoted_from)

    # Tier 3 — provincial average. This is a REAL CMHC figure (just at provincial
    # granularity), so it is trusted RAW — no floor. Flooring it at the per-type
    # constant would overwrite genuine sub-constant provinces (national purpose-built
    # vacancy ran 1.5-2.2% in 2023-24; BC ~1.9%) with the stale 3% default, re-creating
    # the exact blanket-constant mis-statement this pipeline removes. The conservative
    # max(constant, ...) floor belongs only at tier 4, where there is no real data.
    prov_entry = vac.get("provincial", {}).get(prov)
    if isinstance(prov_entry, dict) and isinstance(prov_entry.get("vacancy_rate"), (int, float)):
        return VacancyResolution(
            rate=float(prov_entry["vacancy_rate"]),
            tier=3, stamp="provincial_avg",
            reliability=prov_entry.get("reliability"),
            geo_name=f"{prov} (provincial avg)",
            normal=True, attribution=attribution, domain="residential",
            demoted_from=demoted_from,
        )

    # Tier 4 — nothing resolved. Conservative floor + ALARM (province missing/unknown
    # or the provincial table has no entry => the fetch/join broke this run).
    national = vac.get("national", {})
    nat_rate = national.get("vacancy_rate") if isinstance(national, dict) else None
    rate = max(type_constant, float(nat_rate)) if isinstance(nat_rate, (int, float)) else type_constant
    return VacancyResolution(
        rate=rate, tier=4, stamp="constant_floor",
        reliability=None, geo_name="constant floor",
        normal=False, attribution=None, domain="residential",
        demoted_from=demoted_from,
    )


def attribution_string() -> Optional[str]:
    """The CMHC license attribution string for report footnotes/about sections.
    'Adapted from Canada Mortgage and Housing Corporation, Rental Market Survey, <date>.'"""
    try:
        return _load_vacancy().get("_meta", {}).get("attribution")
    except VacancyDataError:
        return None
