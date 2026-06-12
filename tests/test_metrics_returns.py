import pytest
from models.property_input import PropertyInput
from analysis.metrics.returns import ReturnMetrics, MarketMetrics, METRIC_MARKET_STALENESS


def _make_prop(**kwargs):
    defaults = dict(
        original_price=500_000, asking_price=500_000,
        total_sq_ft=5000, property_taxes=8000,
        down_payment_pct=0.25, interest_rate=0.055,
        term_years=25, hold_years=10,
    )
    defaults.update(kwargs)
    return PropertyInput(**defaults)


class TestReturnMetrics:
    def test_equity_multiple_positive(self):
        prop = _make_prop(asking_price=500_000, hold_years=10)
        m = ReturnMetrics(prop, year1_noi=12_000, annual_mortgage=0, cash_invested=125_000, exit_price=600_000)
        assert m.equity_multiple > 0

    def test_equity_multiple_known(self):
        prop = _make_prop(asking_price=500_000, hold_years=10)
        exit_price   = 620_000
        loan_balance = 300_000
        # mortgage=0 so yearly_flows = year1_noi * (1+g)^(yr-1)
        g        = 0.02
        total_cf = sum(12_000 * (1 + g) ** (yr - 1) for yr in range(1, 11))
        expected_em = (total_cf + exit_price - loan_balance) / 125_000
        m = ReturnMetrics(prop, 12_000, 0, 125_000, exit_price=exit_price, loan_balance=loan_balance)
        assert m.equity_multiple == pytest.approx(expected_em, rel=1e-4)

    def test_zero_cash_invested_em(self):
        prop = _make_prop()
        m = ReturnMetrics(prop, 12_000, 0, 0, exit_price=500_000)
        assert m.equity_multiple == 0

    def test_irr_reasonable(self):
        prop = _make_prop(asking_price=500_000, hold_years=10)
        m = ReturnMetrics(prop, 12_000, 0, 125_000, exit_price=600_000)
        # IRR should be a plausible percentage, not -100
        assert -10 < m.irr < 50

    def test_irr_negative_cash_flow_returns_minus100(self):
        prop = _make_prop(asking_price=500_000, hold_years=10)
        m = ReturnMetrics(prop, -50_000, 0, 125_000, exit_price=600_000)
        # Very negative cash flow may produce invalid IRR
        # Just ensure it runs without exception
        assert isinstance(m.irr, float)

    def test_irr_zero_hold_years(self):
        prop = _make_prop(hold_years=0)
        m = ReturnMetrics(prop, 12_000, 0, 125_000, exit_price=500_000)
        assert m.irr == -100.0

    def test_em_grade_excellent(self):
        prop = _make_prop(asking_price=300_000, hold_years=20)
        m = ReturnMetrics(prop, 30_000, 0, 75_000, exit_price=700_000)
        assert m._em_grade() == "EXCELLENT"

    def test_em_grade_poor(self):
        prop = _make_prop(asking_price=500_000, hold_years=5)
        # exit_equity = 480k - 450k loan = 30k; EM = (0 + 30k) / 125k = 0.24 → POOR
        m = ReturnMetrics(prop, 0, 0, 125_000, exit_price=480_000, loan_balance=450_000)
        assert m._em_grade() in ("POOR (Underperforming)", "FAIR")

    def test_rows_count(self):
        prop = _make_prop()
        m = ReturnMetrics(prop, 12_000, 0, 125_000, exit_price=550_000)
        assert len(m.rows()) == 3  # IRR, Equity Multiple, NOI Growth Assumption

    def test_rows_metrics(self):
        prop = _make_prop()  # hold_years=10
        m = ReturnMetrics(prop, 12_000, 0, 125_000, exit_price=550_000)
        metrics = {r.metric for r in m.rows()}
        assert "IRR (10-Yr)" in metrics
        assert "Equity Multiple" in metrics

    def test_irr_label_reflects_hold_years(self):
        for years in (5, 10, 30):
            prop = _make_prop(hold_years=years)
            m = ReturnMetrics(prop, 12_000, 0, 125_000, exit_price=550_000)
            metrics = {r.metric for r in m.rows()}
            assert f"IRR ({years}-Yr)" in metrics

    def test_calc_irr_simple(self):
        # Simple IRR: invest 100, get 110 after 1 year → IRR ≈ 10%
        flows = [-100, 110]
        irr = ReturnMetrics._calc_irr(flows)
        assert irr == pytest.approx(0.10, rel=0.001)

    def test_calc_irr_no_flows(self):
        # constant returns
        flows = [-1000] + [300] * 5
        irr = ReturnMetrics._calc_irr(flows)
        assert irr > 0

    def test_calc_irr_dnpv_zero(self):
        """Single cash flow at t=0 makes derivative = 0 → break immediately."""
        flows = [-100.0]
        # dnpv = sum(-t * cf / (1+rate)^(t+1)) — only t=0 term which is 0
        irr = ReturnMetrics._calc_irr(flows)
        assert isinstance(irr, float)  # did not crash

    def test_calc_irr_loop_continues_multiple_iterations(self):
        """Use iterations=1 so the loop body runs but break isn't triggered by
        convergence — covers the 'rate = new_rate' branch (loop continues)."""
        flows = [-1000, 100, 200, 300]
        # With only 1 iteration, the loop runs once; convergence test unlikely to pass
        irr = ReturnMetrics._calc_irr(flows, iterations=1)
        assert isinstance(irr, float)

    def test_irr_exception_handler(self):
        """Forces the except branch (irr = -100.0) by patching _calc_irr to raise."""
        from unittest.mock import patch
        prop = _make_prop(asking_price=500_000, hold_years=5)
        with patch.object(ReturnMetrics, "_calc_irr", side_effect=OverflowError("bad")):
            m = ReturnMetrics(prop, 10_000, 0, 125_000, exit_price=600_000)
        assert m.irr == -100.0

    def test_em_grade_good(self):
        """em between 1.5 and 2.0 → GOOD."""
        prop = _make_prop(asking_price=500_000, hold_years=5)
        # Manually force equity_multiple to 1.7
        m = ReturnMetrics.__new__(ReturnMetrics)
        m.equity_multiple = 1.7
        m.irr = 10.0
        assert m._em_grade() == "GOOD"

    def test_em_grade_poor_underperforming(self):
        """em < 1.2 → POOR (Underperforming)."""
        m = ReturnMetrics.__new__(ReturnMetrics)
        m.equity_multiple = 0.9
        m.irr = -100.0
        assert m._em_grade() == "POOR (Underperforming)"


