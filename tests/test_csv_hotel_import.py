"""Regression test: CSV import must preserve property_type='Hotel' for hotel rows.

Before the fix, the local COMMERCIAL_TYPES set in csv_handler.py omitted "hotel",
so prop_type_field was set to None for hotel rows and the saved record lost the type.
"""
import csv
import json
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Minimal stub so CsvHandlerMixin can be instantiated without a full UI stack
# ---------------------------------------------------------------------------

class _StubMenu:
    THIN_DIVIDER = "-" * 40

    def __init__(self, store, resolver):
        self._store    = store
        self._resolver = resolver


from ui.csv_handler import CsvHandlerMixin

class _Menu(_StubMenu, CsvHandlerMixin):
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_resolver():
    """Return a resolver that yields a plausible hotel revenue figure."""
    resolver = MagicMock()
    resolver.resolve.return_value = (500_000.0, ["Hotel revenue stub"])
    resolver._comm_rent = 500_000.0
    resolver._res_rent  = 0.0
    return resolver


def _write_hotel_csv(path):
    headers = [
        "address", "mls_number", "status", "original_price", "property_type",
        "commercial_rent", "floors", "total_sq_ft",
        "bachelor", "one_br", "two_br", "three_br", "four_br", "unknown",
        "residential_rent", "property_taxes", "down_payment_pct",
        "interest_rate", "term_years", "hold_years", "expense_ratio", "lease_type",
        "hotel_rooms", "hotel_adr", "hotel_occupancy",
        "ind_warehouse_sqft", "ind_office_sqft", "ind_yard_sqft",
        "ind_dock_doors", "ind_drive_in_doors", "ind_clear_height_ft",
        "ind_office_rate", "ind_yard_rate",
    ]
    row = {h: "" for h in headers}
    row.update({
        "address":        "123 Main St, Toronto ON",
        "mls_number":     "H-001",
        "status":         "active",
        "original_price": "2000000",
        "property_type":  "Hotel",
        "total_sq_ft":    "10000",
        "hotel_rooms":    "80",
        "hotel_adr":      "150",
        "hotel_occupancy":"65",
    })
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerow(row)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHotelCsvImport:

    def _run_import(self, csv_path, store, resolver):
        menu = _Menu(store, resolver)
        with patch("builtins.input", return_value=str(csv_path)), \
             patch("builtins.print"):
            menu._import_csv()

    def test_hotel_property_type_preserved_on_success(self, tmp_path, make_store):
        """PropertyInput passed to the analyzer must have property_type='Hotel' (success path)."""
        csv_path = tmp_path / "hotels.csv"
        _write_hotel_csv(csv_path)
        store = make_store()
        captured = {}

        from analysis.analyzer import CommercialPropertyAnalyzer
        real_init = CommercialPropertyAnalyzer.__init__

        def spy_init(self, prop, resolver):
            captured["property_type"] = prop.property_type
            real_init(self, prop, resolver)

        with patch.object(CommercialPropertyAnalyzer, "__init__", spy_init), \
             patch("builtins.print"):
            menu = _Menu(store, _make_resolver())
            with patch("builtins.input", return_value=str(csv_path)):
                menu._import_csv()

        assert captured.get("property_type") == "Hotel"

    def test_hotel_property_type_preserved_on_fallback(self, tmp_path, make_store):
        """A hotel row whose resolver raises must still save property_type='Hotel'
        in the fallback record — not None."""
        csv_path = tmp_path / "hotels.csv"
        _write_hotel_csv(csv_path)
        store = make_store()

        bad_resolver = MagicMock()
        bad_resolver.resolve.side_effect = ValueError("no rate")

        with patch("analysis.analyzer.CommercialPropertyAnalyzer.__init__",
                   side_effect=ValueError("forced fallback")), \
             patch("builtins.print"):
            menu = _Menu(store, bad_resolver)
            with patch("builtins.input", return_value=str(csv_path)):
                menu._import_csv()

        props = store.load_properties()
        assert len(props) == 1
        assert props[0].get("property_type") == "Hotel"

    def test_hotel_not_treated_as_residential(self, tmp_path, make_store):
        """prop_type_field must not be None for a Hotel row (the pre-fix bug)."""
        csv_path = tmp_path / "hotels.csv"
        _write_hotel_csv(csv_path)
        store = make_store()

        captured = {}

        from analysis.analyzer import CommercialPropertyAnalyzer

        real_init = CommercialPropertyAnalyzer.__init__

        def spy_init(self, prop, resolver):
            captured["property_type"] = prop.property_type
            real_init(self, prop, resolver)

        with patch.object(CommercialPropertyAnalyzer, "__init__", spy_init), \
             patch("builtins.print"):
            menu = _Menu(store, _make_resolver())
            with patch("builtins.input", return_value=str(csv_path)):
                menu._import_csv()

        assert captured.get("property_type") == "Hotel", (
            "property_type passed to analyzer must be 'Hotel', not None. "
            "This catches the pre-fix bug where 'hotel' was missing from COMMERCIAL_TYPES."
        )
