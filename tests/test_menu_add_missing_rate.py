"""Adding a property whose city has no market rate must not lose the entry.

Regression: adding a new industrial (or any commercial) property for a city with
no rate data raised ValueError inside the analyzer; PropertyMenu._add caught it,
printed an error, and returned *before* saving the property or registering the
city. The entry was lost and the city never appeared for rate entry.

The fix saves a partial record (no analysis results) and registers the city so
rates can be added later and the property re-analyzed.
"""
from unittest.mock import MagicMock, patch

from ui.menu import PropertyMenu
from models.property_input import PropertyInput, UnitMix


def _make_menu():
    menu = PropertyMenu.__new__(PropertyMenu)
    menu._store    = MagicMock()
    menu._resolver = MagicMock()
    menu._scorer   = MagicMock()
    menu._ranker   = MagicMock()
    menu._prop_rpt = MagicMock()
    menu._city_rpt = MagicMock()
    return menu


def _industrial_prop():
    return PropertyInput(
        address="100 Industrial Way, Newcity, ON",
        mls_number="MLS-1", status="active",
        original_price=1_000_000, asking_price=1_000_000,
        total_sq_ft=40_000, property_taxes=12_000,
        down_payment_pct=0.20, interest_rate=0.05, term_years=25,
        listing_date="2026-06-16", hold_years=30,
        city="Newcity", province="ON", property_type="Industrial",
        unit_mix=UnitMix(floors=1),
        ind_warehouse_sqft=35_000, ind_office_sqft=5_000,
    )


class TestAddMissingRate:
    def test_partial_record_saved_and_city_registered(self):
        menu = _make_menu()
        prop = _industrial_prop()

        with patch.object(menu, "_prompt_property", return_value=prop), \
             patch("ui.menu.CommercialPropertyAnalyzer",
                   side_effect=ValueError("No commercial rate for Newcity, ON (Industrial).")), \
             patch("builtins.input", side_effect=[""]), \
             patch("builtins.print"):
            menu._add()

        # Property still saved (entry not lost) ...
        menu._store.save_property.assert_called_once()
        record = menu._store.save_property.call_args[0][0]
        assert record["address"] == prop.address
        assert record["property_type"] == "Industrial"
        assert record["results"] == []
        assert record["analyzed_on"] is None

        # ... and the city registered so rates can be added later.
        menu._store.ensure_city_in_rates.assert_called_once_with("Newcity", "ON")

    def test_notes_attached_to_partial_record(self):
        menu = _make_menu()
        prop = _industrial_prop()

        with patch.object(menu, "_prompt_property", return_value=prop), \
             patch("ui.menu.CommercialPropertyAnalyzer",
                   side_effect=ValueError("No commercial rate.")), \
             patch("builtins.input", side_effect=["check zoning"]), \
             patch("builtins.print"):
            menu._add()

        record = menu._store.save_property.call_args[0][0]
        assert record["notes"] == "check zoning"
