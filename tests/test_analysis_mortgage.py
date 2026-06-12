import pytest
from datetime import date, timedelta
from analysis.mortgage import (
    MortgageCalculator, DaysOnMarketCalculator,
    effective_monthly_rate, amortization_payment, remaining_balance,
    compounding_for_province,
)
from models.constants import CANADIAN_PROVINCES


class TestCompoundingForProvince:
    def test_canadian_provinces_are_semi_annual(self):
        for prov in CANADIAN_PROVINCES:
            assert compounding_for_province(prov) == "semi-annual", prov

    def test_us_state_is_monthly(self):
        assert compounding_for_province("CA") == "monthly"
        assert compounding_for_province("NY") == "monthly"

    def test_empty_defaults_to_monthly(self):
        assert compounding_for_province("") == "monthly"

    def test_case_insensitive(self):
        assert compounding_for_province("on") == "semi-annual"


class TestEffectiveMonthlyRate:
    def test_semi_annual_6pct(self):
        # (1 + 0.06/2)^(1/6) - 1
        expected = (1.03) ** (1 / 6) - 1
        assert effective_monthly_rate(0.06, "semi-annual") == pytest.approx(expected, rel=1e-9)

    def test_monthly_6pct(self):
        assert effective_monthly_rate(0.06, "monthly") == pytest.approx(0.06 / 12, rel=1e-9)

    def test_semi_annual_lower_than_monthly(self):
        assert effective_monthly_rate(0.06, "semi-annual") < effective_monthly_rate(0.06, "monthly")

    def test_zero_rate(self):
        assert effective_monthly_rate(0.0, "semi-annual") == pytest.approx(0.0)
        assert effective_monthly_rate(0.0, "monthly") == pytest.approx(0.0)


class TestAmortizationPayment:
    def test_canadian_100k_6pct_25yr(self):
        # Known-good: $100k @ 6% semi-annual, 25yr ≈ $639.81/mo
        # Computed: r = 1.03^(1/6)-1, (1+r)^300 = 1.03^50 ≈ 4.38391
        r = (1.03) ** (1 / 6) - 1
        n = 300
        expected = 100_000 * (r * (1 + r) ** n) / ((1 + r) ** n - 1)
        assert amortization_payment(100_000, 0.06, 300, "semi-annual") == pytest.approx(expected, rel=1e-6)
        # Must be less than US-convention payment
        assert amortization_payment(100_000, 0.06, 300, "semi-annual") < amortization_payment(100_000, 0.06, 300, "monthly")

    def test_us_100k_6pct_25yr(self):
        r = 0.06 / 12
        n = 300
        expected = 100_000 * (r * (1 + r) ** n) / ((1 + r) ** n - 1)
        assert amortization_payment(100_000, 0.06, 300, "monthly") == pytest.approx(expected, rel=1e-6)

    def test_zero_rate(self):
        assert amortization_payment(120_000, 0.0, 120, "semi-annual") == pytest.approx(1_000.0)

    def test_semi_annual_and_monthly_converge_near_zero_rate(self):
        # At very low rates the two conventions produce nearly identical results
        diff = abs(
            amortization_payment(100_000, 0.001, 300, "semi-annual")
            - amortization_payment(100_000, 0.001, 300, "monthly")
        )
        assert diff < 0.50  # less than $0.50/month difference at 0.1%


class TestRemainingBalance:
    def test_full_term_paid_off(self):
        assert remaining_balance(100_000, 0.06, 300, 300, "semi-annual") == 0.0

    def test_exceeds_term_is_zero(self):
        assert remaining_balance(100_000, 0.06, 300, 360, "semi-annual") == 0.0

    def test_balance_decreases_over_time(self):
        b10 = remaining_balance(500_000, 0.06, 300, 120, "semi-annual")
        b20 = remaining_balance(500_000, 0.06, 300, 240, "semi-annual")
        assert b10 > b20 > 0

    def test_zero_rate_balance(self):
        # 0% rate: linear paydown; 60 of 120 payments made → 50% left
        assert remaining_balance(120_000, 0.0, 120, 60, "semi-annual") == pytest.approx(60_000)


