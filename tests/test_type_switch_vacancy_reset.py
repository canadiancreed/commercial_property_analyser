"""
Regression tests for the vacancy-rate ratchet bug.

When a property's type is changed via _edit (field 6), both expense_ratio and
vacancy_rate must be reset to None so __post_init__ re-derives correct defaults
for the new type on the next analysis pass.

Without the fix, the old type's vacancy_rate would survive the type change and
silently distort effective gross income for the new property type.
"""
import pytest
from unittest.mock import MagicMock, patch


# ── Helpers ───────────────────────────────────────────────────────────────────

def _base_record(**overrides):
    rec = {
        "address": "1 Main St", "mls_number": "X1", "status": "active",
        "listing_date": "2025-01-01", "created_at": "2025-01-01",
        "last_modified": "2025-01-01", "analyzed_on": "2025-01-01",
        "asking_price": 500_000, "original_price": 500_000,
        "total_sq_ft": 4_000, "property_taxes": 8_000,
        "down_payment_pct": 0.25, "interest_rate": 0.055,
        "term_years": 25, "hold_years": 10,
        "expense_ratio": 0.42, "lease_type": "Normal",
        "construction_cost": 0,
        "city": "Ottawa", "province": "ON",
        "property_type": "Office",
        "annual_rent": None,
        "commercial_rent": 80_000.0,
        "residential_rent": 0.0,
        "commercial_rent_user_entered": False,
        "residential_rent_user_entered": False,
        "rent_breakdown": [],
        "vacancy_rate": 0.14,   # Office default — the stale value under test
        "noi_growth_rate": None,
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


def _make_menu(records):
    from ui.menu import PropertyMenu
    from analysis.rent_resolver import RentResolver
    from models.constants import PROPERTY_TYPES

    store = MagicMock()
    store.load_properties.return_value = records

    comm_loader = MagicMock()
    comm_loader.get_rent_per_sqft.return_value = 20.0
    res_loader = MagicMock()
    res_loader.get_rates.return_value = None

    resolver = RentResolver(comm_loader, res_loader, store)
    menu = PropertyMenu.__new__(PropertyMenu)
    menu._store       = store
    menu._resolver    = resolver
    menu.THIN_DIVIDER = "-" * 40
    menu.VALID_TYPES  = PROPERTY_TYPES
    return menu, store


def _run_type_change(menu, store, record, new_type_input):
    """Drive _edit() through field 6 (Property type) then exit."""
    with patch.object(menu, "_sorted_props", return_value=[record]), \
         patch.object(menu, "_list"), \
         patch.object(menu, "_pick_index", return_value=0), \
         patch("builtins.input", side_effect=["6", new_type_input, "0"]):
        menu._edit()


def _type_change_write(store):
    """Return the update_property payload that contains property_type, or None."""
    return next(
        (c[0][1] for c in store.update_property.call_args_list
         if "property_type" in c[0][1]),
        None,
    )


# ── Core regression: vacancy_rate and expense_ratio both reset ────────────────

class TestTypeChangeResetsRates:
    def test_store_write_clears_vacancy_rate(self):
        """Changing property type must write vacancy_rate=None to the store."""
        record = _base_record(property_type="Office", vacancy_rate=0.14)
        menu, store = _make_menu([record])
        _run_type_change(menu, store, record, "r")   # Office → Retail

        written = _type_change_write(store)
        assert written is not None, "No property_type update written"
        assert written["vacancy_rate"] is None, (
            "vacancy_rate must be None after type change so __post_init__ "
            "re-derives the correct default for the new type"
        )

    def test_store_write_clears_expense_ratio(self):
        """Changing property type must also write expense_ratio=None (pre-existing behaviour)."""
        record = _base_record(property_type="Office", expense_ratio=0.42)
        menu, store = _make_menu([record])
        _run_type_change(menu, store, record, "r")

        written = _type_change_write(store)
        assert written is not None
        assert written["expense_ratio"] is None

    def test_in_memory_dict_cleared(self):
        """The in-memory property dict must also have vacancy_rate=None after the edit."""
        record = _base_record(property_type="Office", vacancy_rate=0.14)
        menu, store = _make_menu([record])
        _run_type_change(menu, store, record, "r")

        assert record["vacancy_rate"] is None


# ── All cross-type switches that change vacancy default ───────────────────────
#
# VACANCY_RATE_DEFAULTS:
#   office=0.14, retail=0.05, industrial=0.05, mixed-use=0.09,
#   retail-office=0.09, multi-family=0.03, residential=0.03, hotel=0.00

# Pairs where the vacancy default differs between from_type and to_type,
# represented as (from_type, from_vacancy, shortcut_to, to_label).
SWITCHING_PAIRS = [
    # Office (0.14) → anything lower
    ("Office",       0.14, "r",  "Retail"),
    ("Office",       0.14, "i",  "Industrial"),
    ("Office",       0.14, "m",  "Mixed-Use"),
    ("Office",       0.14, "ro", "Retail-Office"),
    ("Office",       0.14, "mu", "Multi-Family"),
    ("Office",       0.14, "re", "Residential"),
    ("Office",       0.14, "h",  "Hotel"),
    # Retail (0.05) → types with different defaults
    ("Retail",       0.05, "o",  "Office"),
    ("Retail",       0.05, "m",  "Mixed-Use"),
    ("Retail",       0.05, "ro", "Retail-Office"),
    ("Retail",       0.05, "mu", "Multi-Family"),
    ("Retail",       0.05, "re", "Residential"),
    ("Retail",       0.05, "h",  "Hotel"),
    # Industrial (0.05) → types with different defaults
    ("Industrial",   0.05, "o",  "Office"),
    ("Industrial",   0.05, "m",  "Mixed-Use"),
    ("Industrial",   0.05, "ro", "Retail-Office"),
    ("Industrial",   0.05, "mu", "Multi-Family"),
    ("Industrial",   0.05, "re", "Residential"),
    ("Industrial",   0.05, "h",  "Hotel"),
    # Mixed-Use (0.09) → types with different defaults
    ("Mixed-Use",    0.09, "o",  "Office"),
    ("Mixed-Use",    0.09, "r",  "Retail"),
    ("Mixed-Use",    0.09, "i",  "Industrial"),
    ("Mixed-Use",    0.09, "mu", "Multi-Family"),
    ("Mixed-Use",    0.09, "re", "Residential"),
    ("Mixed-Use",    0.09, "h",  "Hotel"),
    # Retail-Office (0.09) → types with different defaults
    ("Retail-Office",0.09, "o",  "Office"),
    ("Retail-Office",0.09, "r",  "Retail"),
    ("Retail-Office",0.09, "i",  "Industrial"),
    ("Retail-Office",0.09, "mu", "Multi-Family"),
    ("Retail-Office",0.09, "re", "Residential"),
    ("Retail-Office",0.09, "h",  "Hotel"),
    # Multi-Family (0.03) → types with different defaults
    ("Multi-Family", 0.03, "o",  "Office"),
    ("Multi-Family", 0.03, "r",  "Retail"),
    ("Multi-Family", 0.03, "i",  "Industrial"),
    ("Multi-Family", 0.03, "m",  "Mixed-Use"),
    ("Multi-Family", 0.03, "ro", "Retail-Office"),
    ("Multi-Family", 0.03, "h",  "Hotel"),
    # Residential (0.03) → types with different defaults
    ("Residential",  0.03, "o",  "Office"),
    ("Residential",  0.03, "r",  "Retail"),
    ("Residential",  0.03, "i",  "Industrial"),
    ("Residential",  0.03, "m",  "Mixed-Use"),
    ("Residential",  0.03, "ro", "Retail-Office"),
    ("Residential",  0.03, "h",  "Hotel"),
    # Hotel (0.00) → types with different defaults
    ("Hotel",        0.00, "o",  "Office"),
    ("Hotel",        0.00, "r",  "Retail"),
    ("Hotel",        0.00, "i",  "Industrial"),
    ("Hotel",        0.00, "m",  "Mixed-Use"),
    ("Hotel",        0.00, "ro", "Retail-Office"),
    ("Hotel",        0.00, "mu", "Multi-Family"),
    ("Hotel",        0.00, "re", "Residential"),
]


@pytest.mark.parametrize(
    "from_type,from_vacancy,shortcut,to_type",
    SWITCHING_PAIRS,
    ids=[f"{f}->{t}" for f, _, __, t in SWITCHING_PAIRS],
)
class TestAllTypeSwitch:
    def test_vacancy_rate_reset_to_none(self, from_type, from_vacancy, shortcut, to_type):
        """vacancy_rate written to store must be None for every cross-type switch."""
        record = _base_record(property_type=from_type, vacancy_rate=from_vacancy)
        menu, store = _make_menu([record])
        _run_type_change(menu, store, record, shortcut)

        written = _type_change_write(store)
        assert written is not None, f"No property_type update for {from_type}→{to_type}"
        assert written["vacancy_rate"] is None, (
            f"{from_type}→{to_type}: expected vacancy_rate=None in store write, "
            f"got {written['vacancy_rate']!r}"
        )

    def test_expense_ratio_reset_to_none(self, from_type, from_vacancy, shortcut, to_type):
        """expense_ratio written to store must also be None for every cross-type switch."""
        record = _base_record(property_type=from_type, vacancy_rate=from_vacancy)
        menu, store = _make_menu([record])
        _run_type_change(menu, store, record, shortcut)

        written = _type_change_write(store)
        assert written is not None
        assert written["expense_ratio"] is None, (
            f"{from_type}→{to_type}: expected expense_ratio=None in store write, "
            f"got {written['expense_ratio']!r}"
        )
