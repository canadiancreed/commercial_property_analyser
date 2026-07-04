from typing import Optional
from models.report_row import ReportRow
from analysis.metrics.grader import Grader
from models.constants import EXPENSE_RATIO_RANGES
from analysis.underwriting_config import load_underwriting_config


INCOME_METRIC_NAMES: frozenset = frozenset({
    "Gross Potential Rent",
    "Effective Gross Income",
    "NOI",
    "Cap Rate",
})


class IncomeMetrics:

    def __init__(self, prop, annual_rent: float, rent_breakdown: list,
                 vacancy_rate: float = None):
        self.annual_rent    = annual_rent
        self.rent_breakdown = rent_breakdown
        self.vacancy_rate   = vacancy_rate if vacancy_rate is not None else (prop.vacancy_rate or 0.0)
        self.egi            = annual_rent * (1 - self.vacancy_rate)  # Effective Gross Income
        self.est_expenses   = self.egi * prop.expense_ratio
        self.est_noi        = self.egi - self.est_expenses
        self._cost_basis    = prop.asking_price + (prop.construction_cost or 0)
        self.cap_rate       = (self.est_noi / self._cost_basis) * 100
        self.oer_ratio      = (self.est_expenses / self.egi) * 100
        self.entry_cap      = self.est_noi / self._cost_basis
        self._prop          = prop

    def _expense_grade(self) -> str:
        p     = self._prop
        ratio = p.expense_ratio
        key   = "nnn" if p.lease_type.upper() == "NNN" else (p.property_type or "").strip().lower()
        bounds = EXPENSE_RATIO_RANGES.get(key)
        if bounds is None:
            return "INFO"
        lo, hi = bounds
        if ratio < lo:
            return f"WARNING: Low for {p.property_type or 'this type'} (typical {lo*100:.0f}–{hi*100:.0f}%)"
        if ratio > hi:
            return f"WARNING: High for {p.property_type or 'this type'} (typical {lo*100:.0f}–{hi*100:.0f}%)"
        return "GOOD"

    def _oer_grade(self) -> str:
        if self._prop.lease_type.upper() == "NNN":
            return "GOOD" if self.oer_ratio <= 15 else "FAIR" if self.oer_ratio <= 25 else "POOR"
        return "GOOD" if 35 <= self.oer_ratio <= 45 else "FAIR" if 30 <= self.oer_ratio <= 50 else "POOR"

    def rows(self) -> list:
        p    = self._prop
        rows = [ReportRow("  Rent Detail", line, "") for line in self.rent_breakdown]
        rows += [
            ReportRow("Gross Potential Rent", f"${self.annual_rent:,.2f}", "INFO"),
            *([] if (self._prop.property_type or "").strip().lower() == "hotel" else
              [ReportRow("Vacancy Rate", f"{self.vacancy_rate * 100:.1f}%", "INFO")]),
            ReportRow("Effective Gross Income", f"${self.egi:,.2f}",      "INFO"),
            ReportRow("Expense Ratio",    f"{p.expense_ratio * 100}%",   self._expense_grade()),
            ReportRow("NOI",              f"${self.est_noi:,.2f}",
                      Grader.grade(self.entry_cap, 0.07, 0.05)),
            ReportRow("Cap Rate",         f"{self.cap_rate:.2f}%",
                      Grader.grade(self.cap_rate, 7.5, 5.5)),
            ReportRow("Op Expense Ratio", f"{self.oer_ratio:.2f}%",      self._oer_grade()),
        ]
        return rows


class ExitCapEstimator:

    MAX_HOLD_FOR_AGING = 10

    def __init__(self, entry_cap: float, hold_years: int, market_cap_rate: Optional[float] = None):
        cfg = load_underwriting_config()
        self.entry_cap          = entry_cap
        self.hold_years         = hold_years
        self.market_cap_rate    = market_cap_rate
        self._aging_bps_per_year = cfg["exit_cap_aging_bps_per_year"]
        self._market_drift_bps   = cfg["exit_cap_spread_bps"]

    def estimate(self) -> float:
        effective_hold = min(self.hold_years, self.MAX_HOLD_FOR_AGING)
        aging_spread = (self._aging_bps_per_year * effective_hold) / 10000
        drift_spread = self._market_drift_bps / 10000
        formula_exit = self.entry_cap + aging_spread + drift_spread
        if self.market_cap_rate is not None:
            return round((formula_exit + self.market_cap_rate) / 2, 4)
        return round(formula_exit, 4)


class ExitMetrics:

    def __init__(self, prop, entry_cap: float, est_noi: float, loan_balance: float = 0.0,
                 noi_growth_rate: Optional[float] = None):
        self.exit_cap = (prop.exit_cap_rate if prop.exit_cap_rate is not None
                         else ExitCapEstimator(entry_cap, prop.hold_years, prop.market_cap_rate).estimate())
        # Required to capitalize the exit value — a zero/negative cap would
        # silently collapse exit price to 0. Fail loudly instead.
        if not self.exit_cap or self.exit_cap <= 0:
            raise ValueError(
                f"exit cap rate must be > 0 to capitalize exit value (got {self.exit_cap!r})"
            )
        self.exit_cap_ratio = entry_cap / self.exit_cap
        if noi_growth_rate is not None:
            g = noi_growth_rate
        else:
            _g = getattr(prop, "noi_growth_rate", None)
            g = _g if _g is not None else load_underwriting_config()["noi_growth_default"]
        terminal_noi        = est_noi * (1 + g) ** prop.hold_years
        self.exit_price     = terminal_noi / self.exit_cap
        self._entry_cap     = entry_cap
        self._cost_basis    = prop.asking_price + (prop.construction_cost or 0)
        self._loan_balance  = loan_balance

    def _exit_cap_grade(self) -> str:
        spread_bps = (self.exit_cap - self._entry_cap) * 10000
        if spread_bps <= 150: return "GOOD"
        if spread_bps <= 250: return "FAIR"
        return "POOR"

    def rows(self) -> list:
        if self._loan_balance > 0:
            exit_price_grade = ("GOOD" if self.exit_price >= self._loan_balance * 1.20 else
                                "FAIR" if self.exit_price >= self._loan_balance else "POOR")
        else:
            exit_price_grade = ("GOOD" if self.exit_price >= self._cost_basis else
                                "FAIR" if self.exit_price >= self._cost_basis * 0.85 else "POOR")
        return [
            ReportRow("Exit Cap Rate",  f"{self.exit_cap * 100:.2f}%",  self._exit_cap_grade()),
            ReportRow("Exit Cap Ratio", f"{self.exit_cap_ratio:.2f}",
                      Grader.grade(self.exit_cap_ratio, 0.90, 0.75)),
            ReportRow("Exit Price",     f"${self.exit_price:,.2f}", exit_price_grade),
        ]
