"""
Integration tests for the industrial income refactor, end-to-end through the
real DataStore / RentResolver / Analyzer / Scorer / CityRanker stack using the
shipped json/ data files.

Covers:
  * details drive income (circularity fix) — total_income feeds NOI, not a flat rate
  * size multiplier applied to the city average
  * income_confidence grading (HIGH/MED/LOW) from Src/Est rate × details
  * LOW-confidence industrial excluded from city averages but kept in inventory
"""
import pytest
from models.property_input import PropertyInput
from data.store import DataStore, CommercialRentLoader, ResidentialRentLoader
from analysis.rent_resolver import RentResolver
from analysis.analyzer import CommercialPropertyAnalyzer
from analysis.industrial_config import resolve_size_band
from scoring.scorer import PropertyScorer
from scoring.city_ranker import CityRanker


def _resolver():
    store = DataStore()
    return RentResolver(CommercialRentLoader(store), ResidentialRentLoader(store), store), store


def _ind_prop(city="Ottawa", sqft=50_000, address="1 Test Rd", **detail):
    return PropertyInput(
        original_price=3_000_000, asking_price=3_000_000,
        total_sq_ft=sqft, property_taxes=40_000,
        down_payment_pct=0.30, interest_rate=0.06,
        term_years=25, hold_years=10,
        city=city, province="ON", property_type="Industrial",
        address=address, listing_date="2026-01-01",
        **detail,
    )


# ── Ottawa = sourced (Src) industrial rate ────────────────────────────────────

class TestDetailDrivenIncome:
    def test_undetailed_uses_size_adjusted_flat(self):
        resolver, _ = _resolver()
        prop = _ind_prop(sqft=50_000)               # mid-size band
        a = CommercialPropertyAnalyzer(prop, resolver)
        rate = 21.0                                  # Ottawa Industrial (Src)
        _, mult, _ = resolve_size_band(50_000)
        assert a.income.annual_rent == pytest.approx(rate * mult * 50_000)
        assert a._income_confidence == "MED"         # Src + no details
        assert a.industrial.is_detailed is False

    def test_details_drive_income(self):
        """A detailed building's total_income — not the flat rate — feeds NOI."""
        resolver, _ = _resolver()
        flat = CommercialPropertyAnalyzer(_ind_prop(sqft=50_000), resolver)

        detailed = CommercialPropertyAnalyzer(_ind_prop(
            sqft=50_000, address="2 Test Rd",
            ind_clear_height_ft=32.0,                # premium clearance
            ind_office_sqft=8_000,                   # office at 1.4x (16% — under override)
            ind_dock_doors=3, ind_drive_in_doors=0,  # door income, under density threshold
            ind_yard_sqft=10_000,
        ), resolver)

        assert detailed.industrial.is_detailed is True
        # The income the analyser scores IS the detail-driven total_income.
        assert detailed.income.annual_rent == pytest.approx(detailed.industrial.total_income)
        # And it differs from the flat estimate (the original bug: it didn't).
        assert detailed.income.annual_rent != pytest.approx(flat.income.annual_rent)
        assert detailed._income_confidence == "HIGH"  # Src + details

    def test_user_entered_rent_not_overridden(self):
        """A user-entered commercial_rent must survive even with details present."""
        resolver, _ = _resolver()
        prop = _ind_prop(
            city="Ottawa", sqft=50_000, address="3 Test Rd",
            commercial_rent=900_000, commercial_rent_user_entered=True,
            ind_clear_height_ft=32.0, ind_dock_doors=4,
        )
        a = CommercialPropertyAnalyzer(prop, resolver)
        assert a.income.annual_rent == pytest.approx(900_000)
        # User-supplied figure is not graded as a market estimate.
        assert a._income_confidence is None

    def test_explicit_annual_rent_not_overridden(self):
        resolver, _ = _resolver()
        prop = _ind_prop(
            city="Ottawa", sqft=50_000, address="4 Test Rd",
            annual_rent=800_000, ind_clear_height_ft=30.0, ind_office_sqft=5_000,
        )
        a = CommercialPropertyAnalyzer(prop, resolver)
        assert a.income.annual_rent == pytest.approx(800_000)
        assert a._income_confidence is None

    def test_to_record_emits_confidence_and_band(self):
        resolver, _ = _resolver()
        a = CommercialPropertyAnalyzer(_ind_prop(sqft=150_000), resolver)
        rec = a.to_record()
        assert rec["income_confidence"] == "MED"
        assert rec["income_size_band"] == "big-box"


# ── Perth = estimated (Est) industrial rate ───────────────────────────────────

class TestEstimateConfidence:
    def test_est_no_details_is_low(self):
        resolver, _ = _resolver()
        a = CommercialPropertyAnalyzer(_ind_prop(city="Perth", sqft=120_000), resolver)
        assert a._income_confidence == "LOW"
        assert a.to_record()["income_confidence"] == "LOW"

    def test_est_with_details_is_med(self):
        resolver, _ = _resolver()
        a = CommercialPropertyAnalyzer(_ind_prop(
            city="Perth", sqft=120_000, ind_clear_height_ft=28.0, ind_dock_doors=4,
        ), resolver)
        assert a._income_confidence == "MED"


# ── City ranking: LOW excluded from averages, kept in inventory ───────────────

class TestCityRankerExclusion:
    def test_low_excluded_from_city_average(self):
        resolver, store = _resolver()
        scorer = PropertyScorer(store)

        low = CommercialPropertyAnalyzer(
            _ind_prop(city="Perth", sqft=120_000, address="LOW Rd"), resolver).to_record()
        med = CommercialPropertyAnalyzer(_ind_prop(
            city="Perth", sqft=120_000, address="MED Rd",
            ind_clear_height_ft=28.0, ind_dock_doors=4), resolver).to_record()

        assert low["income_confidence"] == "LOW"
        assert med["income_confidence"] == "MED"

        cities = {c["city"]: c for c in CityRanker(scorer).rank([low, med])}
        perth  = next(c for v, c in cities.items() if v.startswith("Perth"))

        # Both kept in inventory, but the city cap-rate average reflects only
        # the MED property (LOW excluded).
        assert perth["total"] == 2
        med_cap = scorer.score_property(med)["cap_rate"]
        assert perth["act_cap"] == pytest.approx(med_cap, rel=1e-3)
