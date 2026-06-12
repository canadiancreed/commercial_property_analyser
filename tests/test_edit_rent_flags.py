"""
Tests for rent provenance flag correctness across all three write paths:
  1. _edit (menu optional fields 7/16)
  2. CSV import
  3. Clearing a rent in _edit (clears the flag so re-analysis doesn't re-freeze)

Each scenario verifies that after the write path runs, the correct flags are
stored in the record so the resolver and _reanalyze_city behave correctly on
the next pass.
"""
import csv
import pytest
from unittest.mock import MagicMock, patch, call
from datetime import date


# ── Shared helpers ────────────────────────────────────────────────────────────

def _base_record(**overrides):
    rec = {
        "address": "1 Main St", "mls_number": "X1", "status": "active",
        "listing_date": "2025-01-01", "created_at": "2025-01-01",
        "last_modified": "2025-01-01", "analyzed_on": "2025-01-01",
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


def _make_menu(records, comm_rate=20.0):
    from ui.menu import PropertyMenu
    from analysis.rent_resolver import RentResolver
    from models.constants import PROPERTY_TYPES

    store = MagicMock()
    store.load_properties.return_value = records

    comm_loader = MagicMock()
    comm_loader.get_rent_per_sqft.return_value = comm_rate
    res_loader = MagicMock()
    res_loader.get_rates.return_value = None

    resolver = RentResolver(comm_loader, res_loader, store)
    menu = PropertyMenu.__new__(PropertyMenu)
    menu._store       = store
    menu._resolver    = resolver
    menu.THIN_DIVIDER = "-" * 40
    menu.VALID_TYPES  = PROPERTY_TYPES
    return menu, store


# ── _edit: entering a rent sets the flag ─────────────────────────────────────

def _run_edit(menu, store, record, input_side_effect):
    """Drive _edit() with mocked internals so we skip the index-picker UI."""
    with patch.object(menu, "_sorted_props", return_value=[record]), \
         patch.object(menu, "_list"), \
         patch.object(menu, "_pick_index", return_value=0), \
         patch("builtins.input", side_effect=input_side_effect):
        menu._edit()


class TestEditSetsFlag:
    def test_editing_commercial_rent_sets_user_entered_true(self):
        """Typing a value into field 7 (Commercial rent) must set commercial_rent_user_entered."""
        record = _base_record(
            commercial_rent=80_000.0,
            commercial_rent_user_entered=False,
        )
        menu, store = _make_menu([record])
        # field 7 → new value → field 0 to exit
        _run_edit(menu, store, record, ["7", "95000", "0"])

        field_write = next(
            (c for c in store.update_property.call_args_list
             if "commercial_rent" in c[0][1]),
            None
        )
        assert field_write is not None, "commercial_rent was not written"
        written = field_write[0][1]
        assert written["commercial_rent"] == pytest.approx(95_000.0)
        assert written["commercial_rent_user_entered"] is True

    def test_editing_residential_rent_sets_user_entered_true(self):
        """Typing a value into field 16 (Residential rent) must set residential_rent_user_entered."""
        record = _base_record(
            property_type="Mixed-Use",
            residential_rent=24_000.0,
            residential_rent_user_entered=False,
            unit_mix={"bachelor": 0, "one_br": 2, "two_br": 0,
                      "three_br": 0, "four_br": 0, "unknown": 0, "floors": 2},
        )
        menu, store = _make_menu([record])
        _run_edit(menu, store, record, ["16", "30000", "0"])

        field_write = next(
            (c for c in store.update_property.call_args_list
             if "residential_rent" in c[0][1]),
            None
        )
        assert field_write is not None
        written = field_write[0][1]
        assert written["residential_rent"] == pytest.approx(30_000.0)
        assert written["residential_rent_user_entered"] is True


# ── _edit: clearing a rent clears the flag ────────────────────────────────────

class TestEditClearsFlag:
    def test_clearing_commercial_rent_sets_user_entered_false(self):
        """Pressing Enter (clear) on field 7 must set commercial_rent_user_entered=False
        so the next re-analysis re-derives from market rates instead of freezing None."""
        record = _base_record(
            commercial_rent=55_000.0,
            commercial_rent_user_entered=True,
        )
        menu, store = _make_menu([record])
        _run_edit(menu, store, record, ["7", "", "0"])

        field_write = next(
            (c for c in store.update_property.call_args_list
             if "commercial_rent" in c[0][1]),
            None
        )
        assert field_write is not None
        written = field_write[0][1]
        assert written["commercial_rent"] is None
        assert written["commercial_rent_user_entered"] is False

    def test_clearing_residential_rent_sets_user_entered_false(self):
        record = _base_record(
            residential_rent=40_000.0,
            residential_rent_user_entered=True,
        )
        menu, store = _make_menu([record])
        _run_edit(menu, store, record, ["16", "", "0"])

        field_write = next(
            (c for c in store.update_property.call_args_list
             if "residential_rent" in c[0][1]),
            None
        )
        assert field_write is not None
        written = field_write[0][1]
        assert written["residential_rent"] is None
        assert written["residential_rent_user_entered"] is False

    def test_cleared_flag_allows_reanalysis_to_re_derive(self):
        """After clearing a user-entered rent, re-analysis must re-derive from market rates."""
        record = _base_record(
            commercial_rent=55_000.0,
            commercial_rent_user_entered=True,
            residential_rent_user_entered=True,
        )
        menu, store = _make_menu([record], comm_rate=25.0)

        cleared_record = {**record,
                          "commercial_rent": None,
                          "commercial_rent_user_entered": False,
                          "residential_rent_user_entered": False}
        store.load_properties.side_effect = [
            [record],        # reload at end of _edit for re-analysis
            [cleared_record],
        ]

        _run_edit(menu, store, record, ["7", "", "0"])

        final_write = store.update_property.call_args_list[-1][0][1]
        assert final_write.get("commercial_rent") == pytest.approx(25.0 * 4_000)


# ── CSV import sets flags ─────────────────────────────────────────────────────

class TestCsvImportSetsFlags:
    def _importer(self, comm_rate=20.0, res_rates=None):
        from ui.csv_handler import CsvHandlerMixin
        from analysis.rent_resolver import RentResolver

        store = MagicMock()
        store.load_properties.return_value = []

        comm_loader = MagicMock()
        comm_loader.get_rent_per_sqft.return_value = comm_rate
        res_loader = MagicMock()
        res_loader.get_rates.return_value = res_rates

        resolver = RentResolver(comm_loader, res_loader, store)

        class _Importer(CsvHandlerMixin):
            THIN_DIVIDER = ""

        importer = _Importer.__new__(_Importer)
        importer._store    = store
        importer._resolver = resolver
        return importer, store

    def _write_csv(self, tmp_path, rows):
        path = tmp_path / "import.csv"
        fieldnames = [
            "address", "mls_number", "status", "original_price", "total_sq_ft",
            "property_type", "commercial_rent", "residential_rent", "floors",
            "bachelor", "one_br", "two_br", "three_br", "four_br", "unknown",
            "property_taxes", "down_payment_pct", "interest_rate", "term_years",
            "hold_years", "construction_cost",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in fieldnames})
        return str(path)

    def test_csv_commercial_rent_sets_flag(self, tmp_path):
        """A CSV row with commercial_rent must save commercial_rent_user_entered=True."""
        importer, store = self._importer(comm_rate=20.0)
        csv_path = self._write_csv(tmp_path, [{
            "address": "1 Test St, Ottawa, ON",
            "mls_number": "X1", "status": "active",
            "original_price": "500000", "total_sq_ft": "4000",
            "property_type": "Office", "commercial_rent": "80000",
            "property_taxes": "8000", "down_payment_pct": "25",
            "interest_rate": "5.5", "term_years": "25", "hold_years": "10",
            "floors": "1",
        }])
        with patch("builtins.input", return_value=csv_path):
            importer._import_csv()

        assert store.save_property.called
        saved = store.save_property.call_args[0][0]
        assert saved["commercial_rent_user_entered"] is True
        assert saved["residential_rent_user_entered"] is False

    def test_csv_no_rent_leaves_flags_false(self, tmp_path):
        """A CSV row with no explicit rent must leave both flags False (resolver derives)."""
        importer, store = self._importer(comm_rate=20.0)
        csv_path = self._write_csv(tmp_path, [{
            "address": "2 Test St, Ottawa, ON",
            "mls_number": "X2", "status": "active",
            "original_price": "500000", "total_sq_ft": "4000",
            "property_type": "Office",
            "property_taxes": "8000", "down_payment_pct": "25",
            "interest_rate": "5.5", "term_years": "25", "hold_years": "10",
            "floors": "1",
        }])
        with patch("builtins.input", return_value=csv_path):
            importer._import_csv()

        assert store.save_property.called
        saved = store.save_property.call_args[0][0]
        assert saved["commercial_rent_user_entered"] is False
        assert saved["residential_rent_user_entered"] is False

    def test_csv_residential_rent_sets_flag(self, tmp_path):
        """A CSV row with residential_rent must save residential_rent_user_entered=True."""
        importer, store = self._importer(res_rates={"one_br": 1_200})
        csv_path = self._write_csv(tmp_path, [{
            "address": "3 Test St, Ottawa, ON",
            "mls_number": "X3", "status": "active",
            "original_price": "500000", "total_sq_ft": "4000",
            "property_type": "Residential",
            "residential_rent": "36000", "one_br": "3",
            "property_taxes": "8000", "down_payment_pct": "25",
            "interest_rate": "5.5", "term_years": "25", "hold_years": "10",
            "floors": "1",
        }])
        with patch("builtins.input", return_value=csv_path):
            importer._import_csv()

        assert store.save_property.called
        saved = store.save_property.call_args[0][0]
        assert saved["residential_rent_user_entered"] is True
        assert saved["commercial_rent_user_entered"] is False

    def test_csv_user_rent_survives_reanalysis(self, tmp_path):
        """A rent imported from CSV (flag=True) must not be overwritten by _reanalyze_city."""
        from ui.menu import PropertyMenu
        from analysis.rent_resolver import RentResolver

        # Import with explicit commercial_rent=80_000
        importer, store = self._importer(comm_rate=25.0)
        csv_path = self._write_csv(tmp_path, [{
            "address": "4 Test St, Ottawa, ON",
            "mls_number": "X4", "status": "active",
            "original_price": "500000", "total_sq_ft": "4000",
            "property_type": "Office", "commercial_rent": "80000",
            "property_taxes": "8000", "down_payment_pct": "25",
            "interest_rate": "5.5", "term_years": "25", "hold_years": "10",
            "floors": "1",
        }])
        with patch("builtins.input", return_value=csv_path):
            importer._import_csv()

        saved = store.save_property.call_args[0][0]
        assert saved["commercial_rent_user_entered"] is True

        # Now run _reanalyze_city with a changed rate — rent must stay frozen
        from models.constants import PROPERTY_TYPES
        comm_loader = MagicMock()
        comm_loader.get_rent_per_sqft.return_value = 25.0  # new rate
        res_loader = MagicMock()
        res_loader.get_rates.return_value = None
        resolver = RentResolver(comm_loader, res_loader, store)

        reanalyze_store = MagicMock()
        reanalyze_store.load_properties.return_value = [saved]

        menu = PropertyMenu.__new__(PropertyMenu)
        menu._store       = reanalyze_store
        menu._resolver    = resolver
        menu.THIN_DIVIDER = ""
        menu.VALID_TYPES  = PROPERTY_TYPES
        menu._reanalyze_city("Ottawa", "ON")

        reanalyzed = reanalyze_store.update_property.call_args[0][1]
        assert reanalyzed["commercial_rent"] == pytest.approx(80_000.0)
        comm_loader.get_rent_per_sqft.assert_not_called()
