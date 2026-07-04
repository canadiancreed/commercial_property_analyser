from models.report_row import ReportRow
from analysis.metrics.grader import Grader
from analysis.mortgage import amortization_payment


class CashFlowMetrics:

    def __init__(self, est_noi: float, annual_mortgage: float, down_payment: float,
                 construction_cost: float = 0.0):
        self.cash_invested     = down_payment + (construction_cost or 0)
        self.annual_cash_flow  = est_noi - annual_mortgage
        self.monthly_cash_flow = self.annual_cash_flow / 12
        self.coc_return        = (self.annual_cash_flow / self.cash_invested) * 100 if self.cash_invested else 0

    def _cf_grade(self) -> str:
        if self.annual_cash_flow <= 0: return "POOR/BLEEDING"
        if self.coc_return >= 8.0:     return "GOOD"
        return "FAIR (Thin Margin)"

    def rows(self) -> list:
        if self.cash_invested:
            cocr_value = f"{self.coc_return:.2f}%"
            cocr_grade = Grader.grade(self.coc_return, 10, 5)
        else:
            # No cash basis — a bare 0.00% would read as a real (poor) return.
            cocr_value = "N/A (no cash invested)"
            cocr_grade = "WARN — no cash basis"
        return [
            ReportRow("Annual Cash Flow",  f"${self.annual_cash_flow:,.2f}",  self._cf_grade()),
            ReportRow("Monthly Cash Flow", f"${self.monthly_cash_flow:,.2f}",
                      Grader.grade(self.coc_return, 8.0, 0,
                                   labels=("GOOD", "FAIR", "POOR/BLEEDING"))),
            ReportRow("CoCR",              cocr_value, cocr_grade),
        ]


class DebtMetrics:

    DEFAULT_STRESS_RATE = 0.02
    DEFAULT_STRESS_MIN_DSCR = 1.20

    def __init__(self, est_noi: float, expense_ratio: float,
                 annual_mortgage: float, annual_rent: float,
                 loan_amount: float = 0.0, interest_rate: float = 0.05,
                 term_years: int = 25, stress_rate_bump: float = DEFAULT_STRESS_RATE,
                 stress_min_dscr: float = DEFAULT_STRESS_MIN_DSCR,
                 compounding: str = "semi-annual"):
        self.dscr             = est_noi / annual_mortgage if annual_mortgage else float('inf')
        self.be_ratio         = (annual_mortgage / est_noi) * 100 if est_noi > 0 else float('inf')
        net_rent_per_unit     = annual_rent * (1 - expense_ratio)
        self.break_even_point = (annual_mortgage / net_rent_per_unit) * 100 if net_rent_per_unit else 0
        self._net_rent_per_unit = net_rent_per_unit
        self._annual_mortgage = annual_mortgage

        if loan_amount > 0 and term_years > 0:
            stressed_monthly = amortization_payment(
                loan_amount, interest_rate + stress_rate_bump, term_years * 12, compounding
            )
            stressed_debt = stressed_monthly * 12
        else:
            stressed_debt = annual_mortgage * (1 + stress_rate_bump)

        self.stressed_dscr = est_noi / stressed_debt if stressed_debt else 0
        self._stress_rate_bump = stress_rate_bump
        self._stress_min_dscr = stress_min_dscr

    def rows(self) -> list:
        no_debt = not self._annual_mortgage
        if no_debt:
            # No leverage — DSCR is infinite and stress is meaningless. Show a
            # label rather than a bare "inf"/"0.00" that reads like a real ratio.
            dscr_value,  dscr_grade   = "N/A (no debt)", "INFO"
            stress_value, stress_grade = "N/A (no debt)", "INFO"
        else:
            dscr_value  = f"{self.dscr:.2f}"
            dscr_grade  = Grader.grade(self.dscr, 1.5, 1.25,
                                       labels=("GOOD", "FAIR", "POOR/UNBANKABLE"))
            stress_value  = f"{self.stressed_dscr:.2f} DSCR"
            stress_grade  = ("PASS" if self.stressed_dscr >= self._stress_min_dscr
                              else "FAIL: High Rate Risk")
        be_occ_value = ("N/A" if not self._net_rent_per_unit
                        else f"{self.break_even_point:.2f}%")
        return [
            ReportRow("DSCR",                   dscr_value, dscr_grade),
            ReportRow("Break-Even NOI",         f"${self._annual_mortgage:,.2f}",
                      Grader.grade(self.be_ratio, 65, 80, higher_is_better=False)),
            ReportRow("Break-Even NOI %",
                      "N/A" if self.be_ratio == float('inf') else f"{self.be_ratio:.2f}%",
                      Grader.grade(self.be_ratio, 75, 85, higher_is_better=False)),
            ReportRow("Break-Even Occupancy %", be_occ_value,
                      Grader.grade(self.break_even_point, 75, 85, higher_is_better=False)),
            ReportRow(f"Stress Test (+{self._stress_rate_bump*100:.0f}%)", stress_value, stress_grade),
        ]
