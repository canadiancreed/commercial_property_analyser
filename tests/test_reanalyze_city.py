"""
Tests for PropertyMenu._reanalyze_city.

Verifies that re-analysis:
  - Updates resolver-derived rents when market rates change
  - Leaves user-entered commercial rents frozen (commercial_rent_user_entered=True)
  - Leaves user-entered residential rents frozen (residential_rent_user_entered=True)
  - Updates only the unfrozen component when one is frozen and the other is derived
  - Skips records from other cities
"""
import pytest
from unittest.mock import MagicMock, patch, call
from models.property_input import UnitMix


# ── Helpers ───────────────────────────────────────────────────────────────────

def _base_record(**overrides):
    rec = {
        "address": "1 Main St",
        "mls_number": "", "status": "active",
        "listing_date": "2025-01-01",
        "created_at": "2025-01-01", "last_modified": "2025-01-01", "analyzed_on": "2025-01-01",
        "asking_price": 500_000, "original_price": 500_000,
        "total_sq_ft": 4_000, "property_taxes": 8_000,
        "down_payment_pct": 0.25, "interest_rate": 0.055,
        "term_years": 25, "hold_years": 10,
        "expense_ratio": 0.40, "lease_type": "Normal",
        "construction_cost": 0,
        "city": "Ottawa", "province": "ON",
        "property_type": "Office",
        "annual_rent": None,
        "commercial_rent": 80_000.0,
        "residential_rent": 0.0,
        "commercial_rent_user_entered": False,
        "residential_rent_user_entered": False,
        "rent_breakdown": [],
        "vacancy_rate": 0.05, "noi_growth_rate": None,
        "unit_mix": {"bachelor": 0, "one_br": 0, "two_br": 0,
                     "three_br": 0, "four_br": 0, "unknown": 0, "floors": 1},
        "floors": 1,
        "hotel_rooms": 0, "hotel_adr": None, "hotel_occupancy": None,
        "ind_warehouse_sqft": 0, "ind_office_sqft": 0, "ind_yard_sqft": 0,
        "ind_dock_doors": 0, "ind_drive_in_doors": 0, "ind_clear_height_ft": 0,
        "ind_office_rate": None, "ind_yard_rate": None,
        "results": [],
    }
    rec.update(overrides)
    return rec


def _make_menu(records, comm_rate=20.0, res_rates=None):
    """Build a PropertyMenu with mocked store and resolver."""
    from ui.menu import PropertyMenu
    from analysis.rent_resolver import RentResolver
    from data.store import CommercialRentLoader, ResidentialRentLoader

    store = MagicMock()
    store.load_properties.return_value = records

    comm_loader = MagicMock()
    comm_loader.get_rent_per_sqft.return_value = comm_rate
    res_loader = MagicMock()
    res_loader.get_rates.return_value = res_rates

    resolver = RentResolver(comm_loader, res_loader, store)

    menu = PropertyMenu.__new__(PropertyMenu)
    menu._store    = store
    menu._resolver = resolver
    return menu, store


# ── Derived rents update on re-analysis ───────────────────────────────────────

class TestDerivedRentsUpdate:
    def test_commercial_derived_rent_updates_when_rate_changes(self):
        """commercial_rent_user_entered=False → new rate replaces stored value."""
        record = _base_record(
            commercial_rent=80_000.0,  # old value at old rate
            commercial_rent_user_entered=False,
        )
        menu, store = _make_menu([record], comm_rate=25.0)
        menu._reanalyze_city("Ottawa", "ON")

        saved = store.update_property.call_args[0][1]
        # new rate 25 × 4000 sqft = 100_000
        assert saved["commercial_rent"] == pytest.approx(100_000.0)

    def test_skips_records_from_other_cities(self):
        """Records not matching city/province must not be updated."""
        record = _base_record(city="Toronto", province="ON")
        menu, store = _make_menu([record], comm_rate=25.0)
        menu._reanalyze_city("Ottawa", "ON")
        store.update_property.assert_not_called()

    def test_skips_records_mismatched_province(self):
        record = _base_record(city="Ottawa", province="QC")
        menu, store = _make_menu([record], comm_rate=25.0)
        menu._reanalyze_city("Ottawa", "ON")
        store.update_property.assert_not_called()


# ── Frozen commercial rent preserved on re-analysis ──────────────────────────

