"""
Deal-financing analysis — the ADDITIVE per-type financing rows on the card.

This sits *alongside* MortgageCalculator (which is deliberately type-agnostic and
still produces Down Payment / Monthly Payment / Annual Debt Service off the
resolved scalars). It adds the lender-appetite view a screener needs:

  • the two loan ceilings (LTV-constrained and DSCR-constrained) and which one
    binds,
  • per-door economics for multi-family, and
  • the CMHC / MLI Select panel for 5+ unit multifamily.

All inputs are resolved figures — the resolved financing block from
financing_config, the price, and the NOI/GPR from this same analysis run. It
reuses the Canadian semi-annual payment math from analysis.mortgage; the loan
inversion (principal that a given payment supports) lives here, not in the
MortgageCalculator class.
"""
from models.report_row import ReportRow
from analysis.mortgage import amortization_payment, effective_monthly_rate

_MF_TYPES = frozenset({"multi_family_1_4", "multi_family_5plus"})


def loan_from_payment(monthly_payment: float, annual_rate: float, amort_years: int,
                      compounding: str = "semi-annual") -> float:
    """Principal a fully-amortizing loan can carry given a target monthly payment
    — the inverse of analysis.mortgage.amortization_payment."""
    r = effective_monthly_rate(annual_rate, compounding)
    n = amort_years * 12
    if n <= 0:
        return 0.0
    if r == 0:
        return monthly_payment * n
    return monthly_payment * ((1 + r) ** n - 1) / (r * (1 + r) ** n)


