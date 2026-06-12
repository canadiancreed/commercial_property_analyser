from datetime import date
from models.report_row import ReportRow


class MortgageCalculator:

    def __init__(self, asking_price: float, down_payment_pct: float,
                 interest_rate: float, term_years: int, hold_years: int,
                 construction_cost: float = 0.0):
        self._construction_cost = construction_cost or 0
        self.down_payment = asking_price * down_payment_pct
        self.loan_amount  = asking_price - self.down_payment

        monthly_rate = interest_rate / 12
        n_payments   = term_years * 12

        if monthly_rate == 0:
            self.monthly_payment = self.loan_amount / n_payments
        else:
            self.monthly_payment = (
                self.loan_amount
                * (monthly_rate * (1 + monthly_rate) ** n_payments)
                / ((1 + monthly_rate) ** n_payments - 1)
            )

        self.annual_mortgage = self.monthly_payment * 12

        payments_made = hold_years * 12
        if payments_made >= n_payments:
            self.loan_balance = 0.0
        elif monthly_rate == 0:
            self.loan_balance = self.loan_amount - (self.monthly_payment * payments_made)
        else:
            self.loan_balance = (
                self.loan_amount
                * ((1 + monthly_rate) ** n_payments - (1 + monthly_rate) ** payments_made)
                / ((1 + monthly_rate) ** n_payments - 1)
            )

    def rows(self) -> list:
        rows = [
            ReportRow("Loan Amount",     f"${self.loan_amount:,.2f}",     "INFO"),
            ReportRow("Down Payment",    f"${self.down_payment:,.2f}",    "INFO"),
        ]
        if self._construction_cost:
            rows.append(ReportRow("Construction Cost", f"${self._construction_cost:,.2f}", "INFO"))
            rows.append(ReportRow("Total Cash In",     f"${self.down_payment + self._construction_cost:,.2f}", "INFO"))
        rows += [
            ReportRow("Monthly Payment", f"${self.monthly_payment:,.2f}", "INFO"),
            ReportRow("Annual Debt Svc", f"${self.annual_mortgage:,.2f}", "INFO"),
        ]
        return rows


class DaysOnMarketCalculator:

    def __init__(self, listing_date: str):
        listed    = date.fromisoformat(listing_date)
        self.days = (date.today() - listed).days

    @property
    def count(self) -> int:
        return self.days
