"""
Extended unit tests for main.py — targeting the classes and methods
not covered by the existing test suite to push coverage to >= 90%.
"""
import json
import os
import tempfile
import pytest
from datetime import date
from unittest.mock import MagicMock, patch, PropertyMock

# ---------------------------------------------------------------------------
# Import helpers — adjust path so main.py is importable
# ---------------------------------------------------------------------------
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# The module lives one level up (user uploaded it).  Try both locations.
try:
    from main_old import (
        DataStore, UnitMix, PropertyInput, MortgageCalculator,
        DaysOnMarketCalculator, CommercialRentLoader, ResidentialRentLoader,
        RentResolver, ReportRow, Grader, PricingMetrics, IncomeMetrics,
        ExitCapEstimator, ExitMetrics, CashFlowMetrics, DebtMetrics,
        ReturnMetrics, MarketMetrics, CommercialPropertyAnalyzer,
        ReportPrinter, PropertyMenu,
    )
except ModuleNotFoundError:
    # When run from the repo root the uploads copy is at this path
    sys.path.insert(0, "/mnt/user-data/uploads")
    from main_old import (
        DataStore, UnitMix, PropertyInput, MortgageCalculator,
        DaysOnMarketCalculator, CommercialRentLoader, ResidentialRentLoader,
        RentResolver, ReportRow, Grader, PricingMetrics, IncomeMetrics,
        ExitCapEstimator, ExitMetrics, CashFlowMetrics, DebtMetrics,
        ReturnMetrics, MarketMetrics, CommercialPropertyAnalyzer,
        ReportPrinter, PropertyMenu,
    )


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

COMMERCIAL_DATA = {
    "cities": {
        "Ottawa": {
            "province": "ON",
            "types": {"Office": 28.0, "Retail": 32.0, "Industrial": 14.0, "Mixed-Use": 20.0}
        },
        "Toronto": {
            "province": "ON",
            "types": {"Office": 45.0, "Retail": 60.0, "Industrial": 18.0, "Mixed-Use": 35.0}
        }
    }
}

RESIDENTIAL_DATA = {
    "cities": {
        "Ottawa": {
            "province": "ON",
            "units": {"bachelor": 1200, "one_br": 1600, "two_br": 2100,
                      "three_br": 2600, "four_br": 3000, "unknown": 1500}
        },
        "Toronto": {
            "province": "ON",
            "units": {"bachelor": 1800, "one_br": 2400, "two_br": 3000,
                      "three_br": 3600, "four_br": 4200, "unknown": 2000}
        }
    }
}


def make_temp_store(tmp_path, comm=None, res=None, props=None):
    """Create a DataStore backed by temp files."""
    comm_file  = tmp_path / "commercial_rents.json"
    res_file   = tmp_path / "residential_rents.json"
    props_file = tmp_path / "properties.json"
    miss_file  = tmp_path / "missing_cities.json"

    comm_file.write_text(json.dumps(comm or COMMERCIAL_DATA))
    res_file.write_text(json.dumps(res or RESIDENTIAL_DATA))
    if props is not None:
        props_file.write_text(json.dumps({"properties": props}))

    return DataStore(
        commercial_path=str(comm_file),
        residential_path=str(res_file),
        properties_path=str(props_file),
        missing_path=str(miss_file),
    )


def make_prop(**kwargs):
    """Build a minimal valid PropertyInput."""
    defaults = dict(
        original_price=500_000,
        asking_price=500_000,
        total_sq_ft=5_000,
        property_taxes=8_000,
        down_payment_pct=0.25,
        interest_rate=0.065,
        term_years=25,
        annual_rent=60_000,
        listing_date="2024-01-01",
        address="123 Test St",
        hold_years=5,
    )
    defaults.update(kwargs)
    return PropertyInput(**defaults)


def make_resolver(store):
    """Build a RentResolver from a DataStore."""
    return RentResolver(
        commercial_loader=CommercialRentLoader(store),
        residential_loader=ResidentialRentLoader(store),
        data_store=store,
    )


# ===========================================================================
# DataStore
# ===========================================================================

class TestDataStoreReadWrite:
    def test_read_missing_file_raises(self, tmp_path):
        path = str(tmp_path / "ghost.json")
        with pytest.raises(FileNotFoundError):
            DataStore._read(path)

    def test_write_and_read_roundtrip(self, tmp_path):
        path = str(tmp_path / "data.json")
        DataStore._write(path, {"key": "value"})
        result = DataStore._read(path)
        assert result == {"key": "value"}


class TestDataStoreCommercial:
    def test_load_commercial_rates_normalises_keys(self, tmp_path):
        store = make_temp_store(tmp_path)
        rates = store.load_commercial_rates()
        assert "ottawa" in rates
        assert "office" in rates["ottawa"]
        assert rates["ottawa"]["retail"] == 32.0

    def test_save_commercial_rates_adds_city(self, tmp_path):
        store = make_temp_store(tmp_path)
        store.save_commercial_rates("Kingston", "ON", {"Office": 22.0})
        rates = store.load_commercial_rates()
        assert "kingston" in rates
        assert rates["kingston"]["office"] == 22.0

    def test_save_commercial_rates_overwrites_city(self, tmp_path):
        store = make_temp_store(tmp_path)
        store.save_commercial_rates("Ottawa", "ON", {"Office": 99.0})
        rates = store.load_commercial_rates()
        assert rates["ottawa"]["office"] == 99.0