class DealFinancing:
    """Additive financing rows sourced from the resolved per-type financing block.

    ``financing`` is the dict returned by financing_config.get_financing /
    resolve_financing. ``noi`` is Year-1 NOI, ``gpr`` the gross potential rent,
    ``units`` the residential door count (0/None for non-multifamily).
    """

    def __init__(self, financing: dict, price: float, noi: float,
                 gpr: float = 0.0, units: int = 0, compounding: str = "semi-annual"):
        self._fin        = financing
        self._price      = price or 0
        self._noi        = noi or 0
        self._gpr        = gpr or 0
        self._units      = units or 0
        self._compound   = compounding

        self.type_key    = financing.get("type_key")
        self.max_ltv     = financing.get("max_ltv") or 0
        self.dscr_floor  = financing.get("dscr_floor")
        self.amort_years = financing.get("term_years") or financing.get("amort_years") or 0
        self.contract_rate   = financing.get("interest_rate") or 0
        self.stress_bump     = financing.get("stress_test_bump") or 0
        self.qualifying_rate = self.contract_rate + self.stress_bump

        # LTV-constrained ceiling.
        self.ltv_max_loan = self._price * self.max_ltv

        # DSCR-constrained ceiling: the largest loan whose stressed (qualifying-
        # rate) debt service keeps DSCR at the floor. Skipped for 1-4 unit
        # residential, which qualifies on borrower GDS/TDS, not a DSCR floor.
        if self.dscr_floor:
            max_ads = self._noi / self.dscr_floor
            self.dscr_max_loan = loan_from_payment(
                max_ads / 12, self.qualifying_rate, self.amort_years, self._compound
            )
            self.max_supportable_loan = min(self.ltv_max_loan, self.dscr_max_loan)
            self.binding_constraint = (
                "LTV" if self.ltv_max_loan <= self.dscr_max_loan else "DSCR"
            )
        else:
            self.dscr_max_loan = None
            self.max_supportable_loan = self.ltv_max_loan
            self.binding_constraint = "n/a (GDS/TDS)"

        # Refi headroom: when LTV binds, this is the additional debt income could
        # support at the current NOI before hitting the DSCR floor. Only meaningful
        # for a DSCR-floor type whose LTV ceiling binds first; omitted (None)
        # otherwise (DSCR-binding, or 1-4 unit residential with no floor).
        if self.dscr_max_loan is not None and self.binding_constraint == "LTV":
            self.refi_headroom = self.dscr_max_loan - self.max_supportable_loan
        else:
            self.refi_headroom = None

        self.is_multifamily = self.type_key in _MF_TYPES
        self.price_per_door = (self._price / self._units) if self._units else None
        self.avg_rent_per_door = (self._gpr / 12 / self._units) if self._units else None

    # ── rendering ──────────────────────────────────────────────────────────

    def _loan_analysis_rows(self) -> list:
        rows = [
            ReportRow("Max LTV", f"{self.max_ltv * 100:.0f}%", "INFO"),
            ReportRow("LTV Max Loan", f"${self.ltv_max_loan:,.2f}", "INFO"),
        ]
        if self.dscr_max_loan is not None:
            rows.append(ReportRow(
                "DSCR Max Loan",
                f"${self.dscr_max_loan:,.2f} @ {self.qualifying_rate * 100:.2f}%",
                "INFO",
            ))
        rows += [
            ReportRow("Max Supportable Loan", f"${self.max_supportable_loan:,.2f}", "INFO"),
            ReportRow("Binding Constraint", self.binding_constraint, "INFO"),
        ]
        if self.refi_headroom is not None:
            rows.append(ReportRow(
                "Refi Headroom",
                f"${self.refi_headroom:,.2f} — income supports this much additional debt at current NOI",
                "INFO",
            ))
        return rows

    def _unit_rows(self) -> list:
        if not self.is_multifamily:
            return []
        rows = [ReportRow("Units", f"{self._units}", "INFO")]
        if self.price_per_door is not None:
            rows.append(ReportRow("Price / Door", f"${self.price_per_door:,.2f}", "INFO"))
        if self.avg_rent_per_door is not None:
            rows.append(ReportRow("Avg Rent / Door", f"${self.avg_rent_per_door:,.2f}/mo", "INFO"))
        return rows

    def _mli_rows(self) -> list:
        """CMHC / MLI panel — Fix C: renders IFF the deal is actually MLI-routed
        (``financing_scenario == "mli_standard"``). Conventional deals get NO MLI
        rows: small-balance 5+ MF, 1-4 unit residential, and non-eligible
        mixed-use. (MLI-routed mixed-use under the 30% rule DOES render it.)"""
        if self._fin.get("financing_scenario") != "mli_standard":
            return []
        cmhc = self._fin.get("cmhc")
        if not isinstance(cmhc, dict):
            return []
        select   = cmhc.get("mli_select", {})
        standard = cmhc.get("mli_standard", {})
        std_ltv  = standard.get("max_ltv", 0.85)
        # Acquisition LTV is capped at 85% for BOTH programs; 95% is the unverified
        # top-tier ceiling. Select amortization is modeled at the 70-pt/45yr tier.
        sel_ltv       = select.get("max_ltv", 0.85)
        sel_amort     = select.get("modeled_amort_years", 45)
        tier_max      = max((select.get("amort_by_points") or {"100": 50}).values())
        unverified    = cmhc.get("unverified_max_ltv", 0.95)
        rows = [
            ReportRow("MLI Eligible", "Yes (5+ units)", "INFO"),
            ReportRow("MLI Max Loan (Standard)",
                      f"${self._price * std_ltv:,.2f} @ {std_ltv * 100:.0f}% LTV, "
                      f"{standard.get('amort_years', 40)}yr — ranking basis", "INFO"),
            ReportRow("MLI Max Loan (Select)",
                      f"${self._price * sel_ltv:,.2f} @ {sel_ltv * 100:.0f}% LTV "
                      f"(acquisition cap)", "INFO"),
            ReportRow("MLI Amortization",
                      f"modeled {sel_amort}yr (70-pt tier); up to {tier_max}yr @ 100 pts", "INFO"),
            ReportRow("MLI Note",
                      f"{unverified * 100:.0f}% LTV is unverified upside — requires 100 pts + "
                      f"DSCR≥1.20 + full lender advance. CMHC processing: months.", "INFO"),
        ]
        if self._fin.get("small_balance_flag"):
            # Card-facing copy comes from the config `display` key ONLY. `notes` is
            # internal documentation (variable names, routing instructions) and is
            # never rendered — if `display` is absent, render nothing rather than
            # leak internal prose.
            display = cmhc.get("display")
            if display:
                rows.append(ReportRow("MLI Small-Balance Flag", display, "CAUTION"))
        return rows

    def rows(self) -> list:
        return self._loan_analysis_rows() + self._unit_rows() + self._mli_rows()
