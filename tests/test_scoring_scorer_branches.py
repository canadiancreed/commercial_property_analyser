"""Branch and edge-case coverage for scoring/scorer.py.

Covers: solve_targets binary-search paths, bisect lever bodies and false
branches, config save/load edge cases, and score_property corner cases.
"""
import json
import os
import pytest
from unittest.mock import MagicMock, patch
from scoring.scorer import PropertyScorer, SCORE_CONFIG_PATH
from analysis.metrics.returns import METRIC_MARKET_STALENESS


def _full_results(cap=8.0, coc=10.0, dscr=1.6, irr=14.0, em=2.0,
                  cf=20_000, drop=8.0, dom=120):
    return [
        {"metric": "NOI",             "value": "$40,000.00", "grade": "GOOD"},
        {"metric": "Cap Rate",        "value": f"{cap}%",    "grade": "GOOD"},
        {"metric": "CoCR",            "value": f"{coc}%",    "grade": "GOOD"},
        {"metric": "DSCR",            "value": f"{dscr}",    "grade": "GOOD"},
        {"metric": "IRR (10-Yr)",      "value": f"{irr}%",    "grade": "GOOD"},
        {"metric": "Equity Multiple", "value": f"{em}x",     "grade": "GOOD"},
        {"metric": "Annual Cash Flow","value": f"${cf}",     "grade": "GOOD"},
        {"metric": "Price Drop %",    "value": f"{drop}%",   "grade": "GOOD"},
        {"metric": METRIC_MARKET_STALENESS,"value": f"{dom} Days","grade": "GOOD"},
    ]


def _poor_record():
    return {
        "city": "Ottawa", "province": "ON",
        "asking_price": 500_000, "original_price": 510_000,
        "interest_rate": 0.07, "down_payment_pct": 0.20,
        "commercial_rent": 30_000, "residential_rent": 0,
        "annual_rent": None,
        # Fully verified income / no confidence haircut — these tests isolate
        # a single financial lever (price/rent/rate/down-pct), not the
        # market-signal confidence axis, so DOM/Price Drop must not trigger
        # an amplified haircut here.
        "verified_income_pct": 100.0,
        "confidence_multiplier": 1.0,
        "results": _full_results(cap=2.0, coc=0.0, dscr=0.5,
                                  irr=0.0, em=0.5, cf=-5000,
                                  drop=0.0, dom=0),
    }


# ── solve_targets: full binary search ─────────────────────────────────────────

class TestSolveTargetsBinarySearch:
    """Exercises the binary search levers inside solve_targets."""

    def _analyzer_factory(self):
        """Analyzer that always yields a perfect score."""
        def record_to_prop(rec):
            return MagicMock()

        class FakeAnalyzer:
            def __init__(self, prop, resolver):
                pass
            def to_record(self, existing=None):
                return {"results": _full_results(
                    cap=9.0, coc=12.0, dscr=2.0, irr=20.0,
                    em=3.0, cf=50_000, drop=15.0, dom=180
                )}

        return record_to_prop, FakeAnalyzer

    def test_solve_price_lever(self, make_store):
        scorer = PropertyScorer(make_store())
        p = _poor_record()
        p["asking_price"] = 500_000
        p["results"] = _full_results(cap=3.0, coc=1.0, dscr=0.8,
                                      irr=2.0, em=0.9, cf=-5000,
                                      drop=0.0, dom=10)
        r2p, AnalyzerCls = self._analyzer_factory()
        result = scorer.solve_targets(p, r2p, AnalyzerCls, MagicMock())
        assert isinstance(result, dict)

    def test_solve_rent_lever(self, make_store):
        scorer = PropertyScorer(make_store())
        p = _poor_record()
        p["commercial_rent"] = 30_000
        r2p, AnalyzerCls = self._analyzer_factory()
        result = scorer.solve_targets(p, r2p, AnalyzerCls, MagicMock())
        assert isinstance(result, dict)

    def test_solve_rate_lever(self, make_store):
        scorer = PropertyScorer(make_store())
        p = _poor_record()
        p["interest_rate"] = 0.09
        r2p, AnalyzerCls = self._analyzer_factory()
        result = scorer.solve_targets(p, r2p, AnalyzerCls, MagicMock())
        assert isinstance(result, dict)

    def test_solve_down_pct_lever(self, make_store):
        scorer = PropertyScorer(make_store())
        p = _poor_record()
        p["down_payment_pct"] = 0.10
        r2p, AnalyzerCls = self._analyzer_factory()
        result = scorer.solve_targets(p, r2p, AnalyzerCls, MagicMock())
        assert isinstance(result, dict)

    def test_analyzer_exception_returns_zero(self, make_store):
        """When the inner analyzer raises, score_with should return 0.0 (not crash)."""
        scorer = PropertyScorer(make_store())
        p = _poor_record()

        def bad_record_to_prop(rec):
            raise ValueError("bad")

        class BadAnalyzer:
            def __init__(self, prop, resolver):
                raise RuntimeError("fail")
            def to_record(self, existing=None):
                return {"results": []}

        result = scorer.solve_targets(p, bad_record_to_prop, BadAnalyzer, MagicMock())
        assert isinstance(result, dict)