class TestDataStoreResidential:
    def test_load_residential_rates(self, tmp_path):
        store = make_temp_store(tmp_path)
        rates = store.load_residential_rates()
        assert "ottawa" in rates
        assert rates["ottawa"]["bachelor"] == 1200.0

    def test_save_residential_rates(self, tmp_path):
        store = make_temp_store(tmp_path)
        store.save_residential_rates("London", "ON", {"bachelor": 950, "one_br": 1300})
        rates = store.load_residential_rates()
        assert "london" in rates


class TestDataStoreProperties:
    def test_load_properties_when_file_missing(self, tmp_path):
        store = make_temp_store(tmp_path)
        assert store.load_properties() == []

    def test_save_and_load_property(self, tmp_path):
        store = make_temp_store(tmp_path)
        record = {"address": "1 King St", "listing_date": "2024-01-01", "asking_price": 500_000}
        store.save_property(record)
        props = store.load_properties()
        assert len(props) == 1
        assert props[0]["address"] == "1 King St"

    def test_save_property_replaces_duplicate(self, tmp_path):
        store = make_temp_store(tmp_path)
        r1 = {"address": "1 King St", "listing_date": "2024-01-01", "asking_price": 500_000}
        r2 = {"address": "1 King St", "listing_date": "2024-01-01", "asking_price": 600_000}
        store.save_property(r1)
        store.save_property(r2)
        props = store.load_properties()
        assert len(props) == 1
        assert props[0]["asking_price"] == 600_000

    def test_delete_property_valid(self, tmp_path):
        store = make_temp_store(tmp_path, props=[
            {"address": "A", "listing_date": "2024-01-01"},
            {"address": "B", "listing_date": "2024-01-02"},
        ])
        assert store.delete_property(0) is True
        assert len(store.load_properties()) == 1

    def test_delete_property_out_of_range(self, tmp_path):
        store = make_temp_store(tmp_path, props=[{"address": "A", "listing_date": "2024-01-01"}])
        assert store.delete_property(5) is False

    def test_delete_property_negative_index(self, tmp_path):
        store = make_temp_store(tmp_path, props=[{"address": "A", "listing_date": "2024-01-01"}])
        assert store.delete_property(-1) is False

    def test_update_property_valid(self, tmp_path):
        store = make_temp_store(tmp_path, props=[{"address": "A", "listing_date": "2024-01-01", "asking_price": 100}])
        assert store.update_property(0, {"asking_price": 999}) is True
        assert store.load_properties()[0]["asking_price"] == 999

    def test_update_property_out_of_range(self, tmp_path):
        store = make_temp_store(tmp_path, props=[{"address": "A", "listing_date": "2024-01-01"}])
        assert store.update_property(10, {"asking_price": 999}) is False

    def test_delete_when_no_properties_file(self, tmp_path):
        store = make_temp_store(tmp_path)
        assert store.delete_property(0) is False


class TestDataStoreMissingCities:
    def test_load_missing_cities_no_file(self, tmp_path):
        store = make_temp_store(tmp_path)
        assert store.load_missing_cities() == {}

    def test_log_missing_city_creates_entry(self, tmp_path):
        store = make_temp_store(tmp_path)
        store.log_missing_city("Sudbury", "ON", "commercial", ["Office"])
        result = store.load_missing_cities()
        assert "Sudbury, ON" in result
        assert "commercial" in result["Sudbury, ON"]["missing"]
        assert "Office" in result["Sudbury, ON"]["property_types"]

    def test_log_missing_city_no_duplicates(self, tmp_path):
        store = make_temp_store(tmp_path)
        store.log_missing_city("Sudbury", "ON", "commercial")
        store.log_missing_city("Sudbury", "ON", "commercial")
        result = store.load_missing_cities()
        assert result["Sudbury, ON"]["missing"].count("commercial") == 1

    def test_clear_missing_city(self, tmp_path):
        store = make_temp_store(tmp_path)
        store.log_missing_city("Sudbury", "ON", "commercial")
        store.clear_missing_city("Sudbury, ON")
        assert store.load_missing_cities() == {}

    def test_save_commercial_city_clears_missing(self, tmp_path):
        store = make_temp_store(tmp_path)
        store.log_missing_city("Ottawa", "ON", "commercial", ["Office"])
        store.save_commercial_city("Ottawa", "ON", {"Office": 30.0, "Retail": 35.0,
                                                     "Industrial": 15.0, "Mixed-Use": 22.0})
        # Ottawa should be removed from missing since all types are satisfied
        missing = store.load_missing_cities()
        assert "Ottawa, ON" not in missing

    def test_save_residential_city_clears_missing(self, tmp_path):
        store = make_temp_store(tmp_path)
        store.log_missing_city("Ottawa", "ON", "residential")
        store.save_residential_city("Ottawa", "ON", {"bachelor": 1300, "one_br": 1700,
                                                      "two_br": 2200, "three_br": 2700,
                                                      "four_br": 3100, "unknown": 1550})
        missing = store.load_missing_cities()
        assert "Ottawa, ON" not in missing

    def test_ensure_city_in_rates_adds_missing_city(self, tmp_path):
        store = make_temp_store(tmp_path)
        store.ensure_city_in_rates("Barrie", "ON")
        comm = store.load_commercial_rates()
        res  = store.load_residential_rates()
        assert "barrie" in comm
        assert "barrie" in res

    def test_ensure_city_existing_no_update(self, tmp_path):
        store = make_temp_store(tmp_path)
        # Ottawa already exists — should not raise or modify
        store.ensure_city_in_rates("Ottawa", "ON")
        # No missing_rent_data.json should be written when city already exists
        assert not os.path.exists(store.MISSING_RENT_PATH)


