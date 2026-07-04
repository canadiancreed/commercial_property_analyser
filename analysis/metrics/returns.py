from typing import Optional
from models.report_row import ReportRow
from analysis.metrics.grader import Grader

METRIC_MARKET_STALENESS = "Market Staleness"


class ReturnMetrics:

    @staticmethod
    def _npv(cash_flows: list, rate: float) -> float:
        """Net present value of a period cash-flow array at ``rate`` (index 0 = period 0)."""
        return sum(cf / (1.0 + rate) ** t for t, cf in enumerate(cash_flows))

    @classmethod
    def _calc_irr(cls, cash_flows: list, guess: float = 0.10, iterations: int = 1000) -> float:
        """IRR of a period cash-flow array (index 0 = period-zero equity outflow, negative).

        Solved by bracketed bisection rather than Newton-Raphson: NPV is
        monotonic in the discount rate for a conventional stream (one sign
        change), so bracketing between just-above -100% and a large upper
        rate is guaranteed to converge on the true root. Newton with a fixed
        guess diverged on high-IRR / thin-equity streams and silently
        clamped a real return to -100%. Returns ``float('nan')`` when the
        stream has no conventional IRR (no sign change above -100%).
        """
        lo, hi = -0.999999, 1.0e6
        f_lo = cls._npv(cash_flows, lo)
        f_hi = cls._npv(cash_flows, hi)
        if f_lo == 0.0:
            return lo
        if f_hi == 0.0:
            return hi
        if (f_lo > 0.0) == (f_hi > 0.0):
            # No sign change in the bracket -> no conventional IRR exists
            # (e.g. a single flow, or a stream that never recovers the outlay).
            return float("nan")
        for _ in range(max(1, iterations)):
            mid   = (lo + hi) / 2.0
            f_mid = cls._npv(cash_flows, mid)
            if f_mid == 0.0 or (hi - lo) < 1e-12:
                return mid
            if (f_mid > 0.0) == (f_lo > 0.0):
                lo, f_lo = mid, f_mid
            else:
                hi, f_hi = mid, f_mid
        return (lo + hi) / 2.0

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

        if cash_invested > 0 and prop.hold_years > 0:
            try:
                r = self._calc_irr(period_flows)
            except Exception:
                r = float("nan")
            if r is None or r != r:            # nan -> no conventional IRR
                self.irr = -100.0
            else:
                self._assert_reconciles(r)     # raises if IRR and multiple diverge
                self.irr = r * 100.0
        else:
            self.irr = -100.0

    def _assert_reconciles(self, r: float) -> None:
        """Guard: the IRR must reconcile with the equity multiple because both
        are derived from ``self._period_flows``. The rigorous test is that the
        solved rate zeroes the NPV of that same array -- i.e. the positive and
        negative *discounted* cash flows actually cancel. When they do, IRR and
        multiple provably describe one stream and land where intuition expects:
        near multiple**(1/years) - 1, a touch higher when cash arrives during
        the hold. If they don't cancel the IRR is untrustworthy, so fail loud
        and trust the multiple rather than display an inconsistent pair.

        The residual is normalized by the largest discounted term rather than
        the raw cash total: at a deep negative rate over a long hold the late
        terms dominate and a correct root still leaves a large absolute
        residual, so the peak term is the honest yardstick for cancellation."""
        flows = self._period_flows
        resid = self._npv(flows, r)
        peak  = max(abs(cf) / (1.0 + r) ** t for t, cf in enumerate(flows)) or 1.0
        if abs(resid) > 1e-6 * peak:
            implied = (self.equity_multiple ** (1.0 / self.hold_years) - 1.0
                       if self.equity_multiple > 0 else float("nan"))
            raise ValueError(
                f"IRR {r * 100:.2f}% does not reconcile with equity multiple "
                f"{self.equity_multiple:.2f}x (implied {implied * 100:.2f}%/yr): "
                f"discounted cash flows do not cancel (NPV residual {resid:.2f} "
                f"vs peak term {peak:.2f}). Trust the multiple."
            )

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