# ── solve_targets: bisect body executes and records a target ──────────────────

class TestBisectLeverBody:
    """
    Exercises bisect_lever and the inner target-assignment blocks.

    The max achievable score with all-perfect metrics but no location data is
    98.0 — below the 99.5 trigger.  We zero out the Location weight via a
    patched load_config so max score reaches 100.0, then use a "smart"
    analyzer that returns good results only when the lever crosses its threshold.
    """

    def _no_location_cfg(self, scorer):
        cfg = scorer.load_config()
        cfg["weights"]["Location"] = 0.0
        return cfg

    def _smart_factory(self, trigger_key, trigger_threshold, invert=False):
        """Analyzer yields GOOD results only when the lever crosses the threshold."""
        def record_to_prop(rec):
            return MagicMock()

        class SmartAnalyzer:
            def __init__(self, prop, resolver):
                pass
            def to_record(self_, existing=None):
                val = (existing or {}).get(trigger_key, 0)
                good = (val < trigger_threshold) if invert else (val > trigger_threshold)
                if good:
                    return {"results": _full_results(
                        cap=9.0, coc=12.0, dscr=2.0, irr=20.0,
                        em=3.0, cf=50_000, drop=15.0, dom=180
                    )}
                return {"results": _full_results(
                    cap=2.0, coc=0.0, dscr=0.5, irr=0.0,
                    em=0.5, cf=-5000, drop=0.0, dom=0
                )}

        return record_to_prop, SmartAnalyzer

    def test_bisect_price_lever_body_executed(self, make_store):
        """Base score poor; at lo_p smart analyzer gives score=100 → bisect fires."""
        scorer = PropertyScorer(make_store())
        cfg = self._no_location_cfg(scorer)
        p = _poor_record()
        p["asking_price"] = 500_000
        r2p, AnalyzerCls = self._smart_factory("asking_price", 200_000, invert=True)
        with patch.object(scorer, "load_config", return_value=cfg):
            result = scorer.solve_targets(p, r2p, AnalyzerCls, MagicMock())
        assert "price" in result
        assert result["price"] < 500_000

    def test_bisect_rent_lever_body_executed(self, make_store):
        """Base score poor; at hi_r smart analyzer gives score=100 → bisect fires."""
        scorer = PropertyScorer(make_store())
        cfg = self._no_location_cfg(scorer)
        p = _poor_record()
        p["commercial_rent"] = 30_000
        p["residential_rent"] = 0
        r2p, AnalyzerCls = self._smart_factory("annual_rent", 100_000, invert=False)
        with patch.object(scorer, "load_config", return_value=cfg):
            result = scorer.solve_targets(p, r2p, AnalyzerCls, MagicMock())
        assert "rent" in result
        assert result["rent"] > 30_000

    def test_bisect_rate_lever_body_executed(self, make_store):
        """Base score poor; at lo_i smart analyzer gives score=100 → bisect fires."""
        scorer = PropertyScorer(make_store())
        cfg = self._no_location_cfg(scorer)
        p = _poor_record()
        p["interest_rate"] = 0.09
        r2p, AnalyzerCls = self._smart_factory("interest_rate", 0.02, invert=True)
        with patch.object(scorer, "load_config", return_value=cfg):
            result = scorer.solve_targets(p, r2p, AnalyzerCls, MagicMock())
        assert "rate" in result
        assert result["rate"] < 0.09

    def test_bisect_down_pct_lever_body_executed(self, make_store):
        """Base score poor; at hi_d smart analyzer gives score=100 → bisect fires."""
        scorer = PropertyScorer(make_store())
        cfg = self._no_location_cfg(scorer)
        p = _poor_record()
        p["down_payment_pct"] = 0.10
        r2p, AnalyzerCls = self._smart_factory("down_payment_pct", 0.80, invert=False)
        with patch.object(scorer, "load_config", return_value=cfg):
            result = scorer.solve_targets(p, r2p, AnalyzerCls, MagicMock())
        assert "down_pct" in result
        assert result["down_pct"] > 0.10

    # ── False branches: bisect ran but target ≈ base (no meaningful improvement) ─

    def test_price_bisect_target_not_meaningfully_lower(self, make_store):
        """bisect fires but t ≈ base_price → t < base_price*0.999 is False."""
        scorer = PropertyScorer(make_store())
        cfg = self._no_location_cfg(scorer)
        p = _poor_record()
        base_price = 500_000
        p["asking_price"] = base_price
        r2p, AnalyzerCls = self._smart_factory("asking_price", base_price, invert=True)
        with patch.object(scorer, "load_config", return_value=cfg):
            result = scorer.solve_targets(p, r2p, AnalyzerCls, MagicMock())
        assert "price" not in result

    def test_rent_bisect_target_not_meaningfully_higher(self, make_store):
        """bisect fires but t ≈ base_rent → t > base_rent*1.001 is False."""
        scorer = PropertyScorer(make_store())
        cfg = self._no_location_cfg(scorer)
        p = _poor_record()
        base_rent = 30_000
        p["commercial_rent"] = base_rent
        p["residential_rent"] = 0
        r2p, AnalyzerCls = self._smart_factory("annual_rent", base_rent + 1, invert=False)
        with patch.object(scorer, "load_config", return_value=cfg):
            result = scorer.solve_targets(p, r2p, AnalyzerCls, MagicMock())
        assert "rent" not in result

    def test_rate_bisect_target_not_meaningfully_lower(self, make_store):
        """bisect fires but t ≈ base_rate → t < base_rate*0.999 is False."""
        scorer = PropertyScorer(make_store())
        cfg = self._no_location_cfg(scorer)
        p = _poor_record()
        base_rate = 0.09
        p["interest_rate"] = base_rate
        r2p, AnalyzerCls = self._smart_factory("interest_rate", base_rate, invert=True)
        with patch.object(scorer, "load_config", return_value=cfg):
            result = scorer.solve_targets(p, r2p, AnalyzerCls, MagicMock())
        assert "rate" not in result

    def test_down_pct_bisect_target_not_meaningfully_higher(self, make_store):
        """bisect fires but t ≈ base_dp → t > base_dp*1.001 is False."""
        scorer = PropertyScorer(make_store())
        cfg = self._no_location_cfg(scorer)
        p = _poor_record()
        base_dp = 0.20
        p["down_payment_pct"] = base_dp
        r2p, AnalyzerCls = self._smart_factory("down_payment_pct", base_dp + 0.0001, invert=False)
        with patch.object(scorer, "load_config", return_value=cfg):
            result = scorer.solve_targets(p, r2p, AnalyzerCls, MagicMock())
        assert "down_pct" not in result


