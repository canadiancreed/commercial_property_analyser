import pytest
from unittest.mock import MagicMock, patch
from scoring.city_ranker import CityRanker


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_scorer(score=50.0, cap=7.0, coc=8.0, irr=10.0, dscr=1.4,
                 cf=12_000, drop=5.0, dom=90):
    scorer = MagicMock()
    scorer.load_config.return_value = {
        "confidence_k": 5,
        "city_score_weights": {},
        "city_score_thresholds": {},
    }
    scorer.load_city_demographics.return_value = {}
    scorer.score_property.return_value = {
        "score": score,
        "cap_rate": cap, "coc": coc, "irr": irr, "dscr": dscr,
        "cf_annual": cf, "price_drop": drop, "dom": dom,
    }
    return scorer


def _props(cities, status="active", asking=500_000, ptype="Retail"):
    return [
        {"address": f"{i} Main St, {c}", "city": c, "province": "ON",
         "status": status, "asking_price": asking, "property_type": ptype}
        for i, c in enumerate(cities)
    ]


# ── Basic ranking ─────────────────────────────────────────────────────────────

class TestCityRanker:
    def test_returns_list(self):
        ranker = CityRanker(_make_scorer())
        result = ranker.rank(_props(["Ottawa", "Kingston"]))
        assert isinstance(result, list)

    def test_two_cities_two_entries(self):
        ranker = CityRanker(_make_scorer())
        result = ranker.rank(_props(["Ottawa", "Kingston"]))
        cities = {r["city"] for r in result}
        assert "Ottawa, ON" in cities
        assert "Kingston, ON" in cities

    def test_same_city_grouped(self):
        ranker = CityRanker(_make_scorer())
        props = _props(["Ottawa", "Ottawa", "Ottawa"])
        result = ranker.rank(props)
        assert len(result) == 1
        assert result[0]["total"] == 3

    def test_sorted_by_opportunity_desc(self):
        scorer = _make_scorer()
        # Give Ottawa a perfect score and Kingston a poor score
        def side_effect(p):
            if "Ottawa" in p.get("city", ""):
                return {"score": 90, "cap_rate": 9, "coc": 12, "irr": 20,
                        "dscr": 2.0, "cf_annual": 50_000, "price_drop": 15, "dom": 180}
            return {"score": 10, "cap_rate": 2, "coc": 0, "irr": 1,
                    "dscr": 0.5, "cf_annual": -5_000, "price_drop": 0, "dom": 0}

        scorer.score_property.side_effect = side_effect
        ranker = CityRanker(scorer)
        props = _props(["Ottawa", "Kingston"])
        result = ranker.rank(props)
        assert result[0]["city"].startswith("Ottawa")

    def test_active_vs_inactive_split(self):
        scorer = _make_scorer()
        scorer.score_property.return_value = {
            "score": 50, "cap_rate": 6, "coc": 6, "irr": 8,
            "dscr": 1.2, "cf_annual": 8000, "price_drop": 3, "dom": 60,
        }
        ranker = CityRanker(scorer)
        props = [
            {"city": "Ottawa", "province": "ON", "status": "active",
             "asking_price": 500_000, "property_type": "Retail"},
            {"city": "Ottawa", "province": "ON", "status": "inactive",
             "asking_price": 480_000, "property_type": "Retail"},
        ]
        result = ranker.rank(props)
        assert result[0]["active"] == 1
        assert result[0]["inactive"] == 1

    def test_confidence_formula(self):
        # confidence = n / (n + k), k=5
        scorer = _make_scorer()
        ranker = CityRanker(scorer)
        result = ranker.rank(_props(["Ottawa"] * 5))
        # n=5, k=5 → confidence = 5/10 = 0.5
        assert result[0]["confidence"] == pytest.approx(0.5)

    def test_confidence_emitted_but_does_not_inflate_score(self):
        scorer = _make_scorer()  # empty city weights -> no quality earned
        result = CityRanker(scorer).rank(_props(["Tiny Town"]))
        # confidence is still reported as n/(n+k) for context (display only)
        assert result[0]["confidence"] == pytest.approx(1 / (1 + 5), abs=0.01)
        # but it no longer props a thin, weight-less city up toward a 50 prior
        assert result[0]["opportunity"] < 20

    def test_no_properties_returns_empty(self):
        ranker = CityRanker(_make_scorer())
        assert ranker.rank([]) == []

    def test_type_counts_populated(self):
        scorer = _make_scorer()
        ranker = CityRanker(scorer)
        props = [
            {"city": "Ottawa", "province": "ON", "status": "active",
             "asking_price": 500_000, "property_type": "Retail"},
            {"city": "Ottawa", "province": "ON", "status": "active",
             "asking_price": 500_000, "property_type": "Office"},
        ]
        result = ranker.rank(props)
        tc = result[0]["type_counts"]
        assert tc["Retail"] == 1
        assert tc["Office"] == 1

    def test_demographics_factored_in(self):
        scorer = _make_scorer()
        scorer.load_city_demographics.return_value = {
            "ottawa": {"population": 1_000_000, "growth_pct_annual": 2.0}
        }
        ranker = CityRanker(scorer)
        result = ranker.rank(_props(["Ottawa"]))
        assert result[0]["has_demo"] is True
        assert result[0]["population"] == 1_000_000

    def test_best_score_is_max(self):
        scorer = MagicMock()
        scorer.load_config.return_value = {"confidence_k": 5, "city_score_weights": {}, "city_score_thresholds": {}}
        scorer.load_city_demographics.return_value = {}
        scores = [70, 40, 85]
        scorer.score_property.side_effect = [
            {"score": s, "cap_rate": 6, "coc": 5, "irr": 8, "dscr": 1.2,
             "cf_annual": 5000, "price_drop": 3, "dom": 60}
            for s in scores
        ]
        ranker = CityRanker(scorer)
        props = [{"city": "Ottawa", "province": "ON", "status": "active",
                  "asking_price": 500_000, "property_type": "Retail"}] * 3
        result = ranker.rank(props)
        assert result[0]["best_score"] == pytest.approx(85.0)

    def test_avg_helper(self):
        ranker = CityRanker(MagicMock())
        entries = [{"cap_rate": 6}, {"cap_rate": 8}, {"cap_rate": 7}]
        assert ranker._avg(entries, "cap_rate") == pytest.approx(7.0)

    def test_avg_includes_zeros(self):
        # 0 is a real value (e.g. DOM=0 listed today, price_drop=0 no reduction)
        ranker = CityRanker(MagicMock())
        entries = [{"cap_rate": 0}, {"cap_rate": 6}]
        assert ranker._avg(entries, "cap_rate") == pytest.approx(3.0)

    def test_avg_excludes_none(self):
        # None means "not computed" — must be excluded
        ranker = CityRanker(MagicMock())
        entries = [{"cap_rate": None}, {"cap_rate": 6}]
        assert ranker._avg(entries, "cap_rate") == pytest.approx(6.0)

    def test_avg_empty_list_returns_none(self):
        ranker = CityRanker(MagicMock())
        assert ranker._avg([], "cap_rate") is None

    def test_norm_clamps_below_zero(self):
        ranker = CityRanker(MagicMock())
        assert ranker._norm(-10, 0, 100) == 0.0

    def test_norm_clamps_above_one(self):
        ranker = CityRanker(MagicMock())
        assert ranker._norm(200, 0, 100) == 1.0

    def test_norm_midpoint(self):
        ranker = CityRanker(MagicMock())
        assert ranker._norm(50, 0, 100) == pytest.approx(0.5)

    def test_norm_equal_lo_hi(self):
        ranker = CityRanker(MagicMock())
        assert ranker._norm(5, 5, 5) == 0.0

    def test_whitespace_only_type_not_counted(self):

        """Line 114->112: property_type='   ' → strip() = '' → if t: is False → skipped."""
        scorer = _make_scorer()
        ranker = CityRanker(scorer)
        props = [
            {"city": "Ottawa", "province": "ON", "status": "active",
             "asking_price": 500_000, "property_type": "Retail"},
            {"city": "Ottawa", "province": "ON", "status": "active",
             "asking_price": 500_000, "property_type": "   "},  # whitespace-only
        ]
        result = ranker.rank(props)
        tc = result[0]["type_counts"]
        # whitespace-only type must NOT appear in type_counts
        assert "   " not in tc
        assert "" not in tc
        # The valid type is still counted
        assert tc.get("Retail") == 1


