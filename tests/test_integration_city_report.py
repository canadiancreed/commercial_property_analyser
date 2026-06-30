"""
Integration tests for the city ranking report pipeline.

Exercises the full chain: property dicts → PropertyScorer.score_property()
→ CityRanker.rank() → city result dicts, using no mocks for the core logic.
Verifies the zero-sentinel fix: DOM=0 and price_drop=0 are real values and
must be included in city averages, not silently dropped as "missing".
"""

import json
import math
import pytest

from scoring.scorer import PropertyScorer
from scoring.city_ranker import CityRanker
from analysis.metrics.returns import METRIC_MARKET_STALENESS


# ── Fixtures ──────────────────────────────────────────────────────────────────

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


def _prop(city="Ottawa", province="ON", status="active", asking=500_000,
          cap=7.0, coc=8.0, dscr=1.4, irr=12.0, em=1.8,
          cf=15_000, drop=5.0, dom=90, ptype="Retail"):
    """Build a fully-analysed property dict with explicit metric results."""
    return {
        "city": city, "province": province,
        "asking_price": asking,
        "original_price": asking,
        "status": status,
        "property_type": ptype,
        "results": [
            {"metric": "Cap Rate",          "value": f"{cap}%",        "grade": "GOOD"},
            {"metric": "CoCR",              "value": f"{coc}%",        "grade": "GOOD"},
            {"metric": "DSCR",              "value": f"{dscr}",        "grade": "GOOD"},
            {"metric": "IRR (10-Yr)",       "value": f"{irr}%",        "grade": "GOOD"},
            {"metric": "Equity Multiple",   "value": f"{em}x",         "grade": "GOOD"},
            {"metric": "Annual Cash Flow",  "value": f"${cf}",         "grade": "GOOD"},
            {"metric": "Price Drop %",      "value": f"{drop}%",       "grade": "GOOD"},
            {"metric": METRIC_MARKET_STALENESS, "value": f"{dom} Days","grade": "GOOD"},
            {"metric": "NOI",               "value": "$36,000.00",     "grade": "GOOD"},
        ],
    }


def _unanalysed_prop(city="Ottawa", province="ON", status="active", asking=500_000):
    """Property with no income results — score must be None."""
    return {
        "city": city, "province": province,
        "asking_price": asking,
        "status": status,
        "property_type": "Retail",
        "results": [
            {"metric": "Loan Amount", "value": "$400,000", "grade": "INFO"},
        ],
    }


@pytest.fixture
def ranker(tmp_path):
    store  = _make_store(tmp_path)
    scorer = PropertyScorer(store)
    return CityRanker(scorer)


# ── Zero-sentinel fix ─────────────────────────────────────────────────────────

class TestZeroSentinelFix:
    """Core regression suite for the zero=missing sentinel bug."""

    def test_dom_zero_included_in_average(self, ranker):
        """A property listed today (DOM=0) must pull the city DOM average down."""
        props = [
            _prop(dom=0),    # listed today
            _prop(dom=90),
            _prop(dom=180),
        ]
        result = ranker.rank(props)
        city = result[0]
        # mean([0, 90, 180]) = 90 — if 0 were excluded it would be 135
        assert city["active_days_on_market"] == pytest.approx(90, abs=1)

    def test_price_drop_zero_included_in_average(self, ranker):
        """A property with no price reduction (drop=0) must count in the average."""
        props = [
            _prop(drop=0.0),   # no reduction
            _prop(drop=0.0),
            _prop(drop=15.0),
        ]
        result = ranker.rank(props)
        city = result[0]
        # mean([0, 0, 15]) = 5.0 — if zeros were excluded it would be 15.0
        assert city["active_price_drop"] == pytest.approx(5.0, abs=0.1)

    def test_all_dom_zero_produces_zero_average(self, ranker):
        """City where every listing is fresh (DOM=0 each) must have avg_dom=0."""
        props = [_prop(dom=0), _prop(dom=0), _prop(dom=0)]
        result = ranker.rank(props)
        assert result[0]["active_days_on_market"] == 0

    def test_all_price_drop_zero_produces_zero_average(self, ranker):
        """City where no listing has dropped price must have avg_drop=0."""
        props = [_prop(drop=0.0), _prop(drop=0.0)]
        result = ranker.rank(props)
        assert result[0]["active_price_drop"] == pytest.approx(0.0)

    def test_cf_zero_included_in_average(self, ranker):
        """A break-even property (cf=0) must be counted in avg cash flow."""
        props = [_prop(cf=0), _prop(cf=30_000)]
        result = ranker.rank(props)
        # mean([0, 30000]) = 15000; if 0 excluded → 30000
        assert result[0]["active_cash_flow"] == pytest.approx(15_000, abs=100)