# ── solve_targets: lever skip guards ──────────────────────────────────────────

class TestSolveTargetsBisectFalseBranch:
    """Covers the false branches where extreme value doesn't reach 99.5."""

    def _poor_analyzer_factory(self):
        """Analyzer that always returns a poor score (bisect never triggers)."""
        def record_to_prop(rec):
            return MagicMock()

        class PoorAnalyzer:
            def __init__(self, prop, resolver):
                pass
            def to_record(self, existing=None):
                return {"results": [
                    {"metric": "NOI",             "value": "$5,000",  "grade": "POOR"},
                    {"metric": "Cap Rate",        "value": "1.0%",    "grade": "POOR"},
                    {"metric": "CoCR",            "value": "0.0%",    "grade": "POOR"},
                    {"metric": "DSCR",            "value": "0.5",     "grade": "POOR"},
                    {"metric": "IRR (10-Yr)",      "value": "0.0%",    "grade": "POOR"},
                    {"metric": "Equity Multiple", "value": "0.5x",    "grade": "POOR"},
                    {"metric": "Annual Cash Flow","value": "$-1000",  "grade": "POOR"},
                    {"metric": "Price Drop %",    "value": "0.0%",    "grade": "POOR"},
                    {"metric": METRIC_MARKET_STALENESS,"value": "5 Days",  "grade": "POOR"},
                ]}

        return record_to_prop, PoorAnalyzer

    def test_price_lever_not_triggered_when_extreme_poor(self, make_store):
        scorer = PropertyScorer(make_store())
        p = _poor_record()
        r2p, AnalyzerCls = self._poor_analyzer_factory()
        result = scorer.solve_targets(p, r2p, AnalyzerCls, MagicMock())
        assert "price" not in result

    def test_rent_lever_not_triggered_when_extreme_poor(self, make_store):
        scorer = PropertyScorer(make_store())
        p = _poor_record()
        p["commercial_rent"] = 30_000
        r2p, AnalyzerCls = self._poor_analyzer_factory()
        result = scorer.solve_targets(p, r2p, AnalyzerCls, MagicMock())
        assert "rent" not in result

    def test_rate_lever_not_triggered_when_extreme_poor(self, make_store):
        scorer = PropertyScorer(make_store())
        p = _poor_record()
        p["interest_rate"] = 0.07
        r2p, AnalyzerCls = self._poor_analyzer_factory()
        result = scorer.solve_targets(p, r2p, AnalyzerCls, MagicMock())
        assert "rate" not in result

    def test_down_pct_lever_not_triggered_when_extreme_poor(self, make_store):
        scorer = PropertyScorer(make_store())
        p = _poor_record()
        p["down_payment_pct"] = 0.20
        r2p, AnalyzerCls = self._poor_analyzer_factory()
        result = scorer.solve_targets(p, r2p, AnalyzerCls, MagicMock())
        assert "down_pct" not in result

    def test_zero_asking_price_skips_price_lever(self, make_store):
        """base_price=0 → price lever guard is False, lever skipped."""
        scorer = PropertyScorer(make_store())
        p = _poor_record()
        p["asking_price"] = 0
        r2p, AnalyzerCls = self._poor_analyzer_factory()
        result = scorer.solve_targets(p, r2p, AnalyzerCls, MagicMock())
        assert "price" not in result

    def test_zero_rent_skips_rent_lever(self, make_store):
        """base_rent=0 → rent lever guard is False, lever skipped."""
        scorer = PropertyScorer(make_store())
        p = _poor_record()
        p["commercial_rent"] = 0
        p["residential_rent"] = 0
        r2p, AnalyzerCls = self._poor_analyzer_factory()
        result = scorer.solve_targets(p, r2p, AnalyzerCls, MagicMock())
        assert "rent" not in result

    def test_zero_rate_skips_rate_lever(self, make_store):
        """base_rate=0 → rate lever guard is False, lever skipped."""
        scorer = PropertyScorer(make_store())
        p = _poor_record()
        p["interest_rate"] = 0
        r2p, AnalyzerCls = self._poor_analyzer_factory()
        result = scorer.solve_targets(p, r2p, AnalyzerCls, MagicMock())
        assert "rate" not in result

    def test_high_down_pct_skips_down_pct_lever(self, make_store):
        """base_dp=0.95 → down_pct lever guard is False, lever skipped."""
        scorer = PropertyScorer(make_store())
        p = _poor_record()
        p["down_payment_pct"] = 0.95
        r2p, AnalyzerCls = self._poor_analyzer_factory()
        result = scorer.solve_targets(p, r2p, AnalyzerCls, MagicMock())
        assert "down_pct" not in result

    def test_annual_rent_override_clears_comm_res_rent(self, make_store):
        """score_with with annual_rent override clears commercial_rent/residential_rent."""
        scorer = PropertyScorer(make_store())
        captured = []

        def record_to_prop(rec):
            captured.append(rec.copy())
            return MagicMock()

        class CapturingAnalyzer:
            def __init__(self, prop, resolver): pass
            def to_record(self, existing=None):
                return {"results": _full_results(cap=9.0, coc=12.0, dscr=2.0,
                                                  irr=20.0, em=3.0, cf=50_000,
                                                  drop=15.0, dom=180)}

        p = _poor_record()
        p["commercial_rent"] = 30_000
        p["residential_rent"] = 5_000
        scorer.solve_targets(p, record_to_prop, CapturingAnalyzer, MagicMock())
        for rec in [r for r in captured if r.get("annual_rent") is not None]:
            assert rec.get("commercial_rent") is None
            assert rec.get("residential_rent") is None


