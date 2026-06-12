"""Tests for the 'optional' branch in PropertyMenu._edit.

Covers the three paths through the optional/float field handling:
  - invalid (non-numeric) input → prints error, does NOT update store
  - empty input → clears the field (sets to None)
  - valid numeric input → updates the field
"""
import pytest
from unittest.mock import MagicMock, patch, call

from ui.menu import PropertyMenu


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_menu():
    """Return a PropertyMenu with all dependencies stubbed."""
    store    = MagicMock()
    resolver = MagicMock()
    scorer   = MagicMock()
    ranker   = MagicMock()

    menu = PropertyMenu.__new__(PropertyMenu)
    menu._store    = store
    menu._resolver = resolver
    menu._scorer   = scorer
    menu._ranker   = ranker
    menu._prop_rpt = MagicMock()
    menu._city_rpt = MagicMock()
    return menu


def _run_edit(menu, prop: dict, field_inputs: list[str]):
    """
    Drive PropertyMenu._edit for a single property.

    Mocks out the property-selection plumbing (_sorted_props, _list,
    _pick_index, load_properties) and supplies `field_inputs` as the sequence
    of values the user types at the field-editing prompts.

    field_inputs should be the responses AFTER property selection, i.e.:
        ["7", "<value>", "0"]
    """
    menu._store.load_properties.return_value = [prop]

    with patch.object(menu, "_sorted_props", return_value=[prop]), \
         patch.object(menu, "_list"), \
         patch.object(menu, "_pick_index", return_value=0), \
         patch("builtins.input", side_effect=field_inputs), \
         patch("builtins.print"):
        menu._edit()

    return menu._store


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOptionalFieldEdit:
    """PropertyMenu._edit — 'optional' branch (e.g. commercial_rent, float)."""

    def test_invalid_input_does_not_call_update(self):
        """Non-numeric string must not reach update_property."""
        menu = _make_menu()
        prop = {"commercial_rent": 50000.0, "address": "123 Main St", "mls_number": "X1"}
        store = _run_edit(menu, prop, ["7", "abc", "0"])
        store.update_property.assert_not_called()

    def test_invalid_input_does_not_crash(self):
        """Non-numeric string must be caught — ValueError must not propagate."""
        menu = _make_menu()
        prop = {"commercial_rent": None, "address": "123 Main St", "mls_number": "X1"}
        # If the bug is present this raises ValueError; the test passing proves the fix.
        _run_edit(menu, prop, ["7", "not_a_number", "0"])

    def test_empty_input_clears_field(self):
        """Empty string must clear the field (set to None) and flag user_entered=False."""
        menu = _make_menu()
        prop = {"commercial_rent": 60000.0, "address": "123 Main St", "mls_number": "X1"}
        store = _run_edit(menu, prop, ["7", "", "0"])
        store.update_property.assert_called_once()
        _, update = store.update_property.call_args[0]
        assert update["commercial_rent"] is None
        assert update["commercial_rent_user_entered"] is False

    def test_valid_numeric_input_updates_field(self):
        """Valid float string must persist the parsed value and set user_entered=True."""
        menu = _make_menu()
        prop = {"commercial_rent": None, "address": "123 Main St", "mls_number": "X1"}
        store = _run_edit(menu, prop, ["7", "75000", "0"])
        store.update_property.assert_called_once()
        _, update = store.update_property.call_args[0]
        assert update["commercial_rent"] == pytest.approx(75000.0)
        assert update["commercial_rent_user_entered"] is True

    def test_invalid_then_valid_saves_on_second_attempt(self):
        """Bad input re-prompts the field menu; a valid value on the next pick saves."""
        menu = _make_menu()
        prop = {"commercial_rent": None, "address": "123 Main St", "mls_number": "X1"}
        # bad → loop continues back to field selection → re-pick field 7 → valid value
        store = _run_edit(menu, prop, ["7", "bad", "7", "42000", "0"])
        store.update_property.assert_called_once()
        _, update = store.update_property.call_args[0]
        assert update["commercial_rent"] == pytest.approx(42000.0)