# ── Unanalysed properties ─────────────────────────────────────────────────────

class TestUnanalysedProperties:
    """Properties without income results must not crash the pipeline."""

    def test_unanalysed_only_city_does_not_crash(self, ranker):
        """A city with only unanalysed listings must produce a valid city dict."""
        result = ranker.rank([_unanalysed_prop(), _unanalysed_prop()])
        assert len(result) == 1
        city = result[0]
        assert city["active_deal_score"] == 0          # no data → rounds to 0, not crash
        # No scorable active listing → DOM average is undefined (None), so the
        # report renders "—" rather than a misleading "0d".
        assert city["active_days_on_market"] is None
        assert city["active_price_drop"]  is None or city["active_price_drop"] == 0

    def test_mixed_analysed_and_unanalysed(self, ranker):
        """Unanalysed properties in a city must not dilute the averages."""
        props = [
            _prop(dom=60, drop=5.0, cap=7.0),
            _unanalysed_prop(),                 # no metrics
        ]
        result = ranker.rank(props)
        city = result[0]
        # Only 1 analysed property — averages come from that property alone
        assert city["active_days_on_market"]  == 60
        assert city["active_price_drop"] == pytest.approx(5.0, abs=0.1)
        assert city["active_cap_rate"]  == pytest.approx(7.0, abs=0.1)

    def test_unanalysed_property_best_score_zero(self, ranker):
        """best_score must be 0 (not crash) when no property has a score."""
        result = ranker.rank([_unanalysed_prop()])
        assert result[0]["best_score"] == 0


# ── Average correctness ───────────────────────────────────────────────────────

class TestAverageCorrectness:
    """Spot-check that reported averages match hand-calculated values."""

    def test_cap_rate_average(self, ranker):
        props = [_prop(cap=6.0), _prop(cap=8.0), _prop(cap=10.0)]
        city = ranker.rank(props)[0]
        assert city["active_cap_rate"] == pytest.approx(8.0, abs=0.05)

    def test_coc_average(self, ranker):
        props = [_prop(coc=5.0), _prop(coc=10.0), _prop(coc=15.0)]
        city = ranker.rank(props)[0]
        assert city["active_cash_on_cash"] == pytest.approx(10.0, abs=0.05)

    def test_dom_average(self, ranker):
        props = [_prop(dom=30), _prop(dom=60), _prop(dom=90)]
        city = ranker.rank(props)[0]
        assert city["active_days_on_market"] == pytest.approx(60, abs=1)

    def test_asking_price_average(self, ranker):
        props = [_prop(asking=400_000), _prop(asking=600_000)]
        city = ranker.rank(props)[0]
        assert city["active_avg_price"] == pytest.approx(500_000, abs=500)

    def test_best_score_is_max_not_average(self, ranker):
        props = [_prop(cap=4.0, coc=4.0), _prop(cap=9.0, coc=12.0)]
        city = ranker.rank(props)[0]
        assert city["best_score"] >= city["active_deal_score"]


# ── Active / inactive split ───────────────────────────────────────────────────