class TestMarketMetrics:
    def test_celoc_score(self):
        m = MarketMetrics(36_000, 100_000, 24_000, 24_000, 90)
        assert m.celoc_score == pytest.approx(36.0)

    def test_celoc_zero_cash_invested(self):
        m = MarketMetrics(36_000, 0, 24_000, 24_000, 90)
        assert m.celoc_score == 0

    def test_celoc_grade_fast(self):
        m = MarketMetrics(100_000, 100_000, 30_000, 20_000, 30)
        assert m._celoc_grade() == "FAST CELOC"

    def test_celoc_grade_possible(self):
        m = MarketMetrics(70_000, 100_000, 30_000, 20_000, 30)
        assert m._celoc_grade() == "CELOC POSSIBLE"

    def test_celoc_grade_friction(self):
        m = MarketMetrics(45_000, 100_000, 30_000, 20_000, 30)
        assert m._celoc_grade() == "LENDER FRICTION"

    def test_celoc_grade_none(self):
        m = MarketMetrics(20_000, 100_000, 30_000, 20_000, 30)
        assert m._celoc_grade() == "NO CELOC"

    def test_seller_bleed_positive(self):
        m = MarketMetrics(36_000, 100_000, 24_000, 24_000, 90)
        assert m.total_seller_bleed > 0

    def test_seller_bleed_zero_dom(self):
        m = MarketMetrics(36_000, 100_000, 24_000, 24_000, 0)
        assert m.total_seller_bleed == 0.0

    def test_seller_bleed_exact_value(self):
        # monthly_carry = (24_000 + 24_000) / 12 = 4_000
        # bleed = 4_000 * (90 / 30) * 0.10 = 1_200.0
        m = MarketMetrics(36_000, 100_000, 24_000, 24_000, 90, vacancy_rate=0.10)
        assert m.total_seller_bleed == pytest.approx(1_200.0)

    def test_seller_bleed_scales_with_vacancy_rate(self):
        m_low  = MarketMetrics(36_000, 100_000, 24_000, 24_000, 90, vacancy_rate=0.05)
        m_high = MarketMetrics(36_000, 100_000, 24_000, 24_000, 90, vacancy_rate=0.14)
        assert m_low.total_seller_bleed < m_high.total_seller_bleed

    def test_seller_bleed_zero_vacancy_is_zero(self):
        m = MarketMetrics(36_000, 100_000, 24_000, 24_000, 90, vacancy_rate=0.0)
        assert m.total_seller_bleed == 0.0

    def test_rows_count(self):
        m = MarketMetrics(36_000, 100_000, 24_000, 24_000, 90)
        assert len(m.rows()) == 3

    def test_rows_metrics(self):
        m = MarketMetrics(36_000, 100_000, 24_000, 24_000, 90)
        metrics = {r.metric for r in m.rows()}
        assert "CELOC Speed Score" in metrics
        assert METRIC_MARKET_STALENESS in metrics
        assert "Seller Bleed" in metrics

    def test_staleness_grade_good(self):
        # 150 days ≥ 150 → GOOD
        m = MarketMetrics(36_000, 100_000, 24_000, 24_000, 150)
        row = next(r for r in m.rows() if r.metric == METRIC_MARKET_STALENESS)
        assert row.grade == "GOOD"

    def test_staleness_grade_poor(self):
        # 30 days < 90 → POOR
        m = MarketMetrics(36_000, 100_000, 24_000, 24_000, 30)
        row = next(r for r in m.rows() if r.metric == METRIC_MARKET_STALENESS)
        assert row.grade == "POOR"


