"""Tests for the shortlist comparison report's data shaping.

The render embeds the deal data as JSON; these tests parse it back out and check
the server-side rules: only active, scored deals are offered, and price-per-sqft
is derived correctly.
"""

import json
import re
from reporting.comparison_report import ComparisonReportGenerator


def _embedded(html):
    m = re.search(r"const DATA = (\[.*?\]);", html, re.S)
    assert m, "embedded DATA array not found"
    return json.loads(m.group(1))


def _row(**kw):
    base = dict(address="1 St", city="Testville", type="Office", status="active",
                score=70, asking=1_000_000, sqft=10_000, cap_rate=7.0, coc=8.0,
                irr=12.0, em=1.8, dscr=1.3, cf_annual=20_000, dom=60,
                price_drop=0, verified_income_pct=0.0)
    base.update(kw)
    return base


def test_only_active_scored_deals_are_offered():
    rows = [
        _row(address="Active Scored"),
        _row(address="Inactive", status="inactive"),
        _row(address="Unscored", score=None),
    ]
    deals = _embedded(ComparisonReportGenerator().render(rows))
    addrs = {d["address"] for d in deals}
    assert addrs == {"Active Scored"}


def test_price_per_sqft_is_derived():
    deals = _embedded(ComparisonReportGenerator().render(
        [_row(asking=1_000_000, sqft=10_000)]))
    assert deals[0]["price_psf"] == 100.0


def test_price_per_sqft_none_without_sqft():
    deals = _embedded(ComparisonReportGenerator().render([_row(sqft=0)]))
    assert deals[0]["price_psf"] is None


def test_deals_sorted_best_score_first():
    rows = [_row(address="Low", score=55), _row(address="High", score=95)]
    deals = _embedded(ComparisonReportGenerator().render(rows))
    assert [d["address"] for d in deals] == ["High", "Low"]
