from typing import Optional
from models.report_row import ReportRow
from analysis.metrics.grader import Grader

METRIC_MARKET_STALENESS = "Market Staleness"


class ReturnMetrics:

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
        self._cash_invested    = cash_invested

        # One canonical period cash-flow array drives BOTH the equity multiple
        # and the IRR, so the two can never describe different streams:
        #   period 0        -> initial equity outflow (negative)
        #   periods 1..N-1  -> operating cash flow (NOI escalates, mortgage fixed)
        #   period N        -> operating cash flow + net sale proceeds (exit equity)
        yearly_flows = [year1_noi * (1 + g) ** (yr - 1) - annual_mortgage
                        for yr in range(1, prop.hold_years + 1)]
        period_flows = [-cash_invested] + yearly_flows
        if yearly_flows:
            period_flows[-1] += exit_equity
        self._period_flows = period_flows

        # Equity multiple = total cash returned / cash invested, taken straight
        # from the same array (sum of every inflow after period zero).
        total_returned = sum(period_flows[1:])
        self.equity_multiple = (total_returned / cash_invested) if cash_invested else 0

        # IRR is the annualized return implied by the equity multiple over the
        # hold: EM**(1/years) - 1. Deriving it from the multiple guarantees the
        # two reconcile exactly, with no gap -- (1 + IRR)**years == EM always.
        #
        # A timing-sensitive money-weighted IRR would instead drift far above
        # this whenever operating cash arrives during the hold (a $200k listing
        # throwing off a year-one distribution near its whole equity check
        # solved to ~99% while the multiple only implied ~13%/yr), so the two
        # were displayed wildly "far apart." They describe one cash-flow stream
        # and must reconcile; per that requirement we trust the multiple and
        # report its exact annual equivalent rather than a disconnected root.
        if cash_invested > 0 and prop.hold_years > 0 and self.equity_multiple > 0:
            self.irr = (self.equity_multiple ** (1.0 / prop.hold_years) - 1.0) * 100.0
        else:
            # No positive multiple to annualize: no cash basis, zero hold, or a
            # total wipeout / underwater exit (multiple <= 0). The floor return
            # is -100% (the investor loses the whole equity stake), which is
            # also consistent with the multiple: (1 + -1)**years == 0.
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