# ── Config-driven weights and thresholds ──────────────────────────────────────

def _make_scorer_with_config(city_score_weights, city_score_thresholds, **kwargs):
    scorer = _make_scorer(**kwargs)
    scorer.load_config.return_value = {
        "confidence_k": 5,
        "city_score_weights":    city_score_weights,
        "city_score_thresholds": city_score_thresholds,
    }
    return scorer


class TestCityRankerConfig:
    def test_zero_weight_excludes_metric(self):
        """A metric with weight=0 contributes nothing to raw score."""
        weights = {
            "act_cap": 1.0, "act_coc": 0.0, "n_active": 0.0,
            "act_drop": 0.0, "act_dom": 0.0, "inact_cap": 0.0,
            "cap_trend": 0.0, "pop_score": 0.0, "growth_score": 0.0,
            "absorption_rate": 0.0, "price_trend": 0.0,
        }
        thresholds = {"act_cap": [3.0, 9.0]}
        scorer = _make_scorer_with_config(weights, thresholds, cap=9.0)
        ranker = CityRanker(scorer)
        result = ranker.rank(_props(["Ottawa"] * 10))
        # cap=9 → norm=1.0, weight=1.0 → raw=100; confidence=10/15≈0.67
        # opp = 100 * 0.67 + 50 * 0.33 ≈ 83
        assert result[0]["opportunity"] > 75

    def test_custom_cap_rate_threshold_changes_score(self):
        """Raising the cap rate ceiling should lower the score for the same cap rate."""
        base_thresh  = {"act_cap": [3.0, 9.0]}
        higher_thresh = {"act_cap": [3.0, 18.0]}
        weights = {"act_cap": 1.0, "act_coc": 0.0, "n_active": 0.0,
                   "act_drop": 0.0, "act_dom": 0.0, "inact_cap": 0.0,
                   "cap_trend": 0.0, "pop_score": 0.0, "growth_score": 0.0,
                   "absorption_rate": 0.0, "price_trend": 0.0}

        scorer_base   = _make_scorer_with_config(weights, base_thresh,   cap=9.0)
        scorer_higher = _make_scorer_with_config(weights, higher_thresh, cap=9.0)

        props = _props(["Ottawa"] * 10)
        opp_base   = CityRanker(scorer_base).rank(props)[0]["opportunity"]
        opp_higher = CityRanker(scorer_higher).rank(props)[0]["opportunity"]
        assert opp_base > opp_higher

    def test_dom_threshold_starts_at_zero(self):
        """DOM=15 should score > 0 with the standardised [0,180] threshold."""
        weights = {"act_cap": 0.0, "act_coc": 0.0, "n_active": 0.0,
                   "act_drop": 0.0, "act_dom": 1.0, "inact_cap": 0.0,
                   "cap_trend": 0.0, "pop_score": 0.0, "growth_score": 0.0,
                   "absorption_rate": 0.0, "price_trend": 0.0}
        thresholds = {"act_dom": [0.0, 180.0]}
        scorer = _make_scorer_with_config(weights, thresholds, dom=15)
        ranker = CityRanker(scorer)
        result = ranker.rank(_props(["Ottawa"] * 10))
        assert result[0]["opportunity"] > 0

    def test_dom_low_value_scores_higher_with_zero_floor_than_thirty(self):
        """DOM=15 scores more with floor=0 than the old floor=30 (which gave 0)."""
        weights = {"act_cap": 0.0, "act_coc": 0.0, "n_active": 0.0,
                   "act_drop": 0.0, "act_dom": 1.0, "inact_cap": 0.0,
                   "cap_trend": 0.0, "pop_score": 0.0, "growth_score": 0.0,
                   "absorption_rate": 0.0, "price_trend": 0.0}

        scorer_new = _make_scorer_with_config(weights, {"act_dom": [0.0, 180.0]}, dom=15)
        scorer_old = _make_scorer_with_config(weights, {"act_dom": [30.0, 180.0]}, dom=15)

        props = _props(["Ottawa"] * 10)
        opp_new = CityRanker(scorer_new).rank(props)[0]["opportunity"]
        opp_old = CityRanker(scorer_old).rank(props)[0]["opportunity"]
        assert opp_new > opp_old

    def test_pop_score_zero_when_weight_missing_from_config(self):
        """pop_score must not contribute when city_score_weights has no 'pop_score' key."""
        weights_no_demo = {
            "act_cap": 1.0, "act_coc": 0.0, "n_active": 0.0,
            "act_drop": 0.0, "act_dom": 0.0, "inact_cap": 0.0,
            "cap_trend": 0.0, "absorption_rate": 0.0, "price_trend": 0.0,
            # pop_score and growth_score intentionally absent
        }
        weights_with_demo = {**weights_no_demo, "pop_score": 0.05, "growth_score": 0.05}
        thresholds = {"act_cap": [3.0, 9.0]}

        # cap below ceiling so the (renormalised) demographic factors can lift the
        # score rather than just diluting an already-maxed quality.
        scorer_no   = _make_scorer_with_config(weights_no_demo,   thresholds, cap=6.0)
        scorer_with = _make_scorer_with_config(weights_with_demo, thresholds, cap=6.0)
        for s in (scorer_no, scorer_with):
            s.load_city_demographics.return_value = {
                "ottawa": {"population": 1_000_000, "growth_pct_annual": 5.0}
            }

        props = _props(["Ottawa"] * 10)
        opp_no   = CityRanker(scorer_no).rank(props)[0]["opportunity"]
        opp_with = CityRanker(scorer_with).rank(props)[0]["opportunity"]
        # Without the keys the demographic boost must be absent
        assert opp_no < opp_with

    def test_growth_score_zero_when_weight_missing_from_config(self):
        """growth_score must not contribute when city_score_weights has no 'growth_score' key."""
        weights_no_growth = {
            "act_cap": 0.0, "act_coc": 0.0, "n_active": 0.0,
            "act_drop": 0.0, "act_dom": 0.0, "inact_cap": 0.0,
            "cap_trend": 0.0, "absorption_rate": 0.0, "price_trend": 0.0,
            "pop_score": 0.0,
            # growth_score intentionally absent
        }
        weights_with_growth = {**weights_no_growth, "growth_score": 0.1}
        thresholds = {}

        scorer_no   = _make_scorer_with_config(weights_no_growth,   thresholds)
        scorer_with = _make_scorer_with_config(weights_with_growth, thresholds)
        for s in (scorer_no, scorer_with):
            s.load_city_demographics.return_value = {
                "ottawa": {"population": 500_000, "growth_pct_annual": 5.0}
            }

        props = _props(["Ottawa"] * 10)
        opp_no   = CityRanker(scorer_no).rank(props)[0]["opportunity"]
        opp_with = CityRanker(scorer_with).rank(props)[0]["opportunity"]
        assert opp_no < opp_with

    def test_weights_sum_to_one_produces_score_in_range(self):
        """Weights from score_weights.json (sum=1.0) with mid-range inputs should produce 0–100."""
        import json
        with open("json/score_weights.json") as f:
            file_cfg = json.load(f)
        weights    = file_cfg["city_score_weights"]
        thresholds = file_cfg["city_score_thresholds"]
        scorer = _make_scorer_with_config(weights, thresholds,
                                          cap=6.0, coc=6.0, dom=90, drop=7.0)
        scorer.load_city_demographics.return_value = {
            "ottawa": {"population": 500_000, "growth_pct_annual": 1.5}
        }
        ranker = CityRanker(scorer)
        result = ranker.rank(_props(["Ottawa"] * 10))
        opp = result[0]["opportunity"]
        assert 0 <= opp <= 100

    def test_quality_counts_fully_regardless_of_size(self):
        """A great single listing scores the same quality as a great large market.

        Quality is renormalised and size-independent — depth is separate — so a
        good listing buoys a small market and a large one alike."""
        weights    = {"act_cap": 1.0}
        thresholds = {"act_cap": [3.0, 9.0]}
        scorer = _make_scorer_with_config(weights, thresholds, cap=9.0)  # cap at ceiling
        scorer.load_config.return_value["opportunity_depth_share"] = 0.0  # isolate quality
        small = CityRanker(scorer).rank(_props(["Tiny"]))[0]["opportunity"]
        large = CityRanker(scorer).rank(_props(["Big"] * 30))[0]["opportunity"]
        assert small == pytest.approx(large, abs=0.1)
        assert small == pytest.approx(100.0, abs=0.1)  # full quality, no shrinkage

    def test_larger_market_beats_smaller_all_else_equal(self):
        """With a depth premium, identical metrics rank the larger market higher."""
        weights    = {"act_cap": 1.0}
        thresholds = {"act_cap": [3.0, 9.0]}
        scorer = _make_scorer_with_config(weights, thresholds, cap=6.0)
        scorer.load_config.return_value["opportunity_depth_share"] = 0.2
        scorer.load_config.return_value["opportunity_depth_ref"]   = 50
        small = CityRanker(scorer).rank(_props(["Tiny"] * 2))[0]["opportunity"]
        large = CityRanker(scorer).rank(_props(["Big"] * 40))[0]["opportunity"]
        assert large > small

    def test_thin_market_cannot_outrank_via_depth(self):
        """A 1-listing market earns almost no depth premium even at full quality."""
        weights    = {"act_cap": 1.0}
        thresholds = {"act_cap": [3.0, 9.0]}
        scorer = _make_scorer_with_config(weights, thresholds, cap=9.0)
        scorer.load_config.return_value["opportunity_depth_share"] = 0.2
        scorer.load_config.return_value["opportunity_depth_ref"]   = 50
        result = CityRanker(scorer).rank(_props(["Tiny"]))[0]
        # quality maxes at 80 (the 20% depth share is nearly all unearned at n=1)
        assert result["opportunity"] < 85

    def test_production_config_is_depth_focused(self):
        """score_weights.json must allocate a market-depth premium (and no stale prior)."""
        import json
        with open("json/score_weights.json") as f:
            cfg = json.load(f)
        assert cfg.get("opportunity_depth_share", 0) > 0, "depth premium share missing"
        assert cfg.get("opportunity_depth_ref", 0) > 1, "depth reference count missing"
        assert "opportunity_prior" not in cfg, "stale shrinkage prior should be removed"


