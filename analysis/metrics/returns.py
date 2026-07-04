from typing import Optional
from models.report_row import ReportRow
from analysis.metrics.grader import Grader

METRIC_MARKET_STALENESS = "Market Staleness"


class ReturnMetrics:

    @staticmethod
    def _calc_irr(cash_flows: list, guess: float = 0.10, iterations: int = 1000) -> float:
        """Newton-Raphson IRR on a list of cash flows (index 0 = year 0 outflow, negative)."""
        rate = guess
        for _ in range(iterations):
            npv  = sum(cf / (1 + rate) ** t for t, cf in enumerate(cash_flows))
            dnpv = sum(-t * cf / (1 + rate) ** (t + 1) for t, cf in enumerate(cash_flows))
            if dnpv == 0:
                break
            new_rate = rate - npv / dnpv
            if abs(new_rate - rate) < 1e-7:
                rate = new_rate
                break
            rate = new_rate
        return rate

    def __init__(self, prop, year1_noi: float, annual_mortgage: float, cash_invested: float,
                 exit_price: float, loan_balance: float = 0.0, noi_growth_source: str = "default",
                 noi_growth_rate: Optional[float] = None):
        exit_equity = exit_price - loan_balance
        if noi_growth_rate is not None:
            g = noi_growth_rate
        else:
            _g = getattr(prop, "noi_growth_rate", None)
            g = _g if _g is not None else 0.02
        self.hold_years        = prop.hold_years
        self.noi_growth_rate   = g
        self.noi_growth_source = noi_growth_source

        yearly_flows = [year1_noi * (1 + g) ** (yr - 1) - annual_mortgage
                        for yr in range(1, prop.hold_years + 1)]
        total_cash_flow = sum(yearly_flows)
        self._cash_invested  = cash_invested
        self.equity_multiple = ((total_cash_flow + exit_equity) / cash_invested
                                if cash_invested else 0)

        if cash_invested > 0 and prop.hold_years > 0:
            flows = [-cash_invested] + yearly_flows
            flows[-1] += exit_equity
            try:
                r = self._calc_irr(flows)
                self.irr = r * 100 if -1 < r < 10 else -100.0
            except Exception:
                self.irr = -100.0
        else:
            self.irr = -100.0

    def _em_grade(self) -> str:
        if self.equity_multiple >= 2.0: return "EXCELLENT"
        if self.equity_multiple >= 1.5: return "GOOD"
        if self.equity_multiple >= 1.2: return "FAIR"
        return "POOR (Underperforming)"

    def rows(self) -> list:
        stale = "STALE" in self.noi_growth_source.upper()
        growth_grade = "WARN — refresh demographics data" if stale else ""
        if self._cash_invested:
            em_value, em_grade = f"{self.equity_multiple:.2f}x", self._em_grade()
        else:
            em_value, em_grade = "N/A (no cash invested)", "WARN — no cash basis"
        return [
            ReportRow(f"IRR ({self.hold_years}-Yr)", f"{self.irr:.2f}%",
                      Grader.grade(self.irr, 15.0, 10.0)),
            ReportRow("Equity Multiple",      em_value, em_grade),
            ReportRow("NOI Growth Assumption", f"{self.noi_growth_rate * 100:.2f}%/yr  ({self.noi_growth_source})",
                      growth_grade),
        ]


class MarketMetrics:

    def __init__(self, est_noi: float, cash_invested: float, est_expenses: float,
                 annual_mortgage: float, days_on_market: int, vacancy_rate: float = 0.05):
        self.celoc_score        = (est_noi / cash_invested) * 100 if cash_invested else 0
        self._cash_invested     = cash_invested
        monthly_carry           = (est_expenses + annual_mortgage) / 12
        self.total_seller_bleed = monthly_carry * (days_on_market / 30) * vacancy_rate
        self._days_on_market    = days_on_market

    def _celoc_grade(self) -> str:
        if self.celoc_score >= 80: return "FAST CELOC"
        if self.celoc_score >= 60: return "CELOC POSSIBLE"
        if self.celoc_score >= 40: return "LENDER FRICTION"
        return "NO CELOC"

    def rows(self) -> list:
        if self._cash_invested:
            celoc_value, celoc_grade = f"{self.celoc_score:.2f}", self._celoc_grade()
        else:
            celoc_value, celoc_grade = "N/A (no cash invested)", "WARN — no cash basis"
        return [
            ReportRow("CELOC Speed Score", celoc_value,                       celoc_grade),
            ReportRow(METRIC_MARKET_STALENESS,  f"{self._days_on_market} Days",
                      Grader.grade(self._days_on_market, 150, 90)),
            ReportRow("Seller Bleed",      f"${self.total_seller_bleed:,.2f}",
                      Grader.grade(self.total_seller_bleed, 25000, 5000)),
        ]