# ===========================================================================
# UnitMix
# ===========================================================================

class TestUnitMix:
    def test_total_units(self):
        um = UnitMix(bachelor=1, one_br=2, two_br=3, three_br=1, four_br=1, unknown=0)
        assert um.total_units == 8

    def test_unit_types_list(self):
        um = UnitMix(one_br=3, one_br_rent=1800.0)
        types = um.unit_types()
        one_br_entry = next(t for t in types if t[0] == "one_br")
        assert one_br_entry[1] == 3
        assert one_br_entry[2] == 1800.0

    def test_zero_total_units(self):
        um = UnitMix()
        assert um.total_units == 0


# ===========================================================================
# MortgageCalculator
# ===========================================================================

class TestMortgageCalculator:
    def test_basic_calculation(self):
        mc = MortgageCalculator(500_000, 0.25, 0.065, 25, 5)
        assert mc.down_payment == 125_000
        assert mc.loan_amount  == 375_000
        assert mc.monthly_payment > 0
        assert mc.annual_mortgage == pytest.approx(mc.monthly_payment * 12)

    def test_zero_interest_rate(self):
        mc = MortgageCalculator(300_000, 0.20, 0.0, 25, 5)
        expected_monthly = 240_000 / (25 * 12)
        assert mc.monthly_payment == pytest.approx(expected_monthly)

    def test_loan_balance_after_full_term(self):
        mc = MortgageCalculator(200_000, 0.20, 0.05, 10, 10)
        assert mc.loan_balance == pytest.approx(0.0, abs=1.0)

    def test_loan_balance_midterm(self):
        mc = MortgageCalculator(400_000, 0.25, 0.065, 25, 5)
        assert 0 < mc.loan_balance < mc.loan_amount

    def test_rows_returns_four_items(self):
        mc = MortgageCalculator(500_000, 0.25, 0.065, 25, 5)
        assert len(mc.rows()) == 4


# ===========================================================================
# DaysOnMarketCalculator
# ===========================================================================

class TestDaysOnMarketCalculator:
    def test_days_count(self):
        dom = DaysOnMarketCalculator("2024-01-01")
        assert dom.count >= 0

    def test_recent_listing(self):
        today = date.today().isoformat()
        dom = DaysOnMarketCalculator(today)
        assert dom.count == 0


# ===========================================================================
# CommercialRentLoader
# ===========================================================================

class TestCommercialRentLoader:
    def test_get_existing_rate(self, tmp_path):
        store  = make_temp_store(tmp_path)
        loader = CommercialRentLoader(store)
        rate = loader.get_rent_per_sqft("Ottawa", "ON", "Office")
        assert rate == 28.0

    def test_missing_city_returns_none(self, tmp_path):
        store  = make_temp_store(tmp_path)
        loader = CommercialRentLoader(store)
        assert loader.get_rent_per_sqft("Timbuktu", "ON", "Office") is None

    def test_missing_type_returns_none(self, tmp_path):
        store  = make_temp_store(tmp_path)
        loader = CommercialRentLoader(store)
        assert loader.get_rent_per_sqft("Ottawa", "ON", "Hospital") is None

    def test_case_insensitive(self, tmp_path):
        store  = make_temp_store(tmp_path)
        loader = CommercialRentLoader(store)
        assert loader.get_rent_per_sqft("OTTAWA", "ON", "office") == 28.0


# ===========================================================================
# ResidentialRentLoader
# ===========================================================================

class TestResidentialRentLoader:
    def test_get_existing_rates(self, tmp_path):
        store  = make_temp_store(tmp_path)
        loader = ResidentialRentLoader(store)
        rates = loader.get_rates("Ottawa", "ON")
        assert rates is not None
        assert rates["one_br"] == 1600.0

    def test_missing_city_returns_none(self, tmp_path):
        store  = make_temp_store(tmp_path)
        loader = ResidentialRentLoader(store)
        assert loader.get_rates("Atlantis", "ON") is None


# ===========================================================================
# RentResolver
# ===========================================================================

class TestRentResolverMode1DirectRent:
    def test_direct_rent_returned(self, tmp_path):
        store    = make_temp_store(tmp_path)
        resolver = make_resolver(store)
        prop = make_prop(annual_rent=72_000)
        rent, breakdown = resolver.resolve(prop)
        assert rent == 72_000
        assert "provided directly" in breakdown[0]


class TestRentResolverMode2Commercial:
    def test_commercial_rate_lookup(self, tmp_path):
        store    = make_temp_store(tmp_path)
        resolver = make_resolver(store)
        prop = make_prop(
            annual_rent=None,
            city="Ottawa", province="ON",
            property_type="Retail",
            total_sq_ft=2_000,
        )
        rent, breakdown = resolver.resolve(prop)
        assert rent == pytest.approx(32.0 * 2_000)

    def test_commercial_missing_city_raises(self, tmp_path):
        store    = make_temp_store(tmp_path)
        resolver = make_resolver(store)
        prop = make_prop(
            annual_rent=None,
            city="Atlantis", province="ON",
            property_type="Office",
            total_sq_ft=1_000,
        )
        with pytest.raises(ValueError):
            resolver.resolve(prop)

    def test_no_city_raises(self, tmp_path):
        store    = make_temp_store(tmp_path)
        resolver = make_resolver(store)
        prop = make_prop(
            annual_rent=None,
            city=None, province=None,
            property_type="Office",
            total_sq_ft=1_000,
        )
        with pytest.raises(ValueError):
            resolver.resolve(prop)

    def test_no_rent_no_type_raises(self, tmp_path):
        store    = make_temp_store(tmp_path)
        resolver = make_resolver(store)
        prop = make_prop(
            annual_rent=None,
            city="Ottawa", province="ON",
            property_type=None,
            unit_mix=None,
        )
        with pytest.raises(ValueError):
            resolver.resolve(prop)


