"""
Regional vacancy resolver (v3.7) — the 4-tier fallback chain.

Every tier is exercised against small temp-file fixtures (a crosswalk + a vacancy
table) so the tests don't depend on the committed seed or a live fetch:

  tier 1  region          CSD keyed directly in the vacancy table
  tier 2  parent_cma      CSD's parent CMA/CA keyed
  tier 3  provincial_avg  no region match -> provincial average, conservative max() floor
  tier 4  constant_floor  province unresolved -> ALARM (normal=False)

plus: commercial type_default, reliability carry + demotion, and the name->CSD hop.
"""
import json
import pytest

import analysis.vacancy_resolver as vr
from analysis.vacancy_resolver import resolve_vacancy, attribution_string

ATTR = "Adapted from Canada Mortgage and Housing Corporation, Rental Market Survey, October 2025."


@pytest.fixture
def resolver(tmp_path, monkeypatch):
    """Point the resolver at temp crosswalk + vacancy fixtures and reset its cache."""
    crosswalk = {
        "province_codes": {"35": "ON", "10": "NL"},
        "cma_ca": {
            "521": {"name": "Kingston", "type": "CMA", "province": "ON"},
            "512": {"name": "Brockville", "type": "CA", "province": "ON"},
        },
        "csd": {
            "3510010": {"name": "Kingston",  "cma_ca_code": "521",  "province": "ON"},
            "3510005": {"name": "Loyalist",  "cma_ca_code": "521",  "province": "ON"},
            "3507015": {"name": "Brockville", "cma_ca_code": "512", "province": "ON"},
            "3531016": {"name": "St. Marys", "cma_ca_code": None,   "province": "ON"},
        },
        "name_index": {
            "kingston|ON": "3510010",
            "loyalist|ON": "3510005",
            "brockville|ON": "3507015",
            "st marys|ON": "3531016",
        },
    }
    vacancy = {
        "_meta": {"attribution": ATTR},
        "regions": {
            "3510010": {"vacancy_rate": 0.015, "reliability": "a", "geo_level": "CSD",
                        "name": "Kingston (city)", "province": "ON"},   # tier 1
            "521": {"vacancy_rate": 0.018, "reliability": "a", "geo_level": "CMA",
                    "name": "Kingston", "province": "ON"},              # tier 2
            "512": {"vacancy_rate": 0.089, "reliability": "d", "geo_level": "CA",
                    "name": "Brockville", "province": "ON"},            # reliability d -> demote
        },
        "provincial": {
            "ON": {"vacancy_rate": 0.024, "reliability": None},   # < 0.03 constant
            "NL": {"vacancy_rate": 0.050, "reliability": None},   # > 0.03 constant
        },
        "national": {"vacancy_rate": 0.020},   # below the 0.03 constant, so tier-4 max() is testable
    }
    xw = tmp_path / "xwalk.json"
    vc = tmp_path / "vac.json"
    xw.write_text(json.dumps(crosswalk), encoding="utf-8")
    vc.write_text(json.dumps(vacancy), encoding="utf-8")
    monkeypatch.setattr(vr, "_CROSSWALK_PATH", str(xw))
    monkeypatch.setattr(vr, "_VACANCY_PATH", str(vc))
    vr.reset_cache()
    yield
    vr.reset_cache()


# ── Tier 1: CSD keyed directly ───────────────────────────────────────────────

def test_tier1_region(resolver):
    r = resolve_vacancy("Kingston", "ON", "residential")
    assert r.rate == pytest.approx(0.015)
    assert r.tier == 1 and r.stamp == "region"
    assert r.reliability == "a" and r.normal is True
    assert r.attribution == ATTR
    assert r.geo_name == "Kingston (city)"


# ── Tier 2: parent CMA/CA ────────────────────────────────────────────────────

def test_tier2_parent_cma(resolver):
    r = resolve_vacancy("Loyalist", "ON", "multi-family")
    assert r.rate == pytest.approx(0.018)
    assert r.tier == 2 and r.stamp == "parent_cma"
    assert r.reliability == "a" and r.normal is True


# ── Reliability carry + demotion ─────────────────────────────────────────────

def test_reliability_d_demotes_to_provincial(resolver):
    # Brockville CA (512) carries reliability 'd' -> skipped -> falls to provincial.
    r = resolve_vacancy("Brockville", "ON", "residential")
    assert r.tier == 3 and r.stamp == "provincial_avg"
    assert r.rate == pytest.approx(0.024)   # raw ON provincial, not floored to the constant


