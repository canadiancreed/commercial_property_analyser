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
                 vacancy_rate: float = None, rollup=None):
        self.annual_rent    = annual_rent
        self.rent_breakdown = rent_breakdown
        # ``rollup`` (a MixedUseComponents) replaces the single building-wide
        # vacancy/expense-ratio path with a per-component computation — EGI, opex,
        # and NOI are already blended in it. Only mixed_use passes one; every other
        # property type keeps the exact original single-ratio behavior.
        self._rollup = rollup
        if rollup is not None:
            self.vacancy_rate = rollup.blended_vacancy
            self.egi          = rollup.egi
            self.est_expenses = rollup.total_opex
            self.est_noi      = rollup.noi
        else:
            self.vacancy_rate = vacancy_rate if vacancy_rate is not None else (prop.vacancy_rate or 0.0)
            self.egi          = annual_rent * (1 - self.vacancy_rate)  # Effective Gross Income
            self.est_expenses = self.egi * prop.expense_ratio
            self.est_noi      = self.egi - self.est_expenses
        self._cost_basis    = prop.asking_price + (prop.construction_cost or 0)
        self.cap_rate       = (self.est_noi / self._cost_basis) * 100
        self.oer_ratio      = (self.est_expenses / self.egi) * 100 if self.egi else 0.0
        self.entry_cap      = self.est_noi / self._cost_basis
        self._prop          = prop
        self._cap_rate_risk_threshold = load_underwriting_config()["cap_rate_risk_threshold_pct"]
        self.cap_rate_flagged = self.cap_rate > self._cap_rate_risk_threshold

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
            (ReportRow("Expense Ratio",
                       f"{self._rollup.blended_expense_ratio * 100:.2f}% (blended)", "INFO")
             if self._rollup is not None else
             ReportRow("Expense Ratio", f"{p.expense_ratio * 100}%", self._expense_grade())),
            ReportRow("NOI",              f"${self.est_noi:,.2f}",
                      Grader.grade(self.entry_cap, 0.07, 0.05)),
            ReportRow("Cap Rate",         f"{self.cap_rate:.2f}%",
                      Grader.grade(self.cap_rate, 7.5, 5.5)),
            ReportRow(
                "  Cap Rate Risk Check",
                (f"Above {self._cap_rate_risk_threshold:.1f}% regional norm"
                 if self.cap_rate_flagged else "Within normal range"),
                ("CAUTION: verify underlying risk (illiquidity, vacancy, value erosion)"
                 if self.cap_rate_flagged else "OK"),
            ),
            ReportRow("Op Expense Ratio", f"{self.oer_ratio:.2f}%",      self._oer_grade()),
        ]
        return rows


class MixedUseComponents:
    """Per-component income/expense engine for mixed_use ONLY.

    A single building-wide expense ratio overstates NOI whenever a mixed-use
    listing carries a net/NNN lease tag: under the Ontario RTA (2006) residential
    maintenance obligations are non-waivable and costs cannot be passed to
    residential tenants, so a net/NNN tag can only describe the COMMERCIAL lease.
    This splits the rollup by component and applies the lease tag to the
    commercial expense-ratio lookup alone; the residential component always uses
    the residential default, no matter the tag. That guard is the point of the
    class. EGI / opex / NOI here become the figures the rest of the card derives
    from (cap, DSCR, cash flow, BEO, financing) — unchanged downstream.
    """

    def __init__(self, comm_gpr: float, res_gpr: float, lease_type: str, *,
                 comm_vacancy: float, res_vacancy: float,
                 comm_gross_ratio: float, comm_nnn_ratio: float, res_ratio: float,
                 majority_threshold: float, commercial_lease_expiry: Optional[str] = None):
        self.comm_gpr = comm_gpr or 0.0
        self.res_gpr  = res_gpr or 0.0
        self.gpr      = self.comm_gpr + self.res_gpr

        self.comm_egi = self.comm_gpr * (1 - comm_vacancy)
        self.res_egi  = self.res_gpr * (1 - res_vacancy)
        self.egi      = self.comm_egi + self.res_egi

        self._is_nnn    = (lease_type or "").strip().upper() == "NNN"
        self.comm_ratio = comm_nnn_ratio if self._is_nnn else comm_gross_ratio
        self.res_ratio  = res_ratio                       # ALWAYS residential default
        self.comm_opex  = self.comm_egi * self.comm_ratio
        self.res_opex   = self.res_egi * self.res_ratio
        self.total_opex = self.comm_opex + self.res_opex
        self.noi        = self.egi - self.total_opex

        self.blended_vacancy       = (1 - self.egi / self.gpr) if self.gpr else 0.0
        self.blended_expense_ratio = (self.total_opex / self.egi) if self.egi else 0.0
        self.commercial_share      = (self.comm_gpr / self.gpr) if self.gpr else 0.0
        self._majority_threshold   = majority_threshold
        self.commercial_majority   = self.commercial_share > majority_threshold
        self._lease_expiry         = commercial_lease_expiry

    def rows(self) -> list:
        rows = [ReportRow("Commercial Share of GPR", f"{self.commercial_share * 100:.2f}%", "INFO")]
        if self.commercial_majority:
            rows.append(ReportRow(
                "Commercial Majority",
                "Commercial-majority income — lenders may classify and price this as "
                "commercial, not mixed-use.",
                "CAUTION",
            ))
        if self._lease_expiry:
            rows.append(ReportRow("Commercial Lease Expiry", str(self._lease_expiry), "INFO"))
        else:
            rows.append(ReportRow("Commercial Lease Expiry", "unknown ⚠", "CAUTION"))
        return rows


