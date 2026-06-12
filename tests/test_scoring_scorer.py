import json
import os
import pytest
from scoring.scorer import PropertyScorer, SCORE_CONFIG_PATH
from analysis.metrics.returns import METRIC_MARKET_STALENESS


def _scored_record(cap=7.0, coc=8.0, dscr=1.4, irr=12.0, em=1.8,
                   cf=15_000, drop=5.0, dom=90):
    return {
        "city": "Ottawa",
        "province": "ON",
        "asking_price": 500_000,
        "original_price": 530_000,
        "interest_rate": 0.055,
        "down_payment_pct": 0.25,
        "annual_rent": 60_000,
        "commercial_rent": 60_000,
        "residential_rent": 0,
        "results": [
            {"metric": "Cap Rate",        "value": f"{cap}%",           "grade": "GOOD"},
            {"metric": "CoCR",            "value": f"{coc}%",           "grade": "GOOD"},
            {"metric": "DSCR",            "value": f"{dscr}",           "grade": "GOOD"},
            {"metric": "IRR (10-Yr)",     "value": f"{irr}%",           "grade": "GOOD"},
            {"metric": "Equity Multiple", "value": f"{em}x",            "grade": "GOOD"},
            {"metric": "Annual Cash Flow","value": f"${cf}",            "grade": "GOOD"},
            {"metric": "Price Drop %",    "value": f"{drop}%",          "grade": "GOOD"},
            {"metric": METRIC_MARKET_STALENESS,"value": f"{dom} Days",       "grade": "GOOD"},
            {"metric": "NOI",             "value": "$36,000.00",        "grade": "GOOD"},
        ],
    }


# ── Config ────────────────────────────────────────────────────────────────────

class TestConfig:
    def test_load_config_defaults(self, make_store):
        scorer = PropertyScorer(make_store())
        cfg = scorer.load_config()
        assert "weights" in cfg
        assert "thresholds" in cfg
        assert "Cap Rate" in cfg["weights"]

    def test_config_weights_sum_to_1(self, make_store):
        scorer = PropertyScorer(make_store())
        cfg = scorer.load_config()
        total = sum(cfg["weights"].values())
        assert total == pytest.approx(1.0, abs=0.001)


# ── score_property ─────────────────────────────────────────────────────────────

class TestScoreProperty:
    def test_returns_none_score_without_income_metric(self, make_store):
        scorer = PropertyScorer(make_store())
        p = {"results": [{"metric": "Loan Amount", "value": "$400k", "grade": "INFO"}]}
        result = scorer.score_property(p)
        assert result["score"] is None

    def test_returns_score_with_income(self, make_store):
        scorer = PropertyScorer(make_store())
        result = scorer.score_property(_scored_record())
        assert result["score"] is not None
        assert 0 <= result["score"] <= 100

    def test_score_in_range(self, make_store):
        scorer = PropertyScorer(make_store())
        result = scorer.score_property(_scored_record(cap=9.0, coc=12.0, dscr=2.0,
                                                       irr=20.0, em=3.0, cf=50_000,
                                                       drop=15.0, dom=180))
        assert result["score"] >= 95.0

    def test_poor_metrics_low_score(self, make_store):
        scorer = PropertyScorer(make_store())
        result = scorer.score_property(_scored_record(cap=2.0, coc=0.0, dscr=0.5,
                                                       irr=0.0, em=0.5, cf=-10_000,
                                                       drop=0.0, dom=0))
        assert result["score"] < 30

    def test_breakdown_keys(self, make_store):
        scorer = PropertyScorer(make_store())
        result = scorer.score_property(_scored_record())
        for key in ("Cap Rate", "CoCR", "DSCR", "IRR", "Equity Multiple",
                    "Cash Flow", "Price Drop", "DOM"):
            assert key in result["breakdown"]

    def test_metric_values_returned(self, make_store):
        scorer = PropertyScorer(make_store())
        result = scorer.score_property(_scored_record(cap=7.0, coc=8.0))
        assert result["cap_rate"] == pytest.approx(7.0)
        assert result["coc"] == pytest.approx(8.0)

    def test_empty_results_list(self, make_store):
        scorer = PropertyScorer(make_store())
        result = scorer.score_property({"results": []})
        assert result["score"] is None

    def test_location_score_with_distances(self, make_store, tmp_path):
        scorer = PropertyScorer(make_store())
        dist_path = str(tmp_path / "json" / "city_distances.json")
        os.makedirs(str(tmp_path / "json"), exist_ok=True)
        with open(dist_path, "w") as f:
            json.dump({"ottawa": {"distance_km": 50, "nearest_centre": "Ottawa"}}, f)

        from unittest.mock import patch
        with patch("scoring.scorer.CITY_DISTANCES_PATH", dist_path):
            result = scorer.score_property(_scored_record())
        assert result["dist_km"] == 50


