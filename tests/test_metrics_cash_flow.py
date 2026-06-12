import pytest
from analysis.metrics.cash_flow import CashFlowMetrics, DebtMetrics


class TestCashFlowMetrics:
    def test_cash_invested_no_construction(self):
        m = CashFlowMetrics(36_000, 24_000, 100_000)
        assert m.cash_invested == pytest.approx(100_000)

    def test_cash_invested_with_construction(self):
        m = CashFlowMetrics(36_000, 24_000, 100_000, construction_cost=20_000)
        assert m.cash_invested == pytest.approx(120_000)

    def test_annual_cash_flow(self):
        m = CashFlowMetrics(36_000, 24_000, 100_000)
        assert m.annual_cash_flow == pytest.approx(12_000)

    def test_monthly_cash_flow(self):
        m = CashFlowMetrics(36_000, 24_000, 100_000)
        assert m.monthly_cash_flow == pytest.approx(1_000)

    def test_coc_return(self):
        m = CashFlowMetrics(36_000, 24_000, 100_000)
        # 12000 / 100000 * 100 = 12%
        assert m.coc_return == pytest.approx(12.0)

    def test_coc_zero_cash_invested(self):
        m = CashFlowMetrics(36_000, 24_000, 0)
        assert m.coc_return == 0

    def test_grade_bleeding(self):
        m = CashFlowMetrics(20_000, 30_000, 100_000)
        assert m._cf_grade() == "POOR/BLEEDING"

    def test_grade_good(self):
        # Need coc >= 8.0 and cash_flow > 0
        m = CashFlowMetrics(36_000, 24_000, 100_000)  # coc = 12%
        assert m._cf_grade() == "GOOD"

    def test_grade_fair(self):
        # coc between 0 and 8
        m = CashFlowMetrics(30_000, 24_000, 200_000)  # coc = 3%
        assert m._cf_grade() == "FAIR (Thin Margin)"

    def test_rows_count(self):
        m = CashFlowMetrics(36_000, 24_000, 100_000)
        assert len(m.rows()) == 3

    def test_rows_metrics(self):
        m = CashFlowMetrics(36_000, 24_000, 100_000)
        metrics = {r.metric for r in m.rows()}
        assert "Annual Cash Flow" in metrics
        assert "Monthly Cash Flow" in metrics
        assert "CoCR" in metrics

    def test_cocr_grade_in_rows(self):
        m = CashFlowMetrics(36_000, 24_000, 100_000)  # coc = 12%
        cocr_row = next(r for r in m.rows() if r.metric == "CoCR")
        assert cocr_row.grade == "GOOD"


class TestDebtMetrics:
    def test_dscr_basic(self):
        m = DebtMetrics(36_000, 0.40, 24_000, 60_000)
        assert m.dscr == pytest.approx(1.5)

    def test_dscr_infinite_with_zero_mortgage(self):
        m = DebtMetrics(36_000, 0.40, 0, 60_000)
        assert m.dscr == float("inf")

    def test_be_ratio(self):
        m = DebtMetrics(36_000, 0.40, 24_000, 60_000)
        # be_ratio = (24000 / 36000) * 100 = 66.67
        assert m.be_ratio == pytest.approx(66.67, rel=0.01)

    def test_break_even_point(self):
        m = DebtMetrics(36_000, 0.40, 24_000, 60_000)
        # BEO = mortgage / (gross_rent * (1 - expense_ratio)) * 100
        #     = 24000 / (60000 * 0.60) * 100 = 66.67%
        assert m.break_even_point == pytest.approx(66.67, rel=0.01)

    def test_stressed_dscr_pass(self):
        # NOI=50k well above stressed payment on a small mortgage → PASS
        m = DebtMetrics(50_000, 0.40, 24_000, 80_000,
                        loan_amount=340_000, interest_rate=0.05, term_years=25)
        row = next(r for r in m.rows() if "Stress" in r.metric)
        assert row.grade == "PASS"

    def test_stressed_dscr_fail(self):
        # NOI barely covers the current mortgage; a 200bp shock pushes DSCR below 1.20
        m = DebtMetrics(30_000, 0.40, 28_000, 60_000,
                        loan_amount=400_000, interest_rate=0.05, term_years=25)
        row = next(r for r in m.rows() if "Stress" in r.metric)
        assert "FAIL" in row.grade

    def test_rows_count(self):
        m = DebtMetrics(36_000, 0.40, 24_000, 60_000)
        assert len(m.rows()) == 5

    def test_dscr_grade_good(self):
        m = DebtMetrics(36_000, 0.40, 24_000, 60_000)  # dscr = 1.5
        dscr_row = next(r for r in m.rows() if r.metric == "DSCR")
        assert dscr_row.grade == "GOOD"

    def test_dscr_grade_poor(self):
        m = DebtMetrics(20_000, 0.40, 30_000, 40_000)  # dscr < 1.25
        dscr_row = next(r for r in m.rows() if r.metric == "DSCR")
        assert "POOR" in dscr_row.grade