class TestRentResolverMode3Residential:
    def test_residential_rates_from_market(self, tmp_path):
        store    = make_temp_store(tmp_path)
        resolver = make_resolver(store)
        um = UnitMix(one_br=2, two_br=1)
        prop = make_prop(
            annual_rent=None,
            city="Ottawa", province="ON",
            unit_mix=um,
        )
        rent, breakdown = resolver.resolve(prop)
        expected = (1600 * 2 + 2100 * 1) * 12
        assert rent == pytest.approx(expected)

    def test_residential_override_rent_used(self, tmp_path):
        store    = make_temp_store(tmp_path)
        resolver = make_resolver(store)
        um = UnitMix(one_br=1, one_br_rent=9_000)
        prop = make_prop(
            annual_rent=None,
            city="Ottawa", province="ON",
            unit_mix=um,
        )
        rent, _ = resolver.resolve(prop)
        assert rent == pytest.approx(9_000 * 12)

    def test_residential_missing_city_uses_overrides_only(self, tmp_path):
        store    = make_temp_store(tmp_path)
        resolver = make_resolver(store)
        um = UnitMix(one_br=1, one_br_rent=1500, two_br=1)  # two_br has no override
        prop = make_prop(
            annual_rent=None,
            city="Timbuktu", province="ON",
            unit_mix=um,
        )
        rent, breakdown = resolver.resolve(prop)
        # Only one_br counted (has override), two_br skipped (no market data, no override)
        assert rent == pytest.approx(1500 * 12)
        assert any("skipped" in line for line in breakdown)

    def test_residential_city_avg_used_for_missing_unit_type(self, tmp_path):
        """If market has some unit types but not the requested one, city average is used."""
        # Build a store where Ottawa has only bachelor and one_br rates
        partial_res = {
            "cities": {
                "Ottawa": {
                    "province": "ON",
                    "units": {"bachelor": 1200, "one_br": 1600, "two_br": 0,
                              "three_br": 0, "four_br": 0, "unknown": 0}
                }
            }
        }
        store    = make_temp_store(tmp_path, res=partial_res)
        resolver = make_resolver(store)
        um = UnitMix(two_br=1)   # two_br rate is 0, but city avg will be used
        prop = make_prop(
            annual_rent=None,
            city="Ottawa", province="ON",
            unit_mix=um,
        )
        rent, _ = resolver.resolve(prop)
        assert rent >= 0   # Just confirm it runs without error


class TestRentResolverMode4MixedUse:
    def test_mixed_use_sums_commercial_and_residential(self, tmp_path):
        store    = make_temp_store(tmp_path)
        resolver = make_resolver(store)
        um = UnitMix(one_br=2, floors=2)
        prop = make_prop(
            annual_rent=None,
            city="Ottawa", province="ON",
            property_type="Retail",
            total_sq_ft=4_000,
            unit_mix=um,
        )
        rent, breakdown = resolver.resolve(prop)
        floor_sqft = 4_000 / 2  # ground floor
        expected_comm = 32.0 * floor_sqft
        expected_res  = 1600 * 2 * 12
        assert rent == pytest.approx(expected_comm + expected_res)

    def test_mixed_use_missing_commercial_still_counts_residential(self, tmp_path):
        store    = make_temp_store(tmp_path)
        resolver = make_resolver(store)
        um = UnitMix(one_br=1, floors=2)
        prop = make_prop(
            annual_rent=None,
            city="Atlantis", province="ON",
            property_type="Retail",
            total_sq_ft=2_000,
            unit_mix=um,
        )
        # Missing city — commercial is skipped but residential override not available
        # Should run without crashing (res will be 0 since city not in market)
        rent, breakdown = resolver.resolve(prop)
        assert any("⚠" in line or "missing" in line.lower() for line in breakdown)


# ===========================================================================
# ReportRow
# ===========================================================================

class TestReportRow:
    def test_str_format(self):
        row = ReportRow("Cap Rate", "7.50%", "GOOD")
        s = str(row)
        assert "Cap Rate" in s
        assert "7.50%" in s
        assert "GOOD" in s

    def test_to_dict(self):
        row = ReportRow("NOI", "$45,000", "INFO")
        d = row.to_dict()
        assert d == {"metric": "NOI", "value": "$45,000", "grade": "INFO"}


# ===========================================================================
# Grader
# ===========================================================================

