"""
Cross-file tests for PropertyScorer behaviour — issues #12 and #13.

These tests span scorer.py and the data layer (DataStore + JSON distance files),
which is why they don't belong inside a single metric-class test file.
"""

import json
import pytest

from scoring.scorer import PropertyScorer
from analysis.metrics.returns import METRIC_MARKET_STALENESS


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_store(tmp_path):
    from data.store import DataStore
    comm  = str(tmp_path / "comm.json")
    res   = str(tmp_path / "res.json")
    props = str(tmp_path / "props.json")
    miss  = str(tmp_path / "miss.json")
    for p, d in [(comm, {"cities": {}}), (res, {"cities": {}})]:
        with open(p, "w") as f:
            json.dump(d, f)
    return DataStore(commercial_path=comm, residential_path=res,
                     properties_path=props, missing_path=miss)


def _full_record(city="Ottawa", dom_label=METRIC_MARKET_STALENESS, dom_value="90 Days"):
    return {
        "city": city, "province": "ON",
        "asking_price": 500_000, "original_price": 530_000,
        "interest_rate": 0.055, "down_payment_pct": 0.25,
        "annual_rent": 60_000, "commercial_rent": 60_000, "residential_rent": 0,
        "results": [
            {"metric": "Cap Rate",         "value": "7.0%",       "grade": "GOOD"},
            {"metric": "CoCR",             "value": "8.0%",       "grade": "GOOD"},
            {"metric": "DSCR",             "value": "1.4",        "grade": "GOOD"},
            {"metric": "IRR (10-Yr)",      "value": "12.0%",      "grade": "GOOD"},
            {"metric": "Equity Multiple",  "value": "1.8x",       "grade": "GOOD"},
            {"metric": "Annual Cash Flow", "value": "$15000",     "grade": "GOOD"},
            {"metric": "Price Drop %",     "value": "5.0%",       "grade": "GOOD"},
            {"metric": dom_label,          "value": dom_value,    "grade": "GOOD"},
            {"metric": "NOI",              "value": "$36,000.00", "grade": "GOOD"},
        ],
    }


# ── Issue #12: DOM score must not silently drop to 0 when metric label changes ─

class TestDOMStringLookup:

    def test_dom_constant_wired_end_to_end(self, tmp_path):
        """METRIC_MARKET_STALENESS is the shared key — scorer and emitter both use it."""
        store  = _make_store(tmp_path)
        scorer = PropertyScorer(store)
        score  = scorer.score_property(_full_record(dom_label=METRIC_MARKET_STALENESS,
                                                    dom_value="90 Days"))["score"]
        assert score is not None and score > 0



# ── Issue #13: city with no distance data scores Location=0 ──────────────────

class TestUnknownCityLocationScore:

    def test_unknown_city_location_component_is_zero(self, tmp_path):
        """A city with no distance data scores Location=0 — intentional, not a bug."""
        store  = _make_store(tmp_path)
        scorer = PropertyScorer(store)
        loc    = scorer.score_property(_full_record(city="Smallville"))["breakdown"].get("Location", -1)
        assert loc == 0.0, f"Expected Location=0 for unknown city, got {loc}"

    def test_two_unknown_cities_score_identically(self, tmp_path):
        """Two properties with different unknown cities must produce equal scores."""
        store  = _make_store(tmp_path)
        scorer = PropertyScorer(store)
        s_a    = scorer.score_property(_full_record(city="Smallville"))["score"]
        s_b    = scorer.score_property(_full_record(city="Unknownburg"))["score"]
        assert s_a == pytest.approx(s_b, abs=0.1)

    def test_unknown_city_zero_when_distances_file_present(self, tmp_path):
        """A city absent from the distances file scores 0 even when other cities have data."""
        dist_path = str(tmp_path / "city_distances.json")
        with open(dist_path, "w") as f:
            json.dump({"ottawa": {"distance_km": 5, "nearest_centre": "Ottawa"}}, f)

        import scoring.scorer as scorer_mod
        original = scorer_mod.CITY_DISTANCES_PATH
        scorer_mod.CITY_DISTANCES_PATH = dist_path
        try:
            store  = _make_store(tmp_path)
            scorer = PropertyScorer(store)
            loc    = scorer.score_property(_full_record(city="Smallville"))["breakdown"].get("Location", -1)
        finally:
            scorer_mod.CITY_DISTANCES_PATH = original

        assert loc == 0.0, f"Expected Location=0 for city absent from distances file, got {loc}"