class TestActiveInactiveSplit:
    """Active and inactive properties must be aggregated separately."""

    def test_active_and_inactive_counts(self, ranker):
        props = [
            _prop(status="active"),
            _prop(status="active"),
            _prop(status="inactive"),
        ]
        city = ranker.rank(props)[0]
        assert city["active"]   == 2
        assert city["inactive"] == 1
        assert city["total"]    == 3

    def test_inactive_metrics_excluded_from_active_averages(self, ranker):
        props = [
            _prop(status="active",   cap=7.0),
            _prop(status="inactive", cap=99.0),  # must not pollute act_cap
        ]
        city = ranker.rank(props)[0]
        assert city["active_cap_rate"] == pytest.approx(7.0, abs=0.1)

    def test_inact_cap_is_average_of_inactive_only(self, ranker):
        props = [
            _prop(status="active",   cap=5.0),
            _prop(status="inactive", cap=9.0),
            _prop(status="inactive", cap=11.0),
        ]
        city = ranker.rank(props)[0]
        assert city["inactive_cap_rate"] == pytest.approx(10.0, abs=0.1)


# ── Multi-city output ─────────────────────────────────────────────────────────

class TestMultiCity:
    """Properties from different cities must aggregate independently."""

    def test_two_cities_produce_two_results(self, ranker):
        props = [_prop(city="Ottawa"), _prop(city="Kingston")]
        result = ranker.rank(props)
        assert len(result) == 2

    def test_city_averages_are_independent(self, ranker):
        props = [
            _prop(city="Ottawa",   cap=9.0),
            _prop(city="Ottawa",   cap=9.0),
            _prop(city="Kingston", cap=4.0),
            _prop(city="Kingston", cap=4.0),
        ]
        result = ranker.rank(props)
        by_city = {r["city"]: r for r in result}
        assert by_city["Ottawa, ON"]["active_cap_rate"]   == pytest.approx(9.0, abs=0.1)
        assert by_city["Kingston, ON"]["active_cap_rate"]  == pytest.approx(4.0, abs=0.1)

    def test_sorted_by_opportunity(self, ranker):
        """City with better fundamentals must rank above city with poor ones."""
        props = [
            _prop(city="GoodCity",  cap=9.0, coc=12.0, dom=180, drop=15.0),
            _prop(city="GoodCity",  cap=9.0, coc=12.0, dom=180, drop=15.0),
            _prop(city="GoodCity",  cap=9.0, coc=12.0, dom=180, drop=15.0),
            _prop(city="BadCity",   cap=3.0, coc=1.0,  dom=10,  drop=0.0),
            _prop(city="BadCity",   cap=3.0, coc=1.0,  dom=10,  drop=0.0),
            _prop(city="BadCity",   cap=3.0, coc=1.0,  dom=10,  drop=0.0),
        ]
        result = ranker.rank(props)
        assert result[0]["city"].startswith("GoodCity")


# ── Output shape ─────────────────────────────────────────────────────────────

