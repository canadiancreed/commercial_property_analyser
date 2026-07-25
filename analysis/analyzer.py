from datetime import date
from models.property_input import PropertyInput
from models.constants import VACANCY_RATE_DEFAULTS, EXPENSE_RATIO_DEFAULTS
from analysis.mortgage import MortgageCalculator, DaysOnMarketCalculator
from analysis.rent_resolver import RentResolver
from analysis.metrics.pricing import PricingMetrics
from analysis.metrics.income import (
    IncomeMetrics, ExitMetrics, IncomeConfidenceMetrics, MixedUseComponents,
)
from analysis.metrics.cash_flow import CashFlowMetrics, DebtMetrics
from analysis.metrics.returns import ReturnMetrics, MarketMetrics
from analysis.metrics.property_types import HotelMetrics, IndustrialMetrics
from analysis.industrial_config import industrial_confidence
from analysis.underwriting_config import load_underwriting_config
from analysis.screener_config import load_screener_config
from analysis.financing_config import resolve_financing
from analysis.deal_financing import DealFinancing
from analysis.metrics.financing_robustness import FinancingRobustness


def build_partial_record(prop: PropertyInput, existing: dict = None) -> dict:
    """Serialize a property to a record with no analysis results.

    Used when analysis can't be completed (e.g. no market rate exists for the
    city yet). The property is still saved so the entry isn't lost and the city
    can be registered for later rate entry; ``results`` is empty and
    ``analyzed_on`` is None so the UI flags it as un-analyzed. Mirrors the field
    set of ``CommercialPropertyAnalyzer.to_record`` so a later re-analysis fills
    the same shape.
    """
    now = date.today().isoformat()
    return {
        "address":          prop.address,
        "mls_number":       prop.mls_number,
        "status":           prop.status,
        "listing_date":     prop.listing_date,
        "created_at":       (existing or {}).get("created_at", now),
        "last_modified":    now,
        "analyzed_on":      None,
        "asking_price":     prop.asking_price,
        "original_price":   prop.original_price,
        "total_sq_ft":      prop.total_sq_ft,
        "city":             prop.city,
        "province":         prop.province,
        "property_type":    prop.property_type,
        "property_taxes":   prop.property_taxes,
        "down_payment_pct": prop.down_payment_pct,
        "interest_rate":    prop.interest_rate,
        "term_years":       prop.term_years,
        "hold_years":       prop.hold_years,
        "expense_ratio":    prop.expense_ratio,
        "lease_type":       prop.lease_type,
        "commercial_lease_expiry": prop.commercial_lease_expiry,
        "construction_cost": prop.construction_cost or 0,
        "annual_rent":      prop.annual_rent,
        "commercial_rent":      prop.commercial_rent or 0.0,
        "residential_rent":     prop.residential_rent or 0.0,
        "commercial_rent_user_entered":  prop.commercial_rent_user_entered,
        "residential_rent_user_entered": prop.residential_rent_user_entered,
        "rent_breakdown":   [],
        "unit_mix":         {
            "bachelor":  prop.unit_mix.bachelor  if prop.unit_mix else 0,
            "one_br":    prop.unit_mix.one_br     if prop.unit_mix else 0,
            "two_br":    prop.unit_mix.two_br     if prop.unit_mix else 0,
            "three_br":  prop.unit_mix.three_br   if prop.unit_mix else 0,
            "four_br":   prop.unit_mix.four_br    if prop.unit_mix else 0,
            "unknown":   prop.unit_mix.unknown    if prop.unit_mix else 0,
            "floors":    prop.unit_mix.floors     if prop.unit_mix else (existing or {}).get("floors", 1),
        },
        "floors":           prop.unit_mix.floors if prop.unit_mix else (existing or {}).get("floors", 1),
        "hotel_rooms":      prop.hotel_rooms or 0,
        "hotel_adr":        prop.hotel_adr,
        "hotel_occupancy":  prop.hotel_occupancy,
        "ind_warehouse_sqft":  prop.ind_warehouse_sqft or 0,
        "ind_office_sqft":     prop.ind_office_sqft    or 0,
        "ind_yard_sqft":       prop.ind_yard_sqft      or 0,
        "ind_dock_doors":      prop.ind_dock_doors     or 0,
        "ind_drive_in_doors":  prop.ind_drive_in_doors or 0,
        "ind_clear_height_ft": prop.ind_clear_height_ft or 0,
        "ind_office_rate":     prop.ind_office_rate,
        "ind_yard_rate":       prop.ind_yard_rate,
        "vacancy_rate":        prop.vacancy_rate,
        "noi_growth_rate":     prop.noi_growth_rate,
        "income_confidence":   None,
        "income_size_band":    None,
        "confidence_multiplier": None,
        "verified_income_pct": None,
        "results":          [],
    }


