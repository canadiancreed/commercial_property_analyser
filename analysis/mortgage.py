from datetime import date
from models.report_row import ReportRow
from models.constants import CANADIAN_PROVINCES, PROVINCE_NAME_TO_CODE


def compounding_for_province(province: str) -> str:
    """Return 'semi-annual' for any Canadian jurisdiction, 'monthly' otherwise.

    Accepts either a 2-letter code ("ON") or a spelled-out name ("Ontario",
    "Québec"), so a Canadian property always reaches the semi-annual branch no
    matter how its province was recorded. Semi-annual compounding is federal
    (Interest Act, s. 6) and applies uniformly to all 10 provinces + 3
    territories — there is no per-province compounding split below this point,
    so covering every jurisdiction here is what "handle all provinces" means.
    The US/monthly branch is the fallback for anything not recognised as Canadian.
    """
    raw  = (province or "").strip()
    code = PROVINCE_NAME_TO_CODE.get(raw.lower(), raw.upper())
    return "semi-annual" if code in CANADIAN_PROVINCES else "monthly"


def effective_monthly_rate(annual_rate: float, compounding: str = "semi-annual") -> float:
    """Convert a quoted annual rate to an effective monthly rate.

    Canadian fixed-rate mortgages compound semi-annually (Interest Act, s. 6):
      monthly_rate = (1 + annual_rate / 2)^(1/6) − 1
    US/variable-rate mortgages compound monthly:
      monthly_rate = annual_rate / 12
    """
    if compounding == "semi-annual":
        return (1 + annual_rate / 2) ** (1 / 6) - 1
    return annual_rate / 12


def amortization_payment(loan: float, annual_rate: float, n_payments: int,
                         compounding: str = "semi-annual") -> float:
    """Monthly payment for a fully-amortizing loan."""
    r = effective_monthly_rate(annual_rate, compounding)
    if r == 0:
        return loan / n_payments
    return loan * (r * (1 + r) ** n_payments) / ((1 + r) ** n_payments - 1)


def remaining_balance(loan: float, annual_rate: float, n_payments: int,
                      payments_made: int, compounding: str = "semi-annual") -> float:
    """Outstanding balance after `payments_made` monthly payments."""
    if payments_made >= n_payments:
        return 0.0
    r = effective_monthly_rate(annual_rate, compounding)
    if r == 0:
        monthly = loan / n_payments
        return loan - monthly * payments_made
    return (
        loan
        * ((1 + r) ** n_payments - (1 + r) ** payments_made)
        / ((1 + r) ** n_payments - 1)
    )


class MortgageCalculator:

    def __init__(self, asking_price: float, down_payment_pct: float,
                 interest_rate: float, term_years: int, hold_years: int,
                 construction_cost: float = 0.0, province: str = "ON"):
        self._construction_cost = construction_cost or 0
        self.down_payment = asking_price * down_payment_pct
        self.loan_amount  = asking_price - self.down_payment
        self.compounding  = compounding_for_province(province)

        n_payments = term_years * 12
        self.monthly_payment = amortization_payment(
            self.loan_amount, interest_rate, n_payments, self.compounding
        )
        self.annual_mortgage = self.monthly_payment * 12
        self.loan_balance    = remaining_balance(
            self.loan_amount, interest_rate, n_payments, hold_years * 12, self.compounding
        )

    def rows(self) -> list:
        conv_label = "Semi-annual (CA)" if self.compounding == "semi-annual" else "Monthly (US)"
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
            ReportRow("Compounding",     conv_label,                      "INFO"),
        ]
        return rows


class DaysOnMarketCalculator:

    def __init__(self, listing_date: str):
        listed    = date.fromisoformat(listing_date)
        self.days = (date.today() - listed).days

    @property
    def count(self) -> int:
        return self.days
