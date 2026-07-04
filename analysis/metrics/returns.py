from typing import Optional
import numpy_financial as npf
from models.report_row import ReportRow
from analysis.metrics.grader import Grader
from analysis.underwriting_config import load_underwriting_config

METRIC_MARKET_STALENESS = "Market Staleness"

# The guardrail below allows IRR to sit a hair below the multiple's implied
# compound rate for floating-point noise only; a genuine shortfall raises.
_IRR_EM_TOLERANCE = 1e-6


class ReturnMetrics:

    def __init__(self, prop, year1_noi: float, annual_mortgage: float, cash_invested: float,
                 exit_price: float, loan_balance: float = 0.0, noi_growth_source: str = "default",
                 noi_growth_rate: Optional[float] = None, selling_costs: float = 0.0):
        # Net sale proceeds = gross exit price minus the loan payoff at sale,
        # minus selling costs when the record carries them (0 otherwise).
        # ``loan_balance`` is the amortized outstanding balance at year N (0 once
        # the loan is fully paid off before the modeled sale), NOT the original
        # loan amount. The investor only receives the net.
        net_sale_proceeds = exit_price - loan_balance - selling_costs
        if noi_growth_rate is not None:
            g = noi_growth_rate
        else:
            _g = getattr(prop, "noi_growth_rate", None)
            g = _g if _g is not None else load_underwriting_config()["noi_growth_default"]
        self.hold_years        = prop.hold_years
        self.noi_growth_rate   = g
        self.noi_growth_source = noi_growth_source
        self._cash_invested    = cash_invested

        # Step 1 -- ONE shared cash-flow array (length N + 1) feeds BOTH metrics:
        #   cash_flows[0]      = -equity invested            (period-zero outflow)
        #   cash_flows[1..N-1] = operating cash flow         (NOI escalates at g,
        #                                                     mortgage fixed)
        #   cash_flows[N]      = operating cash flow + net sale proceeds
        # Neither metric is derived from the other; both read this one array.
        operating = [year1_noi * (1 + g) ** (yr - 1) - annual_mortgage
                     for yr in range(1, prop.hold_years + 1)]
        cash_flows = [-cash_invested] + operating
        if operating:
            cash_flows[-1] += net_sale_proceeds
        self._cash_flows        = cash_flows
        self._net_sale_proceeds = net_sale_proceeds

        if cash_invested > 0 and prop.hold_years > 0:
            N = prop.hold_years
            # Step 2a -- Equity multiple: total positive cash returned over the
            # equity invested, straight from the shared array (net proceeds, not
            # gross, are already baked into the final period).
            self.equity_multiple = sum(cf for cf in cash_flows if cf > 0) / cash_invested
            # Step 2b -- IRR: computed from the SAME array so it reflects the
            # timing of the cash flows. NOT back-derived from the multiple.
            # numpy_financial.irr returns nan when the stream has no usable
            # root (e.g. an underwater exit whose flows never turn positive).
            # There is no honest rate to print then, so irr stays None and the
            # report reads "IRR not meaningful" -- never a substitute number
            # dressed up as a real return.
            irr = float(npf.irr(cash_flows))
            self.irr = irr * 100.0 if irr == irr else None
            # Step 3 -- Guardrail (assertion only, never a fallback value).
            # Its premise -- cash received during the hold lifts IRR to at or
            # above the multiple's implied compound rate -- only holds when
            # there are NO interim capital calls. A leveraged deal whose
            # mortgage exceeds NOI in the early years injects cash mid-hold,
            # which legitimately pulls IRR below the implied rate; that is not a
            # broken array. So the assertion runs in the regime where its
            # premise applies (all post-entry flows non-negative), and there a
            # shortfall means the shared cash-flow array is wrong -> raise.
            no_capital_calls = all(cf >= 0 for cf in cash_flows[1:])
            if no_capital_calls and self.equity_multiple > 0:
                # A single outflow at t0 plus non-negative later flows has
                # exactly one sign change, so a real IRR must exist here; a
                # missing root in this regime is itself a broken array.
                implied_rate = self.equity_multiple ** (1.0 / N) - 1.0
                if self.irr is None or not (self.irr / 100.0 >= implied_rate - _IRR_EM_TOLERANCE):
                    irr_desc = "none" if self.irr is None else f"{self.irr:.2f}%"
                    raise ValueError(
                        f"IRR/EM mismatch — recheck cash-flow array "
                        f"(IRR {irr_desc} < implied {implied_rate * 100:.2f}%/yr "
                        f"from {self.equity_multiple:.2f}x over {N}yr)"
                    )
        else:
            # No equity basis or zero hold: nothing to annualize, so there is
            # no rate to report.
            self.equity_multiple = (sum(cf for cf in cash_flows if cf > 0) / cash_invested
                                    if cash_invested else 0)
            self.irr = None

    def _em_grade(self) -> str:
        if self.equity_multiple >= 2.0: return "EXCELLENT"
        if self.equity_multiple >= 1.5: return "GOOD"
        if self.equity_multiple >= 1.2: return "FAIR"
        return "POOR (Underperforming)"

    def _growth_grade(self) -> str:
        # Bank of Canada inflation-control target (config: inflation_rate) sits
        # within a 1%-3% band around the target — the standard external
        # yardstick for "is nominal growth keeping pace with inflation".
        # >=1pt above target outgrows the band (GOOD); within the +/-1pt band
        # tracks it (FAIR); below the band loses real value over the hold
        # (POOR) even when nominally positive.
        inflation = load_underwriting_config()["inflation_rate"] * 100
        return Grader.grade(self.noi_growth_rate * 100, inflation + 1.0, inflation - 1.0)

    def rows(self) -> list:
        stale = "STALE" in self.noi_growth_source.upper()
        # Staleness is a data-quality caveat layered on the rate itself, so it
        # overrides the value-based grade rather than stacking with it.
        growth_grade = "FAIR — refresh demographics data" if stale else self._growth_grade()
        if self._cash_invested:
            em_value, em_grade = f"{self.equity_multiple:.2f}x", self._em_grade()
        else:
            em_value, em_grade = "N/A (no cash invested)", "WARN — no cash basis"
        if self.irr is None:
            irr_value, irr_grade = "IRR not meaningful", "WARN — no real IRR for this cash-flow stream"
        else:
            irr_value, irr_grade = f"{self.irr:.2f}%", Grader.grade(self.irr, 15.0, 10.0)
        return [
            ReportRow(f"IRR ({self.hold_years}-Yr)", irr_value, irr_grade),
            ReportRow("Equity Multiple",      em_value, em_grade),
            ReportRow("NOI Growth Assumption", f"{self.noi_growth_rate * 100:.2f}%/yr",
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