# ── Issue #5: stress test must scale with loan size, not be a flat $9k add-on ─
# ── Issue #8: Break-Even Occupancy % must be graded with break_even_point ─────

class TestStressTestScalesWithLoan:
    # Both loan sizes use the same rate/term so percentage payment increase is identical.
    _RATE  = 0.05
    _TERM  = 25
    _BUMP  = 0.02

    def test_stress_increment_percentage_is_consistent(self):
        """200bp rate shock must increase the payment by the same percentage regardless of loan size."""
        noi     = 500_000
        m_small = DebtMetrics(noi, 0.40, annual_mortgage=50_000,  annual_rent=600_000,
                               loan_amount=700_000,   interest_rate=self._RATE, term_years=self._TERM)
        m_large = DebtMetrics(noi, 0.40, annual_mortgage=500_000, annual_rent=600_000,
                               loan_amount=7_000_000, interest_rate=self._RATE, term_years=self._TERM)

        stressed_small = noi / m_small.stressed_dscr
        stressed_large = noi / m_large.stressed_dscr

        pct_small = (stressed_small - 50_000)  / 50_000
        pct_large = (stressed_large - 500_000) / 500_000

        assert pct_small == pytest.approx(pct_large, rel=0.001), (
            f"Stress increment is {pct_small*100:.1f}% on small loan "
            f"but {pct_large*100:.1f}% on large; must be proportional"
        )

    def test_stress_shock_magnitude_is_realistic(self):
        """A +200bp shock on a 25-year loan at 5% raises the payment ~21%, not ~2%."""
        noi = 200_000
        m   = DebtMetrics(noi, 0.40, annual_mortgage=24_000, annual_rent=260_000,
                          loan_amount=340_000, interest_rate=self._RATE, term_years=self._TERM)
        stressed_payment = noi / m.stressed_dscr
        pct_increase = (stressed_payment - 24_000) / 24_000
        # At 5%→7%, 25yr the increase is ~21%; accept anything between 15% and 30%
        assert 0.15 < pct_increase < 0.30, (
            f"Expected ~21% payment increase for +200bp shock but got {pct_increase*100:.1f}%"
        )

    def test_stress_dscr_drop_is_proportional_regardless_of_loan_size(self):
        """Proportional rate shock → same fractional DSCR reduction for any loan size."""
        noi     = 200_000
        m_small = DebtMetrics(noi, 0.40, annual_mortgage=40_000,  annual_rent=260_000,
                               loan_amount=570_000,   interest_rate=self._RATE, term_years=self._TERM)
        m_large = DebtMetrics(noi, 0.40, annual_mortgage=400_000, annual_rent=260_000,
                               loan_amount=5_700_000, interest_rate=self._RATE, term_years=self._TERM)
        pct_drop_small = (m_small.dscr - m_small.stressed_dscr) / m_small.dscr
        pct_drop_large = (m_large.dscr - m_large.stressed_dscr) / m_large.dscr
        assert pct_drop_small == pytest.approx(pct_drop_large, rel=0.001)


class TestBreakEvenOccupancyGrade:
    """
    Inputs chosen so be_ratio (GOOD) and break_even_point (POOR) diverge:
      be_ratio         = (mortgage / noi) × 100  = 50/100k × 100 = 50   → GOOD  (< 75)
      break_even_point = mortgage / (rent × (1 − expense_ratio)) × 100
                       = 50k / (100k × 0.50) × 100 = 100%               → POOR  (> 85)
    """

    @staticmethod
    def _debt():
        return DebtMetrics(est_noi=100_000, expense_ratio=0.50,
                           annual_mortgage=50_000, annual_rent=100_000)

    def test_be_occupancy_grade_uses_break_even_point(self):
        m   = self._debt()
        row = next(r for r in m.rows() if r.metric == "Break-Even Occupancy %")
        assert row.grade == "POOR", (
            f"Grade should be POOR (bep={m.break_even_point:.0f}%) "
            f"but got {row.grade!r} — graded with be_ratio ({m.be_ratio:.0f}%) instead"
        )

    def test_be_noi_pct_grade_uses_be_ratio(self):
        m   = self._debt()
        row = next(r for r in m.rows() if r.metric == "Break-Even NOI %")
        assert row.grade == "GOOD", (
            f"Grade should be GOOD (be_ratio={m.be_ratio:.0f}%) "
            f"but got {row.grade!r}"
        )

    def test_displayed_values_match_metric_names(self):
        """Values are already correct (only grades are swapped) — regression baseline."""
        m    = self._debt()
        rows = {r.metric: r for r in m.rows()}
        if "Break-Even NOI %" in rows:
            val = float(rows["Break-Even NOI %"].value.replace("%", ""))
            assert val == pytest.approx(m.be_ratio, rel=1e-2)
        if "Break-Even Occupancy %" in rows:
            val = float(rows["Break-Even Occupancy %"].value.replace("%", ""))
            assert val == pytest.approx(m.break_even_point, rel=1e-2)