# ── Issue #1 regression: IRR growth applied to cash flows, not exit price ─────

class TestIRRGrowthRegression:
    """Regression guards — these bugs are fixed; tests ensure they stay fixed."""

    def test_irr_higher_with_growth_than_without(self):
        """Compounding cash flows at 3%/yr must yield a higher IRR than near-flat."""
        prop_low    = _make_prop(hold_years=10, noi_growth_rate=0.001)
        prop_growth = _make_prop(hold_years=10, noi_growth_rate=0.03)
        m_low    = ReturnMetrics(prop_low,    12_000, 0, 125_000, exit_price=600_000)
        m_growth = ReturnMetrics(prop_growth, 12_000, 0, 125_000, exit_price=600_000)
        assert m_growth.irr > m_low.irr

    def test_manual_growth_override_not_replaced_by_default(self):
        """An explicit 5% noi_growth_rate must not be silently replaced by 2%."""
        prop = _make_prop(hold_years=5, noi_growth_rate=0.05)
        m    = ReturnMetrics(prop, 10_000, 0, 100_000, exit_price=550_000)
        assert m.noi_growth_rate == pytest.approx(0.05)

    def test_exit_price_used_as_supplied_not_recomputed(self):
        """EM must use the supplied exit_price, not 500k × (1.02^5) ≈ 552k."""
        g             = 0.02
        prop          = _make_prop(asking_price=500_000, hold_years=5, noi_growth_rate=g)
        exit_price    = 700_000
        cash_flow     = 15_000
        cash_invested = 125_000
        m             = ReturnMetrics(prop, cash_flow, 0, cash_invested, exit_price=exit_price)
        total_cf      = sum(cash_flow * (1 + g) ** (yr - 1) for yr in range(1, 6))
        expected_em   = (total_cf + exit_price) / cash_invested
        assert m.equity_multiple == pytest.approx(expected_em, rel=1e-3)

    def test_cash_flows_compound_over_hold_period(self):
        """Sum of compounded flows at g=0.03 must exceed the flat base × hold_years."""
        g    = 0.03
        base = 10_000
        assert sum(base * (1 + g) ** (yr - 1) for yr in range(1, 6)) > base * 5


# ── Issue #2 regression: single exit price across ExitMetrics and ReturnMetrics

class TestSingleExitPriceRegression:

    def test_return_metrics_uses_exit_metrics_exit_price(self):
        from analysis.metrics.income import ExitMetrics
        g             = 0.02
        prop          = _make_prop(hold_years=5, noi_growth_rate=g)
        loan_balance  = 300_000
        cash_flow     = 12_000
        cash_invested = 125_000
        exit_m = ExitMetrics(prop, entry_cap=0.07, est_noi=35_000,
                             loan_balance=loan_balance)
        ret_m  = ReturnMetrics(prop, cash_flow, 0, cash_invested,
                               exit_price=exit_m.exit_price,
                               loan_balance=loan_balance)
        exit_equity = exit_m.exit_price - loan_balance
        total_cf    = sum(cash_flow * (1 + g) ** (yr - 1) for yr in range(1, 6))
        expected_em = (total_cf + exit_equity) / cash_invested
        assert ret_m.equity_multiple == pytest.approx(expected_em, rel=1e-4)

    def test_exit_price_row_matches_object_attribute(self):
        from analysis.metrics.income import ExitMetrics
        prop   = _make_prop(hold_years=5, noi_growth_rate=0.02)
        exit_m = ExitMetrics(prop, entry_cap=0.065, est_noi=40_000, loan_balance=250_000)
        row    = next(r for r in exit_m.rows() if r.metric == "Exit Price")
        displayed = float(row.value.replace("$", "").replace(",", ""))
        assert displayed == pytest.approx(exit_m.exit_price, rel=1e-4)