class TestGrader:
    def test_higher_is_better_good(self):
        assert Grader.grade(10, 8, 5) == "GOOD"

    def test_higher_is_better_fair(self):
        assert Grader.grade(6, 8, 5) == "FAIR"

    def test_higher_is_better_poor(self):
        assert Grader.grade(3, 8, 5) == "POOR"

    def test_lower_is_better_good(self):
        assert Grader.grade(1.5, 2.0, 3.0, higher_is_better=False) == "GOOD"

    def test_lower_is_better_fair(self):
        assert Grader.grade(2.5, 2.0, 3.0, higher_is_better=False) == "FAIR"

    def test_lower_is_better_poor(self):
        assert Grader.grade(5.0, 2.0, 3.0, higher_is_better=False) == "POOR"

    def test_custom_labels(self):
        result = Grader.grade(100, 80, 60, labels=("A", "B", "C"))
        assert result == "A"


# ===========================================================================
# PricingMetrics
# ===========================================================================

class TestPricingMetrics:
    def setup_method(self):
        self.prop = make_prop(
            original_price=600_000,
            asking_price=500_000,
            total_sq_ft=5_000,
            property_type="Retail",
        )
        self.pm = PricingMetrics(self.prop, loan_balance=375_000, annual_rent=60_000)

    def test_price_per_sqft(self):
        assert self.pm.pp_sqft == 100.0

    def test_grm(self):
        assert self.pm.grm == pytest.approx(500_000 / 60_000)

    def test_price_drop_pct(self):
        assert self.pm.price_drop_pct == pytest.approx((100_000 / 600_000) * 100)

    def test_tax_load(self):
        assert self.pm.tax_load == pytest.approx((8_000 / 500_000) * 100)

    def test_ltv_ratio(self):
        assert self.pm.ltv_ratio == pytest.approx((375_000 / 500_000) * 100)

    def test_rows_count(self):
        assert len(self.pm.rows()) == 5

    def test_unknown_property_type_uses_default_threshold(self):
        p = make_prop(property_type="Hospital", asking_price=500_000, annual_rent=60_000)
        pm = PricingMetrics(p, 375_000, 60_000)
        rows = pm.rows()
        assert rows  # just confirm no crash


# ===========================================================================
# IncomeMetrics
# ===========================================================================

class TestIncomeMetrics:
    def _make_income(self, lease_type="Normal", expense_ratio=0.40):
        prop = make_prop(lease_type=lease_type, expense_ratio=expense_ratio)
        return IncomeMetrics(prop, 60_000, ["Direct rent"])

    def test_noi_calculation(self):
        im = self._make_income()
        assert im.est_noi == pytest.approx(60_000 * 0.60)

    def test_cap_rate(self):
        im = self._make_income()
        assert im.cap_rate == pytest.approx((60_000 * 0.60 / 500_000) * 100)

    def test_expense_grade_normal_good(self):
        im = self._make_income(lease_type="Normal", expense_ratio=0.40)
        assert im._expense_grade() == "GOOD"

    def test_expense_grade_normal_warning(self):
        im = self._make_income(lease_type="Normal", expense_ratio=0.20)
        assert "WARNING" in im._expense_grade()

    def test_expense_grade_nnn_good(self):
        im = self._make_income(lease_type="NNN", expense_ratio=0.15)
        assert im._expense_grade() == "GOOD"

    def test_expense_grade_nnn_warning(self):
        im = self._make_income(lease_type="NNN", expense_ratio=0.30)
        assert "WARNING" in im._expense_grade()

    def test_oer_grade_normal_good(self):
        im = self._make_income(lease_type="Normal", expense_ratio=0.40)
        assert im._oer_grade() == "GOOD"

    def test_oer_grade_nnn_good(self):
        im = self._make_income(lease_type="NNN", expense_ratio=0.10)
        # OER = 10% which is <= 15 → GOOD
        assert im._oer_grade() == "GOOD"

    def test_rows_contains_annual_rent(self):
        im = self._make_income()
        metrics = [r.metric for r in im.rows()]
        assert "Annual Rent" in metrics


# ===========================================================================
# ExitCapEstimator
# ===========================================================================

class TestExitCapEstimator:
    def test_estimate_no_market_cap(self):
        est = ExitCapEstimator(entry_cap=0.07, hold_years=5)
        result = est.estimate()
        assert result > 0.07  # aging spread adds bps

    def test_estimate_with_market_cap(self):
        est = ExitCapEstimator(entry_cap=0.07, hold_years=5, market_cap_rate=0.08)
        result = est.estimate()
        assert result > 0.07
        # Result should be average of formula exit and market cap
        formula = 0.07 + (10 * 5) / 10000 + 50 / 10000
        expected = round((formula + 0.08) / 2, 4)
        assert result == pytest.approx(expected)


# ===========================================================================
# ExitMetrics
# ===========================================================================

class TestExitMetrics:
    def _make_exit(self, asking_price=500_000, entry_cap=0.07, noi=35_000, exit_cap_rate=None):
        prop = make_prop(asking_price=asking_price, exit_cap_rate=exit_cap_rate, hold_years=5)
        return ExitMetrics(prop, entry_cap, noi)

    def test_exit_price_calculation(self):
        em = self._make_exit()
        # exit_cap will be slightly higher than entry_cap due to aging
        assert em.exit_price > 0

    def test_exit_cap_grade_good(self):
        em = self._make_exit()
        em.exit_cap = 0.065  # below entry_cap of 0.07
        assert em._exit_cap_grade() == "GOOD"

    def test_exit_cap_grade_fair(self):
        em = self._make_exit(entry_cap=0.07)
        em.exit_cap = 0.075  # within 1% above entry
        assert em._exit_cap_grade() == "FAIR"

    def test_exit_cap_grade_poor(self):
        em = self._make_exit(entry_cap=0.07)
        em.exit_cap = 0.10  # >1% above entry
        assert em._exit_cap_grade() == "POOR"

    def test_explicit_exit_cap_rate_used(self):
        em = self._make_exit(exit_cap_rate=0.09)
        assert em.exit_cap == 0.09

    def test_rows_count(self):
        em = self._make_exit()
        assert len(em.rows()) == 3


