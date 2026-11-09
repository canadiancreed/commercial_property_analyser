"""Tests for the pipeline summary aggregation (reporting/pipeline_report.py)."""

from reporting.pipeline_report import PipelineReportGenerator

summarize = PipelineReportGenerator.summarize


def _row(**kw):
    base = dict(status="active", score=60, asking=1_000_000, type="Office",
                province="ON", city="Ottawa", cap_rate=7.0, irr=12.0, cf_annual=5_000)
    base.update(kw)
    return base


def test_only_active_scored_deals_counted():
    rows = [_row(), _row(status="inactive"), _row(score=None)]
    s = summarize(rows)
    assert s["count"] == 1


def test_pipeline_value_is_sum_of_asking():
    s = summarize([_row(asking=1_000_000), _row(asking=500_000)])
    assert s["total_value"] == 1_500_000


def test_score_bands_classify_by_named_grade():
    rows = [_row(score=90), _row(score=60), _row(score=40), _row(score=10)]
    s = summarize(rows)
    bands = {b["label"]: b["count"] for b in s["score_bands"]}
    assert bands == {"Excellent": 1, "Good": 1, "Fair": 1, "Weak": 1}


def test_concentration_by_type_shares_sum_to_100():
    rows = [_row(type="Office", asking=600_000),
            _row(type="Retail", asking=400_000)]
    s = summarize(rows)
    by = {t["name"]: t for t in s["by_type"]}
    assert round(by["Office"]["value_pct"] + by["Retail"]["value_pct"], 6) == 100.0
    assert by["Office"]["value_pct"] == 60.0            # largest first
    assert s["by_type"][0]["name"] == "Office"


def test_median_and_cf_positive_share():
    rows = [_row(score=50, cf_annual=10_000), _row(score=70, cf_annual=-1),
            _row(score=90, cf_annual=0)]
    s = summarize(rows)
    assert s["median_score"] == 70
    assert round(s["pct_cf_positive"], 1) == round(1 / 3 * 100, 1)


def test_empty_pipeline_is_safe():
    s = summarize([])
    assert s["count"] == 0 and s["total_value"] == 0
    assert s["median_score"] is None
    assert all(b["count"] == 0 for b in s["score_bands"])