# ── Config save / load ─────────────────────────────────────────────────────────

class TestConfigSaveLoad:
    def test_save_config_creates_file(self, make_store, tmp_path):
        scorer = PropertyScorer(make_store())
        cfg = scorer.load_config()
        cfg["weights"]["Cap Rate"] = 0.30
        score_path = str(tmp_path / "json" / "score_weights.json")
        os.makedirs(str(tmp_path / "json"), exist_ok=True)
        with patch("scoring.scorer.SCORE_CONFIG_PATH", score_path):
            scorer.save_config(cfg)
        assert os.path.exists(score_path)

    def test_load_config_from_file(self, make_store, tmp_path):
        scorer = PropertyScorer(make_store())
        score_path = str(tmp_path / "json" / "score_weights.json")
        os.makedirs(str(tmp_path / "json"), exist_ok=True)
        with open(score_path, "w") as f:
            json.dump({"weights": {"Cap Rate": 0.99}}, f)
        with patch("scoring.scorer.SCORE_CONFIG_PATH", score_path):
            loaded = scorer.load_config()
        assert loaded["weights"]["Cap Rate"] == pytest.approx(0.99)

    def test_load_city_distances_with_data(self, make_store, tmp_path):
        scorer = PropertyScorer(make_store())
        dist_path = str(tmp_path / "json" / "city_distances.json")
        os.makedirs(str(tmp_path / "json"), exist_ok=True)
        with open(dist_path, "w") as f:
            json.dump({"Ottawa": {"distance_km": 50, "nearest_centre": "Ottawa"}}, f)
        with patch("scoring.scorer.CITY_DISTANCES_PATH", dist_path):
            distances = scorer.load_city_distances()
        assert "ottawa" in distances
        assert distances["ottawa"]["distance_km"] == 50

    def test_load_city_demographics_with_data(self, make_store, tmp_path):
        scorer = PropertyScorer(make_store())
        demo_path = str(tmp_path / "json" / "city_demographics.json")
        os.makedirs(str(tmp_path / "json"), exist_ok=True)
        with open(demo_path, "w") as f:
            json.dump({"ottawa": {"population": 1_000_000, "growth_pct_annual": 1.8}}, f)
        with patch("scoring.scorer.CITY_DEMOGRAPHICS_PATH", demo_path):
            demographics = scorer.load_city_demographics()
        assert "ottawa" in demographics
        assert demographics["ottawa"]["population"] == 1_000_000


