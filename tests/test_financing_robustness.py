"""Tests for analysis/metrics/financing_robustness.py (Fix 5 diagnostic + Fix 6
scored factor)."""
import pytest
from analysis.metrics.financing_robustness import FinancingRobustness


def _fr(noi, loan=1_000_000, rate=0.05, amort=25, covenant=1.20, **kw):
    return FinancingRobustness(noi, loan, rate, amort, covenant, **kw)


class TestBreakEvenMargins:
    def test_strong_deal_positive_margins_and_score(self):
        # NOI comfortably above debt service → positive rate & amort margins.
        fr = _fr(noi=120_000)          # DSCR well above 1.20 on a $1M/5%/25yr loan
        assert fr.current_dscr > 1.20
        assert fr.rate_cov_bps > 0
        assert fr.amort_cov_yr > 0
        assert fr.score > 0
        assert fr.verdict == "passes at current terms"

    def test_breached_deal_negative_rate_margin_and_zero_score(self):
        # NOI below the covenant requirement → already breached.
        fr = _fr(noi=60_000)
        assert fr.current_dscr < 1.20
        assert fr.rate_cov_bps < 0            # rate would have to FALL to reach covenant
        assert fr.score == 0.0
        assert fr.verdict == "fails under all realistic terms"

    def test_covenant_breach_precedes_cash_flow_zero(self):
        # For a passing deal the covenant (1.20) is crossed before cash flow zero
        # (DSCR 1.00): covenant margin < cash-flow-zero margin.
        fr = _fr(noi=100_000, covenant=1.20)
        assert fr.rate_cov_bps < fr.rate_cf0_bps
        assert fr.amort_cov_yr < fr.amort_cf0_yr
        assert fr.rate_spread_bps == pytest.approx(fr.rate_cf0_bps - fr.rate_cov_bps)
        assert fr.rate_spread_bps > 0

    def test_lower_covenant_gives_more_rate_headroom(self):
        hi_cov = _fr(noi=100_000, covenant=1.30)
        lo_cov = _fr(noi=100_000, covenant=1.10)   # CMHC-style lower covenant
        assert lo_cov.rate_cov_bps > hi_cov.rate_cov_bps


class TestScore:
    def test_no_debt_is_fully_robust(self):
        fr = _fr(noi=50_000, loan=0)
        assert not fr.has_debt
        assert fr.score == 100.0
        assert "no debt" in fr.verdict

    def test_rate_weighted_more_than_amortization(self):
        # The scored value is 0.7 * rate_margin_score + 0.3 * amort_margin_score,
        # both on the covenant-breach margins — rate weighted more heavily.
        fr = _fr(noi=100_000, rate_ref_bps=250, amort_ref_years=10, rate_weight=0.7)
        rate_s  = max(0.0, min(1.0, fr.rate_cov_bps / 250))
        amort_s = max(0.0, min(1.0, fr.amort_cov_yr / 10))
        expected = round(100.0 * (0.7 * rate_s + 0.3 * amort_s), 1)
        assert fr.score == pytest.approx(expected)

    def test_score_monotonic_in_noi(self):
        weak = _fr(noi=90_000)
        strong = _fr(noi=140_000)
        assert strong.score >= weak.score


class TestRows:
    def test_rows_render_and_include_scored_and_glance(self):
        fr = _fr(noi=120_000)
        rows = {r.metric: r.value for r in fr.rows()}
        assert "Rate Risk (scheduled)" in rows
        assert "Amortization Risk (conditional)" in rows
        assert "Break-Even Financing" in rows
        assert "Financing Verdict" in rows
        assert "covenant breach" in fr.glance()

    def test_no_debt_rows(self):
        fr = _fr(noi=50_000, loan=0)
        rows = {r.metric: r.value for r in fr.rows()}
        assert rows["Financing Robustness"] == "N/A (no debt)"