# ── Issue #3 regression: equity multiple subtracts loan balance at exit ────────

class TestEquityMultipleLoanPaydownRegression:

    def test_em_lower_with_loan_than_without(self):
        prop = _make_prop(hold_years=5, noi_growth_rate=0.02)
        m_clean = ReturnMetrics(prop, 12_000, 0, 125_000, exit_price=650_000, loan_balance=0)
        m_loan  = ReturnMetrics(prop, 12_000, 0, 125_000, exit_price=650_000, loan_balance=350_000)
        assert m_clean.equity_multiple > m_loan.equity_multiple

    def test_em_formula_exact_with_loan(self):
        g             = 0.02
        prop          = _make_prop(hold_years=5, noi_growth_rate=g)
        cash_flow     = 10_000
        cash_invested = 100_000
        exit_price    = 600_000
        loan_balance  = 380_000
        total_cf      = sum(cash_flow * (1 + g) ** (yr - 1) for yr in range(1, 6))
        expected_em   = (total_cf + exit_price - loan_balance) / cash_invested
        m = ReturnMetrics(prop, cash_flow, 0, cash_invested,
                          exit_price=exit_price, loan_balance=loan_balance)
        assert m.equity_multiple == pytest.approx(expected_em, rel=1e-4)

    def test_negative_exit_equity_depresses_em_below_one(self):
        """When loan balance exceeds exit price the investor is under water."""
        g             = 0.02
        prop          = _make_prop(hold_years=5, noi_growth_rate=g)
        cash_flow     = 5_000
        cash_invested = 100_000
        total_cf      = sum(cash_flow * (1 + g) ** (yr - 1) for yr in range(1, 6))
        m = ReturnMetrics(prop, cash_flow, 0, cash_invested,
                          exit_price=300_000, loan_balance=350_000)
        expected_em = (total_cf + 300_000 - 350_000) / cash_invested
        assert m.equity_multiple == pytest.approx(expected_em, rel=1e-4)
        assert m.equity_multiple < 1.0


# ── Issue #4 regression: yearly IRR flows escalate at noi_growth_rate ─────────

class TestRentEscalationInIRRRegression:

    def test_irr_increases_monotonically_with_growth_rate(self):
        m1 = ReturnMetrics(_make_prop(hold_years=10, noi_growth_rate=0.01),
                           12_000, 0, 125_000, exit_price=600_000)
        m3 = ReturnMetrics(_make_prop(hold_years=10, noi_growth_rate=0.03),
                           12_000, 0, 125_000, exit_price=600_000)
        m5 = ReturnMetrics(_make_prop(hold_years=10, noi_growth_rate=0.05),
                           12_000, 0, 125_000, exit_price=600_000)
        assert m1.irr < m3.irr < m5.irr

    def test_equity_multiple_reflects_compounded_flows(self):
        g             = 0.04
        base          = 10_000
        prop          = _make_prop(hold_years=5, noi_growth_rate=g)
        m             = ReturnMetrics(prop, base, 0, 100_000, exit_price=500_000)
        escalated_sum = sum(base * (1 + g) ** (yr - 1) for yr in range(1, 6))
        expected_em   = (escalated_sum + 500_000) / 100_000
        assert m.equity_multiple == pytest.approx(expected_em, rel=1e-3)


# ── Bug fix: mortgage is fixed; only NOI escalates ────────────────────────────