# ── Config load branches ───────────────────────────────────────────────────────

class TestLoadConfigBranches:
    """Covers the load_config branches that require a patched SCORE_CONFIG_PATH."""

    def test_load_config_file_not_found_raises(self, make_store, tmp_path):
        """Missing config file raises — there are no hardcoded fallbacks."""
        scorer = PropertyScorer(make_store())
        with patch("scoring.scorer.SCORE_CONFIG_PATH", str(tmp_path / "no_such_file.json")):
            with pytest.raises(Exception):
                scorer.load_config()

    def test_load_config_partial_file_returns_as_is(self, make_store, tmp_path):
        """A partial config file is returned exactly as stored — no merging."""
        scorer = PropertyScorer(make_store())
        partial_cfg = {"weights": {"Cap Rate": 0.30}}
        cfg_path = str(tmp_path / "json" / "score_weights.json")
        os.makedirs(str(tmp_path / "json"), exist_ok=True)
        with open(cfg_path, "w") as f:
            json.dump(partial_cfg, f)
        with patch("scoring.scorer.SCORE_CONFIG_PATH", cfg_path):
            cfg = scorer.load_config()
        assert cfg["weights"]["Cap Rate"] == pytest.approx(0.30)
        assert "thresholds" not in cfg

    def test_load_config_missing_confidence_k_is_absent(self, make_store, tmp_path):
        """Config file with no confidence_k has no confidence_k — nothing is injected."""
        scorer = PropertyScorer(make_store())
        cfg_path = str(tmp_path / "json" / "score_weights.json")
        os.makedirs(str(tmp_path / "json"), exist_ok=True)
        with open(cfg_path, "w") as f:
            json.dump({"weights": {"Cap Rate": 0.25}}, f)
        with patch("scoring.scorer.SCORE_CONFIG_PATH", cfg_path):
            cfg = scorer.load_config()
        assert "confidence_k" not in cfg


# ── score_property edge cases ──────────────────────────────────────────────────

