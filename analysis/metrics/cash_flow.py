from models.report_row import ReportRow
from analysis.metrics.grader import Grader


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
        return [
            ReportRow("Annual Cash Flow",  f"${self.annual_cash_flow:,.2f}",  self._cf_grade()),
            ReportRow("Monthly Cash Flow", f"${self.monthly_cash_flow:,.2f}",
                      Grader.grade(self.coc_return, 8.0, 0,
                                   labels=("GOOD", "FAIR", "POOR/BLEEDING"))),
            ReportRow("CoCR",              f"{self.coc_return:.2f}%",
                      Grader.grade(self.coc_return, 10, 5)),
        ]


class DebtMetrics:

    DEFAULT_STRESS_RATE = 0.02

    def __init__(self, est_noi: float, expense_ratio: float,
                 annual_mortgage: float, annual_rent: float,
                 loan_amount: float = 0.0, interest_rate: float = 0.05,
                 term_years: int = 25, stress_rate_bump: float = DEFAULT_STRESS_RATE):
        self.dscr             = est_noi / annual_mortgage if annual_mortgage else float('inf')
        self.be_ratio         = (annual_mortgage / est_noi) * 100 if est_noi > 0 else float('inf')
        net_rent_per_unit     = annual_rent * (1 - expense_ratio)
        self.break_even_point = (annual_mortgage / net_rent_per_unit) * 100 if net_rent_per_unit else 0
        self._annual_mortgage = annual_mortgage

        if loan_amount > 0 and term_years > 0:
            shocked_monthly_rate = (interest_rate + stress_rate_bump) / 12
            n = term_years * 12
            if shocked_monthly_rate == 0:
                stressed_monthly = loan_amount / n
            else:
                stressed_monthly = (
                    loan_amount
                    * (shocked_monthly_rate * (1 + shocked_monthly_rate) ** n)
                    / ((1 + shocked_monthly_rate) ** n - 1)
                )
            stressed_debt = stressed_monthly * 12
        else:
            stressed_debt = annual_mortgage * (1 + stress_rate_bump)

        self.stressed_dscr = est_noi / stressed_debt if stressed_debt else 0
        self._stress_rate_bump = stress_rate_bump

    def rows(self) -> list:
        stress_status = "PASS" if self.stressed_dscr >= 1.20 else "FAIL: High Rate Risk"
        return [
            ReportRow("DSCR",                   f"{self.dscr:.2f}",
                      Grader.grade(self.dscr, 1.5, 1.25,
                                   labels=("GOOD", "FAIR", "POOR/UNBANKABLE"))),
            ReportRow("Break-Even NOI",         f"${self._annual_mortgage:,.2f}",
                      Grader.grade(self.be_ratio, 65, 80, higher_is_better=False)),
            ReportRow("Break-Even NOI %",
                      "N/A" if self.be_ratio == float('inf') else f"{self.be_ratio:.2f}%",
                      Grader.grade(self.be_ratio, 75, 85, higher_is_better=False)),
            ReportRow("Break-Even Occupancy %", f"{self.break_even_point:.2f}%",
                      Grader.grade(self.break_even_point, 75, 85, higher_is_better=False)),
            ReportRow(f"Stress Test (+{self._stress_rate_bump*100:.0f}%)", f"{self.stressed_dscr:.2f} DSCR", stress_status),
        ]