class TestFrozenCommercialPreserved:
    def test_manual_commercial_rent_not_overwritten(self):
        """commercial_rent_user_entered=True → stored value survives rate change."""
        record = _base_record(
            commercial_rent=55_000.0,
            commercial_rent_user_entered=True,
            residential_rent_user_entered=True,  # pure commercial, both frozen
        )
        menu, store = _make_menu([record], comm_rate=25.0)
        menu._reanalyze_city("Ottawa", "ON")

        saved = store.update_property.call_args[0][1]
        assert saved["commercial_rent"] == pytest.approx(55_000.0)

    def test_commercial_market_lookup_not_called_when_frozen(self):
        record = _base_record(
            commercial_rent=55_000.0,
            commercial_rent_user_entered=True,
            residential_rent_user_entered=True,
        )
        menu, store = _make_menu([record], comm_rate=25.0)
        menu._reanalyze_city("Ottawa", "ON")
        menu._resolver._commercial.get_rent_per_sqft.assert_not_called()


# ── Frozen residential rent preserved on re-analysis ─────────────────────────

class TestFrozenResidentialPreserved:
    def test_manual_residential_rent_not_overwritten(self):
        """residential_rent_user_entered=True → stored value survives rate change."""
        record = _base_record(
            property_type="Residential",
            commercial_rent=0.0,
            residential_rent=40_000.0,
            commercial_rent_user_entered=True,
            residential_rent_user_entered=True,
            unit_mix={"bachelor": 0, "one_br": 3, "two_br": 0,
                      "three_br": 0, "four_br": 0, "unknown": 0, "floors": 1},
        )
        menu, store = _make_menu([record], comm_rate=None,
                                  res_rates={"one_br": 2_000})
        menu._reanalyze_city("Ottawa", "ON")

        saved = store.update_property.call_args[0][1]
        assert saved["residential_rent"] == pytest.approx(40_000.0)

    def test_residential_market_lookup_not_called_when_frozen(self):
        record = _base_record(
            property_type="Residential",
            commercial_rent=0.0,
            residential_rent=40_000.0,
            commercial_rent_user_entered=True,
            residential_rent_user_entered=True,
            unit_mix={"bachelor": 0, "one_br": 3, "two_br": 0,
                      "three_br": 0, "four_br": 0, "unknown": 0, "floors": 1},
        )
        menu, store = _make_menu([record], res_rates={"one_br": 2_000})
        menu._reanalyze_city("Ottawa", "ON")
        menu._resolver._residential.get_rates.assert_not_called()


# ── Partial freeze: one component frozen, other updates ───────────────────────

class TestPartialFreezeOnReanalysis:
    def test_frozen_comm_derived_res_updates(self):
        """Mixed-use: manual commercial preserved, residential re-derived at new rate."""
        record = _base_record(
            property_type="Mixed-Use",
            commercial_rent=55_000.0,
            residential_rent=24_000.0,  # old value
            commercial_rent_user_entered=True,
            residential_rent_user_entered=False,
            unit_mix={"bachelor": 0, "one_br": 2, "two_br": 0,
                      "three_br": 0, "four_br": 0, "unknown": 0, "floors": 2},
            floors=2, total_sq_ft=4_000,
        )
        menu, store = _make_menu([record], comm_rate=25.0,
                                  res_rates={"one_br": 1_500})
        menu._reanalyze_city("Ottawa", "ON")

        saved = store.update_property.call_args[0][1]
        assert saved["commercial_rent"] == pytest.approx(55_000.0)
        # new res: 1500 × 2 units × 12 months = 36_000
        assert saved["residential_rent"] == pytest.approx(36_000.0)

    def test_frozen_res_derived_comm_updates(self):
        """Mixed-use: manual residential preserved, commercial re-derived at new rate."""
        record = _base_record(
            property_type="Mixed-Use",
            commercial_rent=40_000.0,  # old value
            residential_rent=40_000.0,
            commercial_rent_user_entered=False,
            residential_rent_user_entered=True,
            unit_mix={"bachelor": 0, "one_br": 2, "two_br": 0,
                      "three_br": 0, "four_br": 0, "unknown": 0, "floors": 2},
            floors=2, total_sq_ft=4_000,
        )
        menu, store = _make_menu([record], comm_rate=25.0,
                                  res_rates={"one_br": 1_500})
        menu._reanalyze_city("Ottawa", "ON")

        saved = store.update_property.call_args[0][1]
        # new comm: 25 × (4000/2) = 50_000
        assert saved["commercial_rent"] == pytest.approx(50_000.0)
        assert saved["residential_rent"] == pytest.approx(40_000.0)

    def test_flags_preserved_in_saved_record(self):
        """The two-key flags must be written back correctly after re-analysis."""
        record = _base_record(
            commercial_rent=55_000.0,
            commercial_rent_user_entered=True,
            residential_rent_user_entered=False,
        )
        menu, store = _make_menu([record], comm_rate=25.0)
        menu._reanalyze_city("Ottawa", "ON")

        saved = store.update_property.call_args[0][1]
        assert saved["commercial_rent_user_entered"] is True
        assert saved["residential_rent_user_entered"] is False