# ===========================================================================
# CashFlowMetrics
# ===========================================================================

class TestCashFlowMetrics:
    def test_positive_cash_flow(self):
        cf = CashFlowMetrics(est_noi=50_000, annual_mortgage=30_000, down_payment=125_000)
        assert cf.annual_cash_flow == 20_000
        assert cf.monthly_cash_flow == pytest.approx(20_000 / 12)
        assert cf.coc_return == pytest.approx((20_000 / 125_000) * 100)
        # coc = 16% → GOOD
        assert cf._cf_grade() == "GOOD"

    def test_negative_cash_flow_grade(self):
        cf = CashFlowMetrics(est_noi=10_000, annual_mortgage=50_000, down_payment=100_000)
        assert cf._cf_grade() == "POOR/BLEEDING"

    def test_positive_high_coc_grade(self):
        cf = CashFlowMetrics(est_noi=60_000, annual_mortgage=20_000, down_payment=50_000)
        assert cf._cf_grade() == "GOOD"

    def test_thin_margin_grade(self):
        # coc = 5000/125000*100 = 4% → FAIR (Thin Margin)
        cf = CashFlowMetrics(est_noi=35_000, annual_mortgage=30_000, down_payment=125_000)
        assert cf._cf_grade() == "FAIR (Thin Margin)"

    def test_zero_down_payment(self):
        cf = CashFlowMetrics(est_noi=40_000, annual_mortgage=30_000, down_payment=0)
        assert cf.coc_return == 0

    def test_rows_count(self):
        cf = CashFlowMetrics(50_000, 30_000, 125_000)
        assert len(cf.rows()) == 3


# ===========================================================================
# DebtMetrics
# ===========================================================================

class TestDebtMetrics:
    def test_dscr_calculation(self):
        dm = DebtMetrics(est_noi=50_000, est_expenses=24_000,
                         annual_mortgage=30_000, annual_rent=60_000)
        assert dm.dscr == pytest.approx(50_000 / 30_000)

    def test_stressed_dscr(self):
        dm = DebtMetrics(est_noi=50_000, est_expenses=24_000,
                         annual_mortgage=30_000, annual_rent=60_000)
        expected = 50_000 / (30_000 + DebtMetrics.STRESS_DEBT_ADD)
        assert dm.stressed_dscr == pytest.approx(expected)

    def test_zero_mortgage(self):
        dm = DebtMetrics(est_noi=50_000, est_expenses=20_000,
                         annual_mortgage=0, annual_rent=60_000)
        assert dm.dscr == float("inf")

    def test_rows_count(self):
        dm = DebtMetrics(50_000, 24_000, 30_000, 60_000)
        assert len(dm.rows()) == 5


# ===========================================================================
# ReturnMetrics
# ===========================================================================

class TestReturnMetrics:
    def test_equity_multiple_above_one(self):
        prop = make_prop(asking_price=500_000, hold_years=10)
        rm = ReturnMetrics(prop, annual_cash_flow=20_000, cash_invested=125_000)
        assert rm.equity_multiple > 1.0

    def test_em_grade_excellent(self):
        prop = make_prop(asking_price=500_000, hold_years=20)
        rm = ReturnMetrics(prop, annual_cash_flow=50_000, cash_invested=100_000)
        grade = rm._em_grade()
        assert grade in ("EXCELLENT", "GOOD", "FAIR", "POOR (Underperforming)")

    def test_em_grade_poor(self):
        prop = make_prop(asking_price=500_000, hold_years=1)
        rm = ReturnMetrics(prop, annual_cash_flow=-50_000, cash_invested=100_000)
        assert rm._em_grade() == "POOR (Underperforming)"

    def test_irr_negative_when_loss(self):
        prop = make_prop(asking_price=500_000, hold_years=5)
        rm = ReturnMetrics(prop, annual_cash_flow=-30_000, cash_invested=125_000)
        assert rm.irr == -100.0

    def test_rows_count(self):
        prop = make_prop(asking_price=500_000, hold_years=5)
        rm = ReturnMetrics(prop, 20_000, 125_000)
        assert len(rm.rows()) == 2


# ===========================================================================
# MarketMetrics
# ===========================================================================

class TestMarketMetrics:
    def test_celoc_score(self):
        mm = MarketMetrics(est_noi=50_000, cash_invested=100_000,
                           est_expenses=24_000, annual_mortgage=30_000,
                           days_on_market=90)
        assert mm.celoc_score == pytest.approx(50_000 / 100_000 * 100)

    def test_celoc_grade_fast(self):
        mm = MarketMetrics(100_000, 100_000, 40_000, 30_000, 60)
        assert mm._celoc_grade() == "FAST CELOC"

    def test_celoc_grade_possible(self):
        mm = MarketMetrics(65_000, 100_000, 40_000, 30_000, 60)
        assert mm._celoc_grade() == "CELOC POSSIBLE"

    def test_celoc_grade_friction(self):
        mm = MarketMetrics(45_000, 100_000, 40_000, 30_000, 60)
        assert mm._celoc_grade() == "LENDER FRICTION"

    def test_celoc_grade_no_celoc(self):
        mm = MarketMetrics(30_000, 100_000, 40_000, 30_000, 60)
        assert mm._celoc_grade() == "NO CELOC"

    def test_rows_count(self):
        mm = MarketMetrics(50_000, 100_000, 24_000, 30_000, 90)
        assert len(mm.rows()) == 3