class TestScorePropertyEdgeCases:
    def test_all_zero_weights_returns_zero_score(self, make_store):
        scorer = PropertyScorer(make_store())
        cfg = scorer.load_config()
        for k in cfg["weights"]:
            cfg["weights"][k] = 0.0
        with patch.object(scorer, "load_config", return_value=cfg):
            result = scorer.score_property({"results": _full_results()})
        assert result["score"] == pytest.approx(0.0)

    def test_location_invert_component(self, make_store, tmp_path):
        """Location uses invert=True — closer distance → higher score."""
        scorer = PropertyScorer(make_store())
        dist_path = str(tmp_path / "json" / "city_distances.json")
        os.makedirs(str(tmp_path / "json"), exist_ok=True)
        with open(dist_path, "w") as f:
            json.dump({
                "close city": {"distance_km": 10,  "nearest_centre": "Centre"},
                "far city":   {"distance_km": 300, "nearest_centre": "Centre"},
            }, f)
        close_p = {"city": "close city", "province": "ON", "results": _full_results()}
        far_p   = {"city": "far city",   "province": "ON", "results": _full_results()}
        with patch("scoring.scorer.CITY_DISTANCES_PATH", dist_path):
            close_result = scorer.score_property(close_p)
            far_result   = scorer.score_property(far_p)
        assert close_result["breakdown"].get("Location", 0) >= far_result["breakdown"].get("Location", 0)

    def test_metric_value_parsing_with_dollar_sign(self, make_store):
        """val() strips non-numeric chars — test $-prefixed and comma-formatted values."""
        scorer = PropertyScorer(make_store())
        p = {
            "city": "Ottawa", "province": "ON",
            "results": [
                {"metric": "NOI",             "value": "$36,000.00", "grade": "GOOD"},
                {"metric": "Cap Rate",        "value": "7.50%",      "grade": "GOOD"},
                {"metric": "Annual Cash Flow","value": "$12,000",    "grade": "GOOD"},
                {"metric": "CoCR",            "value": "8.00%",      "grade": "GOOD"},
                {"metric": "DSCR",            "value": "1.50",       "grade": "GOOD"},
                {"metric": "IRR (10-Yr)",      "value": "12.00%",     "grade": "GOOD"},
                {"metric": "Equity Multiple", "value": "1.80x",      "grade": "GOOD"},
                {"metric": "Price Drop %",    "value": "5.00%",      "grade": "GOOD"},
                {"metric": METRIC_MARKET_STALENESS,"value": "90 Days",    "grade": "GOOD"},
            ]
        }
        result = scorer.score_property(p)
        assert result["score"] is not None
        assert result["cap_rate"] == pytest.approx(7.50)
        assert result["cf_annual"] == pytest.approx(12_000)

    def test_val_returns_default_for_missing_metric(self, make_store):
        """val() returns 0.0 when the metric row doesn't exist."""
        scorer = PropertyScorer(make_store())
        p = {"results": [{"metric": "NOI", "value": "$30,000", "grade": "GOOD"}]}
        result = scorer.score_property(p)
        assert result["cap_rate"] == pytest.approx(0.0)

    def test_component_hi_equals_lo_returns_zero(self, make_store):
        """component() when lo == hi → return 0.0 (no division by zero)."""
        scorer = PropertyScorer(make_store())
        cfg = scorer.load_config()
        cfg["thresholds"]["Cap Rate"] = [5.0, 5.0]
        with patch.object(scorer, "load_config", return_value=cfg):
            result = scorer.score_property({"results": _full_results(cap=5.0)})
        assert result["breakdown"]["Cap Rate"] == pytest.approx(0.0)

    def test_load_city_distances_corrupted_file(self, make_store, tmp_path):
        """load_city_distances with invalid JSON → returns {}."""
        scorer = PropertyScorer(make_store())
        dist_path = str(tmp_path / "json" / "city_distances.json")
        os.makedirs(str(tmp_path / "json"), exist_ok=True)
        with open(dist_path, "w") as f:
            f.write("NOT JSON")
        with patch("scoring.scorer.CITY_DISTANCES_PATH", dist_path):
            assert scorer.load_city_distances() == {}

    def test_load_city_demographics_corrupted_file(self, make_store, tmp_path):
        """load_city_demographics with invalid JSON → returns {}."""
        scorer = PropertyScorer(make_store())
        demo_path = str(tmp_path / "json" / "city_demographics.json")
        os.makedirs(str(tmp_path / "json"), exist_ok=True)
        with open(demo_path, "w") as f:
            f.write("NOT JSON")
        with patch("scoring.scorer.CITY_DEMOGRAPHICS_PATH", demo_path):
            assert scorer.load_city_demographics() == {}