# ── Absorption rate ───────────────────────────────────────────────────────────

class TestAbsorptionRate:
    def _ranker(self, absorption_weight=1.0, lo=0.0, hi=0.8):
        weights = {k: 0.0 for k in [
            "act_cap", "act_coc", "n_active", "act_drop", "act_dom",
            "inact_cap", "cap_trend", "price_trend", "pop_score", "growth_score",
        ]}
        weights["absorption_rate"] = absorption_weight
        thresholds = {"absorption_rate": [lo, hi]}
        return CityRanker(_make_scorer_with_config(weights, thresholds))

    def _mixed_props(self, n_active, n_inactive, asking_active=500_000, asking_inactive=480_000):
        props = []
        for i in range(n_active):
            props.append({"city": "Ottawa", "province": "ON", "status": "active",
                          "asking_price": asking_active, "property_type": "Retail"})
        for i in range(n_inactive):
            props.append({"city": "Ottawa", "province": "ON", "status": "inactive",
                          "asking_price": asking_inactive, "property_type": "Retail"})
        return props

    def test_absorption_rate_in_output(self):
        ranker = CityRanker(_make_scorer())
        result = ranker.rank(self._mixed_props(3, 1))
        assert "absorption_rate" in result[0]

    def test_absorption_rate_value(self):
        ranker = CityRanker(_make_scorer())
        result = ranker.rank(self._mixed_props(3, 1))
        # 1 inactive out of 4 total = 0.25
        assert result[0]["absorption_rate"] == pytest.approx(0.25)

    def test_absorption_rate_all_active(self):
        ranker = CityRanker(_make_scorer())
        result = ranker.rank(_props(["Ottawa"] * 4))
        assert result[0]["absorption_rate"] == pytest.approx(0.0)

    def test_absorption_rate_all_inactive(self):
        ranker = CityRanker(_make_scorer())
        result = ranker.rank(self._mixed_props(0, 4))
        assert result[0]["absorption_rate"] == pytest.approx(1.0)

    def test_higher_absorption_scores_higher(self):
        """More sold listings relative to total should increase opportunity."""
        ranker = self._ranker()
        low_absorption  = self._mixed_props(9, 1)   # 0.1
        high_absorption = self._mixed_props(1, 9)   # 0.9 (clamped to 1.0 at hi=0.8)
        opp_low  = ranker.rank(low_absorption)[0]["opportunity"]
        opp_high = ranker.rank(high_absorption)[0]["opportunity"]
        assert opp_high > opp_low

    def test_absorption_rate_threshold_configurable(self):
        """Raising hi threshold should lower score for the same absorption rate."""
        ranker_tight = self._ranker(lo=0.0, hi=0.5)
        ranker_wide  = self._ranker(lo=0.0, hi=1.0)
        props = self._mixed_props(5, 5)  # absorption = 0.5
        opp_tight = ranker_tight.rank(props)[0]["opportunity"]
        opp_wide  = ranker_wide.rank(props)[0]["opportunity"]
        assert opp_tight > opp_wide

    def test_absorption_rate_weight_zero_no_contribution(self):
        """absorption_rate with weight=0 should not affect score."""
        ranker_on  = self._ranker(absorption_weight=0.5)
        ranker_off = self._ranker(absorption_weight=0.0)
        props = self._mixed_props(1, 9)
        opp_on  = ranker_on.rank(props)[0]["opportunity"]
        opp_off = ranker_off.rank(props)[0]["opportunity"]
        assert opp_on > opp_off