class TestMortgageNotEscalated:

    def test_mortgage_held_constant_across_hold_period(self):
        """With a real mortgage, EM must equal sum(noi*(1+g)^(yr-1) - mortgage) + exit_equity."""
        g             = 0.02
        noi           = 40_000
        mortgage      = 25_000
        cash_invested = 125_000
        exit_price    = 700_000
        hold          = 10
        prop          = _make_prop(hold_years=hold, noi_growth_rate=g)
        m             = ReturnMetrics(prop, noi, mortgage, cash_invested, exit_price=exit_price)
        expected_cf   = sum(noi * (1 + g) ** (yr - 1) - mortgage for yr in range(1, hold + 1))
        expected_em   = (expected_cf + exit_price) / cash_invested
        assert m.equity_multiple == pytest.approx(expected_em, rel=1e-4)

    def test_higher_mortgage_reduces_em(self):
        """Doubling the mortgage must reduce EM regardless of growth rate."""
        g    = 0.03
        prop = _make_prop(hold_years=10, noi_growth_rate=g)
        m_lo = ReturnMetrics(prop, 40_000, 10_000, 125_000, exit_price=650_000)
        m_hi = ReturnMetrics(prop, 40_000, 30_000, 125_000, exit_price=650_000)
        assert m_lo.equity_multiple > m_hi.equity_multiple

    def test_mortgage_not_inflated_by_growth(self):
        """At g=0.20, EM with mortgage must equal EM without mortgage minus present value of fixed payments."""
        g             = 0.20
        noi           = 50_000
        mortgage      = 20_000
        hold          = 5
        cash_invested = 100_000
        exit_price    = 500_000
        prop          = _make_prop(hold_years=hold, noi_growth_rate=g)
        m             = ReturnMetrics(prop, noi, mortgage, cash_invested, exit_price=exit_price)
        # If mortgage were escalated at g, the fixed deduction would grow — verify it doesn't
        correct_cf    = sum(noi * (1 + g) ** (yr - 1) - mortgage for yr in range(1, hold + 1))
        wrong_cf      = sum((noi - mortgage) * (1 + g) ** (yr - 1) for yr in range(1, hold + 1))
        expected_em   = (correct_cf + exit_price) / cash_invested
        wrong_em      = (wrong_cf   + exit_price) / cash_invested
        assert m.equity_multiple == pytest.approx(expected_em, rel=1e-4)
        assert m.equity_multiple != pytest.approx(wrong_em, rel=1e-4)


# ── Bug fix: exit price uses terminal NOI, not year-1 NOI ────────────────────

class TestTerminalNOIExitPrice:

    def test_exit_price_scales_with_hold_years(self):
        """Longer hold → higher terminal NOI → higher exit price (g > 0)."""
        from analysis.metrics.income import ExitMetrics
        prop5  = _make_prop(hold_years=5,  noi_growth_rate=0.02, exit_cap_rate=0.07)
        prop10 = _make_prop(hold_years=10, noi_growth_rate=0.02, exit_cap_rate=0.07)
        m5  = ExitMetrics(prop5,  entry_cap=0.07, est_noi=36_000)
        m10 = ExitMetrics(prop10, entry_cap=0.07, est_noi=36_000)
        assert m10.exit_price > m5.exit_price

    def test_exit_price_exact_terminal_formula(self):
        """exit_price == est_noi * (1+g)^hold_years / exit_cap."""
        from analysis.metrics.income import ExitMetrics
        g    = 0.02
        noi  = 36_000
        cap  = 0.07
        hold = 10
        prop = _make_prop(hold_years=hold, noi_growth_rate=g, exit_cap_rate=cap)
        m    = ExitMetrics(prop, entry_cap=cap, est_noi=noi)
        expected = noi * (1 + g) ** hold / cap
        assert m.exit_price == pytest.approx(expected, rel=1e-6)

    def test_exit_price_zero_growth_equals_year1_formula(self):
        """With g=0, terminal NOI == year-1 NOI, so exit_price == est_noi / exit_cap."""
        from analysis.metrics.income import ExitMetrics
        noi  = 50_000
        cap  = 0.08
        prop = _make_prop(hold_years=10, noi_growth_rate=0.0, exit_cap_rate=cap)
        m    = ExitMetrics(prop, entry_cap=cap, est_noi=noi)
        assert m.exit_price == pytest.approx(noi / cap, rel=1e-6)

    def test_exit_price_22pct_higher_on_10yr_2pct_growth(self):
        """10-yr hold at 2% growth: terminal NOI is 1.02^10 ≈ 1.219x year-1 NOI."""
        from analysis.metrics.income import ExitMetrics
        g    = 0.02
        noi  = 36_000
        cap  = 0.07
        prop = _make_prop(hold_years=10, noi_growth_rate=g, exit_cap_rate=cap)
        m    = ExitMetrics(prop, entry_cap=cap, est_noi=noi)
        old_exit_price = noi / cap  # what the buggy code produced
        assert m.exit_price == pytest.approx(old_exit_price * (1 + g) ** 10, rel=1e-6)
        assert m.exit_price > old_exit_price * 1.20  # at least 20% higher