def test_demotion_is_recorded_not_silent(resolver):
    # The skipped 'd' figure must survive the demotion: grade + region carried forward
    # on the resolution AND visible in the report-row provenance.
    r = resolve_vacancy("Brockville", "ON", "residential")
    assert r.demoted_from == "Brockville CA (rel. d)"          # grade carried forward
    assert "demoted from Brockville CA (rel. d)" in r.provenance()   # row shows it


def test_demotion_can_be_disabled(resolver):
    r = resolve_vacancy("Brockville", "ON", "residential", demote_unreliable=False)
    assert r.tier == 2 and r.stamp == "parent_cma"
    assert r.rate == pytest.approx(0.089) and r.reliability == "d"
    assert r.demoted_from is None                              # no demotion, nothing to record


def test_no_demotion_leaves_demoted_from_null(resolver):
    # A clean tier-1 hit records no demotion.
    assert resolve_vacancy("Kingston", "ON", "residential").demoted_from is None


# ── Tier 3: raw provincial average (NO floor — it is real CMHC data) ─────────

def test_tier3_below_constant_province_is_trusted_raw(resolver):
    # ON provincial 0.024 < 0.03 constant. Tier 3 must NOT floor it to the constant —
    # that would re-create the blanket 3% the pipeline exists to remove.
    r = resolve_vacancy("St. Marys", "ON", "residential")   # CSD outside any CMA/CA
    assert r.tier == 3 and r.stamp == "provincial_avg"
    assert r.rate == pytest.approx(0.024)                   # real figure, not 0.030


def test_tier3_row_flags_derived_unweighted_average(resolver):
    # The provincial figure is a derived unweighted mean of surveyed centres (no official
    # provincial RMS cut) — the report row must say so, not imply an official rate.
    r = resolve_vacancy("St. Marys", "ON", "residential")
    assert "derived: unweighted avg of surveyed centres" in r.provenance()
    # A real surveyed region (tier 1/2) must NOT carry that tag.
    assert "derived" not in resolve_vacancy("Kingston", "ON", "residential").provenance()


def test_tier3_above_constant_province_is_trusted_raw(resolver):
    # NL provincial 0.05 > 0.03 constant — also reported raw (high-vacancy province).
    r = resolve_vacancy("Somewhere", "NL", "residential")
    assert r.tier == 3 and r.stamp == "provincial_avg"
    assert r.rate == pytest.approx(0.050)


def test_unknown_city_known_province_resolves_tier3(resolver):
    r = resolve_vacancy("Nowheresville", "ON", "residential")
    assert r.tier == 3 and r.normal is True


# ── Tier 4: alarm ────────────────────────────────────────────────────────────

def test_tier4_alarm_on_unresolved_province(resolver):
    r = resolve_vacancy("Anywhere", "ZZ", "residential")
    assert r.tier == 4 and r.stamp == "constant_floor"
    assert r.normal is False                       # the tripwire
    # Tier 4 (and ONLY tier 4) floors: max(constant 0.03, national 0.02) -> 0.03.
    assert r.rate == pytest.approx(0.030)


def test_tier4_alarm_when_province_missing_from_table(resolver):
    # MB is a real province but absent from the fixture's provincial table -> alarm.
    r = resolve_vacancy("Brandon", "MB", "residential")
    assert r.tier == 4 and r.normal is False


# ── Commercial domain: per-type default (never an alarm) ─────────────────────

@pytest.mark.parametrize("ptype,expected", [
    ("office", 0.14), ("retail", 0.05), ("industrial", 0.05),
    ("hotel", 0.00), ("Warehouse", 0.05),   # unknown type -> 5% fallback
])
def test_commercial_type_default(resolver, ptype, expected):
    r = resolve_vacancy("Kingston", "ON", ptype)
    assert r.rate == pytest.approx(expected)
    assert r.stamp == "type_default" and r.normal is True
    assert r.reliability is None and r.attribution is None


# ── Name / province normalization (the one name-based hop) ───────────────────

def test_name_hop_is_punctuation_and_case_insensitive(resolver):
    # "st. marys", "St Marys", "ST. MARYS" all fold to the same CSD.
    for city in ("st. marys", "St Marys", "ST. MARYS"):
        assert resolve_vacancy(city, "ON", "residential").tier == 3

def test_case_and_spelled_out_province(resolver):
    assert resolve_vacancy("kingston", "on", "residential").tier == 1
    assert resolve_vacancy("Kingston", "Ontario", "residential").tier == 1


# ── Attribution ──────────────────────────────────────────────────────────────

def test_attribution_string(resolver):
    assert attribution_string() == ATTR