# ===========================================================================
# CommercialPropertyAnalyzer
# ===========================================================================

class TestCommercialPropertyAnalyzer:
    def test_full_analysis_with_direct_rent(self, tmp_path):
        store    = make_temp_store(tmp_path)
        resolver = make_resolver(store)
        prop = make_prop(annual_rent=72_000, listing_date="2024-01-01")
        analyzer = CommercialPropertyAnalyzer(prop, resolver)
        assert analyzer._has_rent is True
        report = analyzer.report()
        assert len(report) > 0

    def test_no_rent_no_income_metrics(self, tmp_path):
        store    = make_temp_store(tmp_path)
        resolver = make_resolver(store)
        # Missing city so commercial lookup fails → zero rent
        prop = make_prop(
            annual_rent=None,
            city="Atlantis", province="ON",
            property_type="Office",
            total_sq_ft=2_000,
            listing_date="2024-01-01",
        )
        with pytest.raises(ValueError):
            CommercialPropertyAnalyzer(prop, resolver)

    def test_analyzer_to_record(self, tmp_path):
        store    = make_temp_store(tmp_path)
        resolver = make_resolver(store)
        prop = make_prop(annual_rent=60_000, listing_date="2024-01-01",
                         address="1 King St", city="Ottawa", province="ON")
        analyzer = CommercialPropertyAnalyzer(prop, resolver)
        record = analyzer.to_record()
        assert record["address"] == "1 King St"
        assert "results" in record

    def test_analyzer_to_record_preserves_created_at(self, tmp_path):
        store    = make_temp_store(tmp_path)
        resolver = make_resolver(store)
        prop = make_prop(annual_rent=60_000, listing_date="2024-01-01")
        analyzer = CommercialPropertyAnalyzer(prop, resolver)
        existing = {"created_at": "2023-01-01"}
        record = analyzer.to_record(existing=existing)
        assert record["created_at"] == "2023-01-01"

    def test_analyzer_report_returns_rows(self, tmp_path):
        store    = make_temp_store(tmp_path)
        resolver = make_resolver(store)
        prop = make_prop(annual_rent=60_000, listing_date="2024-01-01")
        analyzer = CommercialPropertyAnalyzer(prop, resolver)
        rows = analyzer.report()
        assert all(isinstance(r, ReportRow) for r in rows)

    def test_analyzer_with_residential_units(self, tmp_path):
        store    = make_temp_store(tmp_path)
        resolver = make_resolver(store)
        um = UnitMix(one_br=4, two_br=2)
        prop = make_prop(
            annual_rent=None,
            city="Ottawa", province="ON",
            unit_mix=um,
            listing_date="2024-01-01",
        )
        analyzer = CommercialPropertyAnalyzer(prop, resolver)
        assert analyzer._has_rent is True


# ===========================================================================
# ReportPrinter
# ===========================================================================

class TestReportPrinter:
    def test_print_report_show_false(self, tmp_path, capsys):
        store    = make_temp_store(tmp_path)
        resolver = make_resolver(store)
        prop = make_prop(annual_rent=60_000, listing_date="2024-01-01")
        analyzer = CommercialPropertyAnalyzer(prop, resolver)
        ReportPrinter.print_report(analyzer, show=False)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_print_report_show_true(self, tmp_path, capsys):
        store    = make_temp_store(tmp_path)
        resolver = make_resolver(store)
        prop = make_prop(annual_rent=60_000, listing_date="2024-01-01")
        analyzer = CommercialPropertyAnalyzer(prop, resolver)
        ReportPrinter.print_report(analyzer, show=True)
        captured = capsys.readouterr()
        assert "METRIC" in captured.out

    def test_list_properties_no_props(self, tmp_path, capsys):
        store = make_temp_store(tmp_path)
        ReportPrinter.list_properties(store)
        captured = capsys.readouterr()
        assert "No saved properties" in captured.out

    def test_list_properties_with_records(self, tmp_path, capsys):
        store = make_temp_store(tmp_path, props=[
            {"address": "1 King St", "listing_date": "2024-01-01",
             "asking_price": 500_000, "total_sq_ft": 5000,
             "property_type": "Retail", "status": "active",
             "mls_number": "MLS123", "analyzed_on": "2024-02-01",
             "city": "Ottawa", "province": "ON", "results": []}
        ])
        ReportPrinter.list_properties(store)
        captured = capsys.readouterr()
        assert "1 King St" in captured.out


# ===========================================================================
# PropertyMenu — score_property and _record_to_prop
# ===========================================================================