class TestMortgageCalculator:
    def _calc(self, price=500_000, down_pct=0.20, rate=0.06, term=25, hold=10,
              construction=0, province="ON"):
        return MortgageCalculator(price, down_pct, rate, term, hold, construction, province)

    def test_down_payment(self):
        m = self._calc(price=500_000, down_pct=0.25)
        assert m.down_payment == pytest.approx(125_000)

    def test_loan_amount(self):
        m = self._calc(price=500_000, down_pct=0.25)
        assert m.loan_amount == pytest.approx(375_000)

    def test_monthly_payment_positive(self):
        m = self._calc()
        assert m.monthly_payment > 0

    def test_annual_mortgage_is_12x_monthly(self):
        m = self._calc()
        assert m.annual_mortgage == pytest.approx(m.monthly_payment * 12)

    def test_canadian_compounding_for_canadian_province(self):
        m = self._calc(province="ON")
        assert m.compounding == "semi-annual"

    def test_monthly_compounding_for_us_state(self):
        m = self._calc(province="CA")
        assert m.compounding == "monthly"

    def test_known_payment_canadian_6pct_25yr(self):
        # $400k loan, 6% semi-annual, 25yr — Canadian convention
        # r = 1.03^(1/6) - 1; expected ≈ $2,560.52/mo (lower than US $2,564.43)
        r = (1.03) ** (1 / 6) - 1
        n = 300
        expected = 400_000 * (r * (1 + r) ** n) / ((1 + r) ** n - 1)
        m = MortgageCalculator(500_000, 0.20, 0.06, 25, 10, province="ON")
        assert m.monthly_payment == pytest.approx(expected, rel=0.001)

    def test_known_payment_us_6pct_25yr(self):
        # US convention: $400k loan, 6%/12/mo
        r = 0.06 / 12
        n = 300
        expected = 400_000 * (r * (1 + r) ** n) / ((1 + r) ** n - 1)
        m = MortgageCalculator(500_000, 0.20, 0.06, 25, 10, province="TX")
        assert m.monthly_payment == pytest.approx(expected, rel=0.001)

    def test_canadian_payment_less_than_us_payment(self):
        ca = MortgageCalculator(500_000, 0.20, 0.06, 25, 10, province="ON")
        us = MortgageCalculator(500_000, 0.20, 0.06, 25, 10, province="TX")
        assert ca.monthly_payment < us.monthly_payment

    def test_zero_interest_rate(self):
        m = MortgageCalculator(120_000, 0.0, 0.0, 10, 5)
        assert m.monthly_payment == pytest.approx(120_000 / 120, rel=0.001)

    def test_loan_balance_reduced_after_hold(self):
        m = self._calc(price=500_000, down_pct=0.20, rate=0.06, term=25, hold=10)
        assert 0 < m.loan_balance < m.loan_amount

    def test_loan_balance_zero_when_hold_exceeds_term(self):
        m = MortgageCalculator(500_000, 0.20, 0.05, 25, 30, province="ON")
        assert m.loan_balance == 0.0

    def test_zero_rate_loan_balance(self):
        m = MortgageCalculator(120_000, 0.0, 0.0, 10, 5)
        expected = 120_000 - m.monthly_payment * 60
        assert m.loan_balance == pytest.approx(expected, rel=0.001)

    def test_construction_cost_in_rows(self):
        m = MortgageCalculator(500_000, 0.20, 0.05, 25, 10, construction_cost=50_000, province="ON")
        rows = m.rows()
        metrics = [r.metric for r in rows]
        assert "Construction Cost" in metrics
        assert "Total Cash In" in metrics

    def test_rows_without_construction(self):
        m = self._calc()
        rows = m.rows()
        metrics = [r.metric for r in rows]
        assert "Loan Amount" in metrics
        assert "Monthly Payment" in metrics
        assert "Annual Debt Svc" in metrics
        assert "Compounding" in metrics
        assert "Construction Cost" not in metrics

    def test_rows_compounding_label_canadian(self):
        m = self._calc(province="ON")
        row = next(r for r in m.rows() if r.metric == "Compounding")
        assert "Semi-annual" in row.value or "CA" in row.value

    def test_rows_compounding_label_us(self):
        m = self._calc(province="TX")
        row = next(r for r in m.rows() if r.metric == "Compounding")
        assert "Monthly" in row.value or "US" in row.value

    def test_rows_returns_report_rows(self):
        from models.report_row import ReportRow
        m = self._calc()
        for row in m.rows():
            assert isinstance(row, ReportRow)

    def test_total_cash_in_value(self):
        m = MortgageCalculator(500_000, 0.25, 0.05, 25, 10, construction_cost=20_000, province="ON")
        rows = {r.metric: r for r in m.rows()}
        expected = m.down_payment + 20_000
        assert f"${expected:,.2f}" in rows["Total Cash In"].value

    def test_default_province_is_canadian(self):
        # Default province "ON" means semi-annual by default
        m = MortgageCalculator(500_000, 0.20, 0.06, 25, 10)
        assert m.compounding == "semi-annual"


class TestDaysOnMarketCalculator:
    def test_today(self):
        dom = DaysOnMarketCalculator(date.today().isoformat())
        assert dom.count == 0

    def test_yesterday(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        dom = DaysOnMarketCalculator(yesterday)
        assert dom.count == 1

    def test_90_days(self):
        past = (date.today() - timedelta(days=90)).isoformat()
        dom = DaysOnMarketCalculator(past)
        assert dom.count == 90

    def test_count_property(self):
        past = (date.today() - timedelta(days=45)).isoformat()
        dom = DaysOnMarketCalculator(past)
        assert dom.count == dom.days