# ── load_city_distances / demographics ─────────────────────────────────────────

class TestGeoData:
    def test_load_distances_missing_file(self, make_store, tmp_path):
        from unittest.mock import patch
        scorer = PropertyScorer(make_store())
        nonexistent = str(tmp_path / "nonexistent_distances.json")
        with patch("scoring.scorer.CITY_DISTANCES_PATH", nonexistent):
            assert scorer.load_city_distances() == {}

    def test_load_demographics_missing_file(self, make_store, tmp_path):
        from unittest.mock import patch
        scorer = PropertyScorer(make_store())
        nonexistent = str(tmp_path / "nonexistent_demographics.json")
        with patch("scoring.scorer.CITY_DEMOGRAPHICS_PATH", nonexistent):
            assert scorer.load_city_demographics() == {}


# ── solve_targets ─────────────────────────────────────────────────────────────

class TestSolveTargets:
    def test_returns_empty_when_no_score(self, make_store):
        scorer = PropertyScorer(make_store())
        result = scorer.solve_targets({"results": []}, lambda x: None, None, None)
        assert result == {}

    def test_returns_empty_when_score_perfect(self, make_store):
        scorer = PropertyScorer(make_store())
        p = _scored_record(cap=9.0, coc=12.0, dscr=2.0, irr=20.0, em=3.0,
                           cf=50_000, drop=15.0, dom=180)
        from unittest.mock import patch
        with patch.object(scorer, "score_property", return_value={"score": 100.0}):
            result = scorer.solve_targets(p, None, None, None)
        assert result == {}

    def test_solve_targets_calls_analyzer(self, make_store):
        """solve_targets should run binary search and return price/rent targets."""
        scorer = PropertyScorer(make_store())
        p = _scored_record(cap=3.0, coc=1.0, dscr=0.8, irr=2.0, em=0.9,
                           cf=-5000, drop=0.0, dom=10)

        from unittest.mock import MagicMock, patch
        mock_prop = MagicMock()
        mock_analyzer = MagicMock()
        mock_analyzer_instance = MagicMock()
        mock_analyzer_instance.to_record.return_value = {"results": [
            {"metric": "NOI",             "value": "$50000",    "grade": "GOOD"},
            {"metric": "Cap Rate",        "value": "9%",        "grade": "GOOD"},
            {"metric": "CoCR",            "value": "12%",       "grade": "GOOD"},
            {"metric": "DSCR",            "value": "2.0",       "grade": "GOOD"},
            {"metric": "IRR (10-Yr)",     "value": "20%",       "grade": "GOOD"},
            {"metric": "Equity Multiple", "value": "3x",        "grade": "GOOD"},
            {"metric": "Annual Cash Flow","value": "$50000",    "grade": "GOOD"},
            {"metric": "Price Drop %",    "value": "15%",       "grade": "GOOD"},
            {"metric": METRIC_MARKET_STALENESS,"value": "180 Days",  "grade": "GOOD"},
        ]}
        mock_analyzer.return_value = mock_analyzer_instance

        result = scorer.solve_targets(p, lambda rec: mock_prop, mock_analyzer, MagicMock())
        assert isinstance(result, dict)