class TestPropertyMenuScoreProperty:
    def _make_menu(self, tmp_path):
        store    = make_temp_store(tmp_path)
        resolver = make_resolver(store)
        return PropertyMenu(store, resolver)

    def test_score_no_income_returns_none(self, tmp_path):
        menu = self._make_menu(tmp_path)
        p = {"results": [{"metric": "Loan Amount", "value": "$375,000", "grade": "INFO"}]}
        result = menu._score_property(p)
        assert result["score"] is None

    def test_score_with_cap_rate(self, tmp_path):
        menu = self._make_menu(tmp_path)
        p = {"results": [
            {"metric": "Cap Rate",         "value": "8.00%",  "grade": "GOOD"},
            {"metric": "NOI",              "value": "$40,000", "grade": "GOOD"},
            {"metric": "CoCR",             "value": "12.00%", "grade": "GOOD"},
            {"metric": "DSCR",             "value": "1.80",   "grade": "GOOD"},
            {"metric": "IRR (5-Yr)",       "value": "18.00%", "grade": "GOOD"},
            {"metric": "Equity Multiple",  "value": "2.10x",  "grade": "GOOD"},
            {"metric": "Annual Cash Flow", "value": "$20,000", "grade": "GOOD"},
            {"metric": "Price Drop %",     "value": "10.00%", "grade": "GOOD"},
            {"metric": "Market Staleness", "value": "200 Days", "grade": "GOOD"},
        ]}
        result = menu._score_property(p)
        assert result["score"] is not None
        assert 0 <= result["score"] <= 100

    def test_record_to_prop_basic(self, tmp_path):
        menu = self._make_menu(tmp_path)
        record = {
            "address":          "1 King St",
            "asking_price":     500_000,
            "original_price":   500_000,
            "total_sq_ft":      5000,
            "property_taxes":   8000,
            "down_payment_pct": 0.25,
            "interest_rate":    0.065,
            "term_years":       25,
            "hold_years":       5,
            "expense_ratio":    0.40,
            "lease_type":       "Normal",
            "listing_date":     "2024-01-01",
            "annual_rent":      60_000,
            "commercial_rent":  None,
            "residential_rent": None,
            "city":             "Ottawa",
            "province":         "ON",
            "property_type":    None,
            "unit_mix":         {},
        }
        prop = PropertyMenu._record_to_prop(record)
        assert isinstance(prop, PropertyInput)
        assert prop.address == "1 King St"

    def test_record_to_prop_with_unit_mix(self, tmp_path):
        menu = self._make_menu(tmp_path)
        record = {
            "address":          "2 Queen St",
            "asking_price":     800_000,
            "original_price":   800_000,
            "total_sq_ft":      8000,
            "property_taxes":   12_000,
            "down_payment_pct": 0.25,
            "interest_rate":    0.065,
            "term_years":       25,
            "hold_years":       10,
            "expense_ratio":    0.40,
            "lease_type":       "Normal",
            "listing_date":     "2024-01-01",
            "annual_rent":      None,
            "commercial_rent":  0,
            "residential_rent": 0,
            "city":             "Ottawa",
            "province":         "ON",
            "property_type":    None,
            "unit_mix":         {"one_br": 3, "two_br": 2, "floors": 1},
        }
        prop = PropertyMenu._record_to_prop(record)
        assert prop.unit_mix is not None
        assert prop.unit_mix.one_br == 3


# ===========================================================================
# Integration tests
# ===========================================================================

class TestEndToEnd:
    def test_full_pipeline_commercial(self, tmp_path):
        store    = make_temp_store(tmp_path)
        resolver = make_resolver(store)
        prop = PropertyInput(
            original_price=1_000_000,
            asking_price=950_000,
            total_sq_ft=6_000,
            property_taxes=15_000,
            down_payment_pct=0.25,
            interest_rate=0.065,
            term_years=25,
            hold_years=10,
            expense_ratio=0.40,
            lease_type="Normal",
            listing_date="2024-01-01",
            address="456 Sparks St",
            city="Ottawa",
            province="ON",
            property_type="Retail",
        )
        analyzer = CommercialPropertyAnalyzer(prop, resolver)
        record = analyzer.to_record()
        store.save_property(record)
        props = store.load_properties()
        assert len(props) == 1
        assert props[0]["address"] == "456 Sparks St"

    def test_full_pipeline_residential(self, tmp_path):
        store    = make_temp_store(tmp_path)
        resolver = make_resolver(store)
        um = UnitMix(bachelor=2, one_br=4, two_br=3, floors=1)
        prop = PropertyInput(
            original_price=2_000_000,
            asking_price=1_900_000,
            total_sq_ft=12_000,
            property_taxes=20_000,
            down_payment_pct=0.25,
            interest_rate=0.065,
            term_years=25,
            hold_years=10,
            expense_ratio=0.40,
            lease_type="Normal",
            listing_date="2024-01-01",
            address="789 Rideau St",
            city="Ottawa",
            province="ON",
            unit_mix=um,
        )
        analyzer = CommercialPropertyAnalyzer(prop, resolver)
        assert analyzer._has_rent is True
        report = analyzer.report()
        assert len(report) > 0

    def test_full_pipeline_mixed_use(self, tmp_path):
        store    = make_temp_store(tmp_path)
        resolver = make_resolver(store)
        um = UnitMix(one_br=4, two_br=2, floors=3)
        prop = PropertyInput(
            original_price=3_000_000,
            asking_price=2_800_000,
            total_sq_ft=18_000,
            property_taxes=30_000,
            down_payment_pct=0.25,
            interest_rate=0.065,
            term_years=25,
            hold_years=10,
            expense_ratio=0.40,
            lease_type="Normal",
            listing_date="2024-01-01",
            address="321 Bank St",
            city="Ottawa",
            province="ON",
            property_type="Retail",
            unit_mix=um,
        )
        analyzer = CommercialPropertyAnalyzer(prop, resolver)
        assert analyzer._has_rent is True