class IncomeConfidenceMetrics:
    """
    Data-confidence axis (separate from structural/debt risk): how much of a
    property's income is stated in the listing versus imputed from a city-wide
    bedroom-type average. Imputed lines carry the coefficient of variation of
    the SAME area-rent sample the average came from — no invented risk premium.

    verified_income_pct / confidence_multiplier are informational only; they do
    NOT alter DSCR, cap rate, NOI, IRR, or any other dollar-based metric. The
    multiplier is applied to the overall property score alone (scoring/scorer.py).
    """

    def __init__(self, total_income: float, verified_income: float,
                 imputed_lines: list, cap_rate: Optional[float] = None):
        cfg = load_underwriting_config()
        self.total_income   = total_income
        self.verified_income = verified_income
        self.imputed_lines   = imputed_lines  # list of (amount, cov)
        self.imputed_income  = sum(a for a, _ in imputed_lines)
        self.verified_income_pct = (
            (verified_income / total_income) * 100 if total_income else 100.0
        )
        self.income_uncertainty = (
            sum((a / total_income) * cov for a, cov in imputed_lines) if total_income else 0.0
        )
        start      = cfg["confidence_uncertainty_start"]
        steepness  = cfg["confidence_steepness"]
        floor      = cfg["confidence_floor"]
        haircut = steepness * max(0.0, self.income_uncertainty - start)
        multiplier = 1.0 - haircut
        # Issue 3: a cap rate well above the regional norm is a pricing signal the
        # structural rows can't see (illiquidity, hidden vacancy/tenant risk). It
        # does not fail the deal — it feeds a small, bounded, config-driven
        # reduction into this same confidence axis rather than the graded rows.
        # Graduated (not a binary cliff): scales linearly with how far the cap
        # rate exceeds the risk threshold, then flattens at a bounded max so no
        # single cap rate — however high — can annihilate the score.
        threshold = cfg["cap_rate_risk_threshold_pct"]
        self.cap_rate_flagged = cap_rate is not None and cap_rate > threshold
        cap_rate_haircut = 0.0
        if cap_rate is not None and cap_rate > threshold:
            cap_rate_haircut = min(
                cfg["cap_rate_risk_max_haircut"],
                cfg["cap_rate_risk_slope"] * (cap_rate - threshold),
            )
        self.cap_rate_haircut = cap_rate_haircut
        multiplier *= (1.0 - cap_rate_haircut)
        self.confidence_multiplier = max(floor, min(1.0, multiplier))

    def imputed_range(self) -> Optional[tuple]:
        """(low, high) dollar range for imputed income using its measured spread,
        or None when there is no imputed income."""
        if self.imputed_income <= 0:
            return None
        half_width = sum(a * cov for a, cov in self.imputed_lines)
        return (self.imputed_income - half_width, self.imputed_income + half_width)

    def rows(self) -> list:
        estimated_pct = 100.0 - self.verified_income_pct
        rows = [
            ReportRow(
                "Income Verification",
                f"Verified: {self.verified_income_pct:.0f}%  ·  Estimated: {estimated_pct:.0f}%",
                "INFO",
            ),
        ]
        rng = self.imputed_range()
        if rng is not None:
            lo, hi = rng
            rows.append(ReportRow(
                "  Estimated Income Range",
                f"${lo:,.0f}-${hi:,.0f}/yr",
                "INFO",
            ))
        rows.append(ReportRow(
            "Confidence Multiplier",
            f"{self.confidence_multiplier:.2f}x",
            "INFO" if self.confidence_multiplier >= 0.99 else "CAUTION: Score Adjusted",
        ))
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