def _resolve_noi_growth(prop: PropertyInput) -> tuple[float, str]:
    """Return (growth_rate, source_label): explicit per-property override, else the
    single house-standard growth assumption from config/underwriting.json.

    Professional underwriters do not forecast a per-city growth rate — they apply
    one flat assumption to every property and let local differences show up in
    Year-1 NOI (built from actual rents) and cap rates instead. Per-city population
    growth (json/city_demographics.json) is not a rent-growth proxy and is not
    consulted here (other consumers of that file, e.g. city_ranker, are unaffected).
    """
    if prop.noi_growth_rate is not None:
        return prop.noi_growth_rate, "manual override"
    return load_underwriting_config()["noi_growth_default"], "house default"


def _resolve_vacancy_rate(prop: PropertyInput) -> float:
    """Return vacancy rate: explicit override if set, else type-specific constant."""
    if prop.vacancy_rate is not None:
        return prop.vacancy_rate
    ptype = (prop.property_type or "").strip().lower()
    return VACANCY_RATE_DEFAULTS.get(ptype, 0.05)


class CommercialPropertyAnalyzer:

    def __init__(self, prop: PropertyInput, rent_resolver: RentResolver):
        self.prop      = prop
        self._has_rent = False
        annual_rent, breakdown = rent_resolver.resolve(prop)
        self._comm_rent = getattr(rent_resolver, "_comm_rent", None)
        self._res_rent  = getattr(rent_resolver, "_res_rent",  None)

        # ── Industrial: resolve detail-driven income BEFORE the income metrics ──
        # When building details are present, IndustrialMetrics (built from the
        # size-adjusted market rate) is the source of the rent figure that flows
        # into NOI/score — not a flat $/sq ft estimate. When absent, the flat
        # estimate stands but is flagged as a low-confidence approximation.
        self.industrial         = None
        self._income_confidence = None
        self._income_size_band  = getattr(rent_resolver, "_industrial_size_band", None)
        is_industrial = (prop.property_type or "").strip().lower() == "industrial"
        if is_industrial and annual_rent and annual_rent > 0:
            base_rate = getattr(rent_resolver, "_city_rent_per_sqft", None)
            # Detail-driven income and confidence apply only when the rent was
            # market-resolved. A user-entered commercial_rent or an explicitly
            # provided annual_rent always wins and is left untouched.
            market_resolved = (
                prop.annual_rent is None
                and not prop.commercial_rent_user_entered
                and base_rate is not None
            )
            if base_rate is None:
                base_rate = (annual_rent / prop.total_sq_ft) if prop.total_sq_ft else 0
            industrial = IndustrialMetrics(prop, base_rate)
            self.industrial = industrial
            if market_resolved:
                self._income_confidence = industrial_confidence(
                    getattr(rent_resolver, "_industrial_rate_source", None),
                    industrial.is_detailed,
                    getattr(rent_resolver, "_industrial_size_downgrade", False),
                )
                if industrial.is_detailed and industrial.total_income > 0:
                    annual_rent     = industrial.total_income
                    self._comm_rent = industrial.total_income
                    breakdown       = breakdown + industrial.income_breakdown
                else:
                    breakdown = breakdown + [
                        f"⚠ Undetailed approximation — flat market rate, no building "
                        f"details entered (confidence: {self._income_confidence})."
                    ]

        # Resolve the per-type financing block (down payment / rate / amort were
        # already set on `prop` from this same block in _record_to_prop; here we
        # keep the rich block — max_ltv, dscr_floor, fixed_expense_fraction, CMHC
        # — for the additive DealFinancing rows and the break-even-occupancy split).
        self._units     = prop.unit_mix.total_units if prop.unit_mix else 0
        self._financing = resolve_financing(prop.asking_price, prop.property_type, self._units)

        self.mortgage = MortgageCalculator(
            prop.asking_price, prop.down_payment_pct,
            prop.interest_rate, prop.term_years, prop.hold_years,
            prop.construction_cost or 0,
            province=prop.province or "",
        )
        self.dom     = DaysOnMarketCalculator(prop.listing_date)
        self.pricing = PricingMetrics(prop, self.mortgage.loan_amount,
                                      annual_rent,
                                      city_rent_per_sqft=getattr(rent_resolver, "_city_rent_per_sqft", None),
                                      comm_sq_ft=getattr(rent_resolver, "_comm_sq_ft", None))

        if annual_rent and annual_rent > 0:
            self._has_rent = True
            noi_growth_rate, noi_growth_source = _resolve_noi_growth(prop)
            # NOTE: the single NOI Growth Assumption blends two regimes on
            # mixed_use — Ontario residential rent increases are guideline-capped
            # (~2.5%/yr for covered units) while commercial escalations are
            # contractual. Acceptable for a screener; flagged here for a future
            # per-component growth pass.
            self._noi_growth_rate = noi_growth_rate
            # Mixed-use uses a per-component income/expense engine (see
            # MixedUseComponents); every other type keeps the single-ratio path.
            is_mixed_use = (prop.property_type or "").strip().lower() in ("mixed-use", "mixed_use")
            self.mixed_use = None
            if is_mixed_use:
                _sc = load_screener_config()
                self.mixed_use = MixedUseComponents(
                    self._comm_rent or 0.0, self._res_rent or 0.0, prop.lease_type,
                    comm_vacancy=_sc["component_vacancy"]["commercial"],
                    res_vacancy=_sc["component_vacancy"]["residential"],
                    comm_gross_ratio=_sc["mixed_use_commercial_gross_expense_ratio"],
                    comm_nnn_ratio=EXPENSE_RATIO_DEFAULTS["nnn"],
                    res_ratio=EXPENSE_RATIO_DEFAULTS["residential"],
                    majority_threshold=_sc["commercial_majority_threshold"],
                    commercial_lease_expiry=prop.commercial_lease_expiry,
                )
                self.income  = IncomeMetrics(prop, annual_rent, breakdown, rollup=self.mixed_use)
                vacancy_rate = self.mixed_use.blended_vacancy
            else:
                vacancy_rate = _resolve_vacancy_rate(prop)
                self.income  = IncomeMetrics(prop, annual_rent, breakdown, vacancy_rate=vacancy_rate)
            imputed_lines = getattr(rent_resolver, "_imputed_lines", [])
            imputed_total = sum(a for a, _ in imputed_lines)
            # Verified/estimated split counts advertised/in-place ([A]) dollars as
            # verified; any market-rate placeholder ([M]) — a $/sqft or city-average
            # unit rent — is estimated (Issue 5: fixes market placeholders reading
            # as 100% verified). Falls back to the imputed-only measure if the
            # resolver didn't record provenance.
            advertised = getattr(rent_resolver, "_advertised_income", None)
            verified_income = (min(advertised, annual_rent)
                               if isinstance(advertised, (int, float))
                               else annual_rent - imputed_total)
            self.income_confidence = IncomeConfidenceMetrics(
                annual_rent, verified_income, imputed_lines,
                cap_rate=self.income.cap_rate,
            )
            self.exit     = ExitMetrics(prop, self.income.entry_cap, self.income.est_noi,
                                        self.mortgage.loan_balance,
                                        noi_growth_rate=noi_growth_rate)
            self.cashflow = CashFlowMetrics(
                self.income.est_noi, self.mortgage.annual_mortgage, self.mortgage.down_payment,
                prop.construction_cost or 0
            )
            _underwriting = load_underwriting_config()
            _screener     = load_screener_config()
            self.debt     = DebtMetrics(
                self.income.est_noi, prop.expense_ratio,
                self.mortgage.annual_mortgage, annual_rent,
                loan_amount=self.mortgage.loan_amount,
                interest_rate=prop.interest_rate,
                term_years=prop.term_years,
                compounding=self.mortgage.compounding,
                stress_rate_bump=_underwriting["stress_rate_bump"],
                stress_min_dscr=_underwriting["stress_min_dscr"],
                egi=self.income.egi,
                total_operating_expenses=self.income.est_expenses,
                fixed_expense_fraction=self._financing.get("fixed_expense_fraction"),
                beo_display_cap=_screener["beo_display_cap"],
                beo_warning_threshold=_screener["beo_warning_threshold"],
            )
            # Additive per-type financing analysis (loan ceilings + which binds,
            # per-door economics, CMHC/MLI panel) — sourced from the resolved block.
            self.deal_financing = DealFinancing(
                self._financing, prop.asking_price, self.income.est_noi,
                gpr=annual_rent, units=self._units, compounding=self.mortgage.compounding,
            )
            # Break-even financing diagnostic (Fix 5) + scored robustness (Fix 6):
            # how much rate / amortization stress the deal absorbs before covenant
            # breach and before cash flow zero, on the per-type covenant DSCR.
            self.financing_robustness = FinancingRobustness(
                self.income.est_noi, self.mortgage.loan_amount,
                prop.interest_rate, prop.term_years,
                self._financing.get("covenant_dscr"),
                compounding=self.mortgage.compounding,
                rate_low=self._financing.get("rate_low"),
                rate_high=self._financing.get("rate_high"),
                rate_ref_bps=_underwriting.get("robustness_rate_ref_bps", 250.0),
                amort_ref_years=_underwriting.get("robustness_amort_ref_years", 10.0),
                rate_weight=_underwriting.get("robustness_rate_weight", 0.7),
            )
            self.returns  = ReturnMetrics(prop, self.income.est_noi, self.mortgage.annual_mortgage,
                                          self.cashflow.cash_invested, self.exit.exit_price,
                                          self.mortgage.loan_balance,
                                          noi_growth_source=noi_growth_source,
                                          noi_growth_rate=noi_growth_rate)
            self.market   = MarketMetrics(
                self.income.est_noi, self.cashflow.cash_invested,
                self.income.est_expenses, self.mortgage.annual_mortgage, self.dom.count,
                vacancy_rate=vacancy_rate
            )
            is_hotel = (prop.property_type or "").strip().lower() == "hotel"
            self.hotel = HotelMetrics(prop, annual_rent) if is_hotel else None
        else:
            self.income = self.exit = self.cashflow = self.debt = self.returns = self.market = None
            self.income_confidence = None
            self.hotel      = None
            self.industrial = None
            self.deal_financing = None
            self.financing_robustness = None
            self.mixed_use  = None
            self._income_confidence = None

    def report(self) -> list:
        rows = []
        for group in (self.mortgage, self.deal_financing, self.financing_robustness,
                      self.pricing, self.income,
                      self.mixed_use, self.income_confidence, self.exit, self.cashflow,
                      self.debt, self.returns, self.market, self.hotel, self.industrial):
            if group is not None:
                rows.extend(group.rows())
        return rows

    def to_record(self, existing: dict = None) -> dict:
        """Serializes the full analysis to a dict suitable for saving via DataStore."""
        p   = self.prop
        now = date.today().isoformat()
        return {
            "address":          p.address,
            "mls_number":       p.mls_number,
            "status":           p.status,
            "listing_date":     p.listing_date,
            "created_at":       (existing or {}).get("created_at", now),
            "last_modified":    now,
            "analyzed_on":      now,
            "asking_price":     p.asking_price,
            "original_price":   p.original_price,
            "total_sq_ft":      p.total_sq_ft,
            "city":             p.city,
            "province":         p.province,
            "property_type":    p.property_type,
            "property_taxes":   p.property_taxes,
            "down_payment_pct": p.down_payment_pct,
            "interest_rate":    p.interest_rate,
            "term_years":       p.term_years,
            "hold_years":       p.hold_years,
            "expense_ratio":    p.expense_ratio,
            "lease_type":       p.lease_type,
            "commercial_lease_expiry": p.commercial_lease_expiry,
            "construction_cost": p.construction_cost or 0,
            "annual_rent":      self.income.annual_rent if self.income else p.annual_rent,
            "commercial_rent":      self._comm_rent if self._comm_rent else 0.0,
            "residential_rent":     self._res_rent  if self._res_rent  else 0.0,
            "commercial_rent_user_entered":  p.commercial_rent_user_entered,
            "residential_rent_user_entered": p.residential_rent_user_entered,
            "rent_breakdown":   self.income.rent_breakdown if self.income else [],
            "unit_mix":         {
                "bachelor":  p.unit_mix.bachelor  if p.unit_mix else 0,
                "one_br":    p.unit_mix.one_br     if p.unit_mix else 0,
                "two_br":    p.unit_mix.two_br     if p.unit_mix else 0,
                "three_br":  p.unit_mix.three_br   if p.unit_mix else 0,
                "four_br":   p.unit_mix.four_br    if p.unit_mix else 0,
                "unknown":   p.unit_mix.unknown    if p.unit_mix else 0,
                "floors":    p.unit_mix.floors     if p.unit_mix else (existing or {}).get("floors", 1),
            },
            "floors":           p.unit_mix.floors if p.unit_mix else (existing or {}).get("floors", 1),
            "hotel_rooms":      p.hotel_rooms or 0,
            "hotel_adr":        p.hotel_adr,
            "hotel_occupancy":  p.hotel_occupancy,
            "ind_warehouse_sqft":  p.ind_warehouse_sqft or 0,
            "ind_office_sqft":     p.ind_office_sqft    or 0,
            "ind_yard_sqft":       p.ind_yard_sqft      or 0,
            "ind_dock_doors":      p.ind_dock_doors     or 0,
            "ind_drive_in_doors":  p.ind_drive_in_doors or 0,
            "ind_clear_height_ft": p.ind_clear_height_ft or 0,
            "ind_office_rate":     p.ind_office_rate,
            "ind_yard_rate":       p.ind_yard_rate,
            "vacancy_rate":        p.vacancy_rate,
            "noi_growth_rate":     p.noi_growth_rate,
            "income_confidence":   self._income_confidence,
            "income_size_band":    self._income_size_band,
            "confidence_multiplier": (
                self.income_confidence.confidence_multiplier if self.income_confidence else None
            ),
            "verified_income_pct": (
                self.income_confidence.verified_income_pct if self.income_confidence else None
            ),
            # Fix 6: the 0-100 financing-robustness sub-score, stored top-level so
            # the scorer reads a clean numeric (the displayed row carries a rich
            # human-readable string that would not parse as a metric value).
            "financing_robustness": (
                self.financing_robustness.score if self.financing_robustness else None
            ),
            "results":          [row.to_dict() for row in self.report() if row.grade != ""],
        }
