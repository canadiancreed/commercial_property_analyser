import pytest
from datetime import date, timedelta
from analysis.mortgage import MortgageCalculator, DaysOnMarketCalculator


class TestMortgageCalculator:
    def _calc(self, price=500_000, down_pct=0.20, rate=0.06, term=25, hold=10, construction=0):
        return MortgageCalculator(price, down_pct, rate, term, hold, construction)

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

    def test_known_payment_calculation(self):
        # $400k loan, 6% / 25yr → ~$2,564/mo (standard amortization)
        m = MortgageCalculator(500_000, 0.20, 0.06, 25, 10)
        assert m.monthly_payment == pytest.approx(2564.43, rel=0.01)

    def test_zero_interest_rate(self):
        m = MortgageCalculator(120_000, 0.0, 0.0, 10, 5)
        # With 0% rate: monthly = loan / n_payments
        assert m.monthly_payment == pytest.approx(120_000 / 120, rel=0.001)

    def test_loan_balance_reduced_after_hold(self):
        m = self._calc(price=500_000, down_pct=0.20, rate=0.06, term=25, hold=10)
        assert 0 < m.loan_balance < m.loan_amount

    def test_loan_balance_zero_when_hold_exceeds_term(self):
        m = MortgageCalculator(500_000, 0.20, 0.05, 25, 30)
        assert m.loan_balance == 0.0

    def test_zero_rate_loan_balance(self):
        m = MortgageCalculator(120_000, 0.0, 0.0, 10, 5)
        # 5 of 10 years paid → half outstanding
        expected = 120_000 - m.monthly_payment * 60
        assert m.loan_balance == pytest.approx(expected, rel=0.001)

    def test_construction_cost_in_rows(self):
        m = MortgageCalculator(500_000, 0.20, 0.05, 25, 10, construction_cost=50_000)
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
        assert "Construction Cost" not in metrics

    def test_rows_returns_report_rows(self):
        from models.report_row import ReportRow
        m = self._calc()
        for row in m.rows():
            assert isinstance(row, ReportRow)

    def test_total_cash_in_value(self):
        m = MortgageCalculator(500_000, 0.25, 0.05, 25, 10, construction_cost=20_000)
        rows = {r.metric: r for r in m.rows()}
        expected = m.down_payment + 20_000
        assert f"${expected:,.2f}" in rows["Total Cash In"].value


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