# ── Price trend ───────────────────────────────────────────────────────────────

class TestPriceTrend:
    def _ranker(self, price_trend_weight=1.0, lo=-10.0, hi=15.0):
        weights = {k: 0.0 for k in [
            "act_cap", "act_coc", "n_active", "act_drop", "act_dom",
            "inact_cap", "cap_trend", "absorption_rate", "pop_score", "growth_score",
        ]}
        weights["price_trend"] = price_trend_weight
        thresholds = {"price_trend": [lo, hi]}
        return CityRanker(_make_scorer_with_config(weights, thresholds))

    def _props_with_prices(self, act_price, inact_price):
        return [
            {"city": "Ottawa", "province": "ON", "status": "active",
             "asking_price": act_price, "property_type": "Retail"},
            {"city": "Ottawa", "province": "ON", "status": "inactive",
             "asking_price": inact_price, "property_type": "Retail"},
        ]

    def test_price_trend_in_output(self):
        ranker = CityRanker(_make_scorer())
        props = self._props_with_prices(520_000, 500_000)
        result = ranker.rank(props)
        assert "price_trend" in result[0]

    def test_price_trend_positive_when_active_higher(self):
        ranker = CityRanker(_make_scorer())
        props = self._props_with_prices(520_000, 500_000)
        result = ranker.rank(props)
        assert result[0]["price_trend"] == pytest.approx(4.0)

    def test_price_trend_negative_when_active_lower(self):
        ranker = CityRanker(_make_scorer())
        props = self._props_with_prices(480_000, 500_000)
        result = ranker.rank(props)
        assert result[0]["price_trend"] == pytest.approx(-4.0)

    def test_price_trend_zero_when_no_inactive(self):
        ranker = CityRanker(_make_scorer())
        result = ranker.rank(_props(["Ottawa"] * 3))
        assert result[0]["price_trend"] == pytest.approx(0.0)

    def test_appreciating_market_scores_higher(self):
        """Active prices above sold should score higher than the reverse."""
        ranker = self._ranker()
        appreciating = self._props_with_prices(550_000, 500_000)  # +10%
        softening    = self._props_with_prices(450_000, 500_000)  # -10%
        opp_app = ranker.rank(appreciating)[0]["opportunity"]
        opp_sof = ranker.rank(softening)[0]["opportunity"]
        assert opp_app > opp_sof

    def test_price_trend_threshold_configurable(self):
        """Raising hi threshold should lower score for the same price trend."""
        ranker_tight = self._ranker(lo=-10.0, hi=10.0)
        ranker_wide  = self._ranker(lo=-10.0, hi=30.0)
        props = self._props_with_prices(550_000, 500_000)  # +10%
        opp_tight = ranker_tight.rank(props)[0]["opportunity"]
        opp_wide  = ranker_wide.rank(props)[0]["opportunity"]
        assert opp_tight > opp_wide

    def test_price_trend_weight_zero_no_contribution(self):
        weights_on  = {"price_trend": 0.5, **{k: 0.0 for k in [
            "act_cap", "act_coc", "n_active", "act_drop", "act_dom",
            "inact_cap", "cap_trend", "absorption_rate", "pop_score", "growth_score",
        ]}}
        weights_off = {**weights_on, "price_trend": 0.0}
        thresh = {"price_trend": [-10.0, 15.0]}
        props = self._props_with_prices(580_000, 500_000)
        opp_on  = CityRanker(_make_scorer_with_config(weights_on,  thresh)).rank(props)[0]["opportunity"]
        opp_off = CityRanker(_make_scorer_with_config(weights_off, thresh)).rank(props)[0]["opportunity"]
        assert opp_on > opp_off


