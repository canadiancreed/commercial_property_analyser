import json
import os
from datetime import date
from models.property_input import PropertyInput
from analysis.mortgage import MortgageCalculator, DaysOnMarketCalculator
from analysis.rent_resolver import RentResolver
from analysis.metrics.pricing import PricingMetrics
from analysis.metrics.income import IncomeMetrics, ExitMetrics
from analysis.metrics.cash_flow import CashFlowMetrics, DebtMetrics
from analysis.metrics.returns import ReturnMetrics, MarketMetrics
from analysis.metrics.property_types import HotelMetrics, IndustrialMetrics

_DEMOGRAPHICS_PATH = "json/city_demographics.json"
_DEFAULT_NOI_GROWTH = 0.02


def _resolve_noi_growth(prop: PropertyInput) -> tuple[float, str]:
    """Return (growth_rate, source_label) in priority: explicit override > locale > default."""
    if prop.noi_growth_rate is not None:
        return prop.noi_growth_rate, "manual override"
    city = (prop.city or "").strip().lower()
    if city and os.path.exists(_DEMOGRAPHICS_PATH):
        try:
            with open(_DEMOGRAPHICS_PATH, encoding="utf-8") as f:
                demo = json.load(f)
            meta  = demo.get("_meta", {})
            entry = demo.get(city, {})
            pct   = entry.get("growth_pct_annual")
            if pct is not None:
                last_updated  = meta.get("last_updated", "unknown")
                refresh_years = int(meta.get("refresh_years", 5))
                try:
                    updated_year = int(last_updated[:4])
                    stale = (date.today().year - updated_year) >= refresh_years
                except (ValueError, TypeError):
                    stale = False
                label = f"{prop.city} demographics ({last_updated})"
                if stale:
                    label += " — DATA MAY BE STALE"
                return float(pct) / 100, label
        except Exception:
            pass
    return _DEFAULT_NOI_GROWTH, "default (no locale data)"


class CommercialPropertyAnalyzer:

    def __init__(self, prop: PropertyInput, rent_resolver: RentResolver):
        self.prop      = prop
        self._has_rent = False
        annual_rent, breakdown = rent_resolver.resolve(prop)
        self._comm_rent = getattr(rent_resolver, "_comm_rent", None)
        self._res_rent  = getattr(rent_resolver, "_res_rent",  None)

        self.mortgage = MortgageCalculator(
            prop.asking_price, prop.down_payment_pct,
            prop.interest_rate, prop.term_years, prop.hold_years,
            prop.construction_cost or 0
        )
        self.dom     = DaysOnMarketCalculator(prop.listing_date)
        self.pricing = PricingMetrics(prop, self.mortgage.loan_balance,
                                      annual_rent if annual_rent else 1,
                                      city_rent_per_sqft=getattr(rent_resolver, "_city_rent_per_sqft", None),
                                      comm_sq_ft=getattr(rent_resolver, "_comm_sq_ft", None))

        if annual_rent and annual_rent > 0:
            self._has_rent = True
            noi_growth_rate, noi_growth_source = _resolve_noi_growth(prop)
            self._noi_growth_rate = noi_growth_rate
            self.income   = IncomeMetrics(prop, annual_rent, breakdown)
            self.exit     = ExitMetrics(prop, self.income.entry_cap, self.income.est_noi,
                                        self.mortgage.loan_balance,
                                        noi_growth_rate=noi_growth_rate)
            self.cashflow = CashFlowMetrics(
                self.income.est_noi, self.mortgage.annual_mortgage, self.mortgage.down_payment,
                prop.construction_cost or 0
            )
            self.debt     = DebtMetrics(
                self.income.est_noi, prop.expense_ratio,
                self.mortgage.annual_mortgage, annual_rent
            )
            self.returns  = ReturnMetrics(prop, self.income.est_noi, self.mortgage.annual_mortgage,
                                          self.cashflow.cash_invested, self.exit.exit_price,
                                          self.mortgage.loan_balance,
                                          noi_growth_source=noi_growth_source,
                                          noi_growth_rate=noi_growth_rate)
            self.market   = MarketMetrics(
                self.income.est_noi, self.cashflow.cash_invested,
                self.income.est_expenses, self.mortgage.annual_mortgage, self.dom.count,
                vacancy_rate=prop.vacancy_rate
            )
            is_hotel = (prop.property_type or "").strip().lower() == "hotel"
            self.hotel = HotelMetrics(prop, annual_rent) if is_hotel else None

            is_industrial = (prop.property_type or "").strip().lower() == "industrial"
            if is_industrial:
                base_rate = (annual_rent / prop.total_sq_ft) if prop.total_sq_ft else 0
                self.industrial = IndustrialMetrics(prop, base_rate)
            else:
                self.industrial = None
        else:
            self.income = self.exit = self.cashflow = self.debt = self.returns = self.market = None
            self.hotel      = None
            self.industrial = None

    def report(self) -> list:
        rows = []
        for group in (self.mortgage, self.pricing, self.income, self.exit,
                      self.cashflow, self.debt, self.returns, self.market, self.hotel,
                      self.industrial):
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
            "results":          [row.to_dict() for row in self.report() if row.grade != ""],
        }