class TestOutputShape:
    """Result dicts must have the expected keys and types — no None in int fields."""

    # Price/cash-flow fields still collapse "no data" to 0 (a $0 average is not a
    # meaningful value anyway, so 0 == missing is acceptable for these).
    INT_FIELDS   = ("active_cash_flow", "active_avg_price", "inactive_avg_price")
    # These distinguish a real 0 from "no data" (None) so the report can render
    # "—" instead of a misleading zero.
    NULLABLE_NUM_FIELDS = ("active_days_on_market", "cap_trend")
    FLOAT_FIELDS = ("active_cap_rate", "active_cash_on_cash", "active_irr", "active_dscr",
                    "active_price_drop", "confidence", "opportunity")

    def test_required_keys_present(self, ranker):
        result = ranker.rank([_prop()])
        city = result[0]
        for key in ("city", "total", "active", "inactive", "confidence",
                    "active_deal_score", "active_cap_rate", "active_cash_on_cash", "active_days_on_market", "active_price_drop",
                    "active_avg_price", "inactive_cap_rate", "best_score", "opportunity",
                    "type_counts", "absorption_rate"):
            assert key in city, f"Missing key: {key}"

    def test_int_fields_are_int_not_none(self, ranker):
        """int() casts must never produce None even when averages have no data."""
        props = [_unanalysed_prop()]   # all metrics missing
        city = ranker.rank(props)[0]
        for field in self.INT_FIELDS:
            assert isinstance(city[field], int), \
                f"{field}={city[field]!r} is not int"

    def test_nullable_num_fields_are_none_when_no_data(self, ranker):
        """Fields where 0 is a real value must be None (not 0) when undefined."""
        city = ranker.rank([_unanalysed_prop()])[0]   # no scorable data, no inactive
        for field in self.NULLABLE_NUM_FIELDS:
            assert city[field] is None, \
                f"{field}={city[field]!r} should be None when undefined"

    def test_nullable_num_fields_are_numeric_when_present(self, ranker):
        """When the data supports them, the nullable fields carry real numbers."""
        props = [_prop(status="active", dom=0, cap=7.0),
                 _prop(status="inactive", cap=6.0)]
        city = ranker.rank(props)[0]
        assert city["active_days_on_market"] == 0      # listed today, a real 0
        assert isinstance(city["cap_trend"], (int, float))

    def test_opportunity_in_range(self, ranker):
        result = ranker.rank([_prop()] * 5)
        assert 0 <= result[0]["opportunity"] <= 100

    def test_confidence_in_range(self, ranker):
        result = ranker.rank([_prop()] * 3)
        assert 0 < result[0]["confidence"] < 1


# ── Outlier screen (implausible estimated rents) ───────────────────────────────

class TestOutlierScreen:
    """Active listings with an impossible cap/CoCR (bad estimated rent) must be
    kept in inventory but dropped from the city's income averages."""

    def test_implausible_cap_excluded_from_average(self, ranker):
        props = [
            _prop(status="active", cap=7.0),
            _prop(status="active", cap=27.0),   # impossible — estimated-rent artifact
        ]
        city = ranker.rank(props)[0]
        assert city["active"] == 2                      # still counted in inventory
        assert city["active_cap_rate"] == pytest.approx(7.0, abs=0.1)  # outlier dropped

    def test_implausible_coc_excluded_from_average(self, ranker):
        props = [
            _prop(status="active", coc=9.0),
            _prop(status="active", coc=80.0),   # impossible CoCR
        ]
        city = ranker.rank(props)[0]
        assert city["active_cash_on_cash"] == pytest.approx(9.0, abs=0.1)

    def test_active_prices_emitted_for_filtering(self, ranker):
        """Individual active asking prices must be emitted (sorted) so the report's
        price filter can match a city on any in-range listing, not the average."""
        props = [
            _prop(status="active",   asking=300_000),
            _prop(status="active",   asking=900_000),
            _prop(status="inactive", asking=500_000),  # sold — not in active_prices
        ]
        city = ranker.rank(props)[0]
        assert city["active_prices"] == [300_000, 900_000]
        # the average (600k) is outside a 250k–350k filter, but the 300k listing
        # is inside — so the city must NOT be filtered out on the average
        assert any(250_000 <= p <= 350_000 for p in city["active_prices"])

    def test_outlier_does_not_inflate_quality(self, ranker):
        clean    = ranker.rank([_prop(status="active", cap=7.0)] * 3)[0]
        with_bad = ranker.rank([_prop(status="active", cap=7.0)] * 3
                               + [_prop(status="active", cap=27.0)])[0]
        # the 27% cap listing is still inventory (so depth/quality count rises is
        # fine), but it must NOT raise the deal-quality sub-score
        assert with_bad["quality_score"] == pytest.approx(clean["quality_score"], abs=0.5)
        assert with_bad["active_cap_rate"] == pytest.approx(7.0, abs=0.1)