# ── IRR / DSCR / Cash Flow ────────────────────────────────────────────────────

def _zero_weights(*extras):
    """All weights zero except the keys in extras (set to 1.0)."""
    keys = [
        "act_cap", "act_coc", "act_irr", "act_dscr", "act_cf",
        "n_active", "act_drop", "act_dom", "inact_cap", "cap_trend",
        "absorption_rate", "price_trend", "pop_score", "growth_score",
    ]
    w = {k: 0.0 for k in keys}
    for k in extras:
        w[k] = 1.0
    return w


class TestIrrDscrCf:
    def test_irr_higher_scores_higher(self):
        thresh = {"act_irr": [8.0, 20.0]}
        scorer_lo = _make_scorer_with_config(_zero_weights("act_irr"), thresh, irr=8.0)
        scorer_hi = _make_scorer_with_config(_zero_weights("act_irr"), thresh, irr=20.0)
        props = _props(["Ottawa"] * 10)
        opp_lo = CityRanker(scorer_lo).rank(props)[0]["opportunity"]
        opp_hi = CityRanker(scorer_hi).rank(props)[0]["opportunity"]
        assert opp_hi > opp_lo

    def test_irr_weight_zero_no_contribution(self):
        thresh = {"act_irr": [8.0, 20.0]}
        scorer_on  = _make_scorer_with_config(_zero_weights("act_irr"), thresh, irr=20.0)
        scorer_off = _make_scorer_with_config(_zero_weights(),           thresh, irr=20.0)
        props = _props(["Ottawa"] * 10)
        opp_on  = CityRanker(scorer_on).rank(props)[0]["opportunity"]
        opp_off = CityRanker(scorer_off).rank(props)[0]["opportunity"]
        assert opp_on > opp_off

    def test_irr_threshold_configurable(self):
        """Raising hi threshold should lower score for the same IRR."""
        scorer_tight = _make_scorer_with_config(_zero_weights("act_irr"), {"act_irr": [8.0, 15.0]}, irr=15.0)
        scorer_wide  = _make_scorer_with_config(_zero_weights("act_irr"), {"act_irr": [8.0, 30.0]}, irr=15.0)
        props = _props(["Ottawa"] * 10)
        opp_tight = CityRanker(scorer_tight).rank(props)[0]["opportunity"]
        opp_wide  = CityRanker(scorer_wide).rank(props)[0]["opportunity"]
        assert opp_tight > opp_wide

    def test_dscr_higher_scores_higher(self):
        thresh = {"act_dscr": [1.0, 1.5]}
        scorer_lo = _make_scorer_with_config(_zero_weights("act_dscr"), thresh, dscr=1.0)
        scorer_hi = _make_scorer_with_config(_zero_weights("act_dscr"), thresh, dscr=1.5)
        props = _props(["Ottawa"] * 10)
        opp_lo = CityRanker(scorer_lo).rank(props)[0]["opportunity"]
        opp_hi = CityRanker(scorer_hi).rank(props)[0]["opportunity"]
        assert opp_hi > opp_lo

    def test_dscr_weight_zero_no_contribution(self):
        thresh = {"act_dscr": [1.0, 1.5]}
        scorer_on  = _make_scorer_with_config(_zero_weights("act_dscr"), thresh, dscr=1.5)
        scorer_off = _make_scorer_with_config(_zero_weights(),           thresh, dscr=1.5)
        props = _props(["Ottawa"] * 10)
        opp_on  = CityRanker(scorer_on).rank(props)[0]["opportunity"]
        opp_off = CityRanker(scorer_off).rank(props)[0]["opportunity"]
        assert opp_on > opp_off

    def test_dscr_below_floor_scores_zero(self):
        """DSCR below lo threshold → norm clamps to 0 → quality 0; with no depth share, opp 0."""
        thresh = {"act_dscr": [1.0, 1.5]}
        scorer = _make_scorer_with_config(_zero_weights("act_dscr"), thresh, dscr=0.5)
        scorer.load_config.return_value["opportunity_depth_share"] = 0.0
        result = CityRanker(scorer).rank(_props(["Ottawa"]))
        assert result[0]["opportunity"] == pytest.approx(0.0, abs=0.5)

    def test_cf_higher_scores_higher(self):
        thresh = {"act_cf": [0.0, 50_000.0]}
        scorer_lo = _make_scorer_with_config(_zero_weights("act_cf"), thresh, cf=0)
        scorer_hi = _make_scorer_with_config(_zero_weights("act_cf"), thresh, cf=50_000)
        props = _props(["Ottawa"] * 10)
        opp_lo = CityRanker(scorer_lo).rank(props)[0]["opportunity"]
        opp_hi = CityRanker(scorer_hi).rank(props)[0]["opportunity"]
        assert opp_hi > opp_lo

    def test_cf_weight_zero_no_contribution(self):
        thresh = {"act_cf": [0.0, 50_000.0]}
        scorer_on  = _make_scorer_with_config(_zero_weights("act_cf"), thresh, cf=50_000)
        scorer_off = _make_scorer_with_config(_zero_weights(),         thresh, cf=50_000)
        props = _props(["Ottawa"] * 10)
        opp_on  = CityRanker(scorer_on).rank(props)[0]["opportunity"]
        opp_off = CityRanker(scorer_off).rank(props)[0]["opportunity"]
        assert opp_on > opp_off

    def test_all_three_together_score_in_range(self):
        """IRR + DSCR + CF combined with mid-range inputs should produce 0–100."""
        weights = {**_zero_weights("act_irr", "act_dscr", "act_cf"),
                   "act_irr": 0.4, "act_dscr": 0.35, "act_cf": 0.25}
        thresholds = {"act_irr": [8.0, 20.0], "act_dscr": [1.0, 1.5], "act_cf": [0.0, 50_000.0]}
        scorer = _make_scorer_with_config(weights, thresholds, irr=14.0, dscr=1.25, cf=25_000)
        result = CityRanker(scorer).rank(_props(["Ottawa"] * 10))
        opp = result[0]["opportunity"]
        assert 0 <= opp <= 100

    def test_inact_cap_ceiling_is_10_in_json(self):
        """score_weights.json inact_cap hi threshold must be 10.0."""
        import json
        with open("json/score_weights.json") as f:
            cfg = json.load(f)
        lo, hi = cfg["city_score_thresholds"]["inact_cap"]
        assert hi == pytest.approx(10.0), f"Expected 10.0, got {hi}"

    def test_inact_cap_threshold_affects_score(self):
        """Lowering the inact_cap ceiling should raise the score for the same cap rate value."""
        w = {**_zero_weights("inact_cap"), "inact_cap": 1.0}
        # A 7% inactive cap rate scores higher against a tight [3,8] ceiling than a wide [3,12]
        thresh_tight = {"inact_cap": [3.0,  8.0]}
        thresh_wide  = {"inact_cap": [3.0, 12.0]}
        # Mix: 5 active + 5 inactive, inactive cap_rate drives inact_cap
        active_props   = _props(["Ottawa"] * 5, status="active")
        inactive_props = _props(["Ottawa"] * 5, status="inactive")
        all_props = active_props + inactive_props

        def _scorer_with_thresh(thresh):
            s = MagicMock()
            s.load_config.return_value = {
                "confidence_k": 5,
                "city_score_weights": w,
                "city_score_thresholds": thresh,
            }
            s.load_city_demographics.return_value = {}
            s.score_property.return_value = {
                "score": 50, "cap_rate": 7.0, "coc": 0, "irr": 0,
                "dscr": 1.0, "cf_annual": 0, "price_drop": 0, "dom": 0,
            }
            return s

        opp_tight = CityRanker(_scorer_with_thresh(thresh_tight)).rank(all_props)[0]["opportunity"]
        opp_wide  = CityRanker(_scorer_with_thresh(thresh_wide)).rank(all_props)[0]["opportunity"]
        assert opp_tight > opp_wide

    def test_production_weights_include_irr_dscr_cf(self):
        """score_weights.json must define non-zero weights for act_irr, act_dscr, act_cf."""
        import json
        with open("json/score_weights.json") as f:
            cfg = json.load(f)
        w = cfg["city_score_weights"]
        assert w.get("act_irr",  0) > 0, "act_irr weight missing or zero"
        assert w.get("act_dscr", 0) > 0, "act_dscr weight missing or zero"
        assert w.get("act_cf",   0) > 0, "act_cf weight missing or zero"
