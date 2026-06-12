"""
Regression tests: re-analysis must never reset a stored floor count, for any
property type.

Context: the Retail-Office floor-loss bug (see test_retail_office_floor_loss.py)
had a wider blast radius than one type — any unit-less record converted by
_record_to_prop got unit_mix=None, and to_record() then wrote floors=1 back.
A 2026-06-09 batch re-analysis stomped 9 Retail-Office and likely 12 unit-less
Mixed-Use records this way.  Two mechanisms now guarantee preservation:
  - _record_to_prop builds a UnitMix carrying floors whenever units exist
    (any type), and a floors-only UnitMix for unit-less Retail-Office;
  - to_record() falls back to the existing record's floors when the
    PropertyInput has no unit_mix, instead of a hardcoded 1.

Every property type is round-tripped through the real pipeline
(record → _record_to_prop → CommercialPropertyAnalyzer → to_record) twice,
asserting floors survive in both the top-level key and unit_mix.floors.
"""

import csv
import pytest
from unittest.mock import MagicMock, patch

from models.property_input import PropertyInput, UnitMix
from analysis.rent_resolver import RentResolver
from analysis.analyzer import CommercialPropertyAnalyzer
from ui.menu import PropertyMenu
from ui.csv_handler import CsvHandlerMixin


FLOORS = 3

ALL_TYPES = ["Office", "Retail", "Industrial", "Mixed-Use", "Hotel",
             "Retail-Office", "Residential", "Multi-Family", None]

UNIT_TYPES = ["Mixed-Use", "Multi-Family", "Residential", "Retail-Office"]


def _resolver():
    comm = MagicMock()
    comm.get_rent_per_sqft.return_value = 20.0
    res = MagicMock()
    res.get_rates.return_value = {"one_br": 1_500}
    return RentResolver(comm, res)


def _stored_record(property_type, units=0, **overrides):
    base = {
        "address":          "1 Test St, Peterborough, ON",
        "mls_number":       "X10000099",
        "status":           "active",
        "listing_date":     "2025-01-01",
        "asking_price":     800_000,
        "original_price":   800_000,
        "total_sq_ft":      6_000,
        "city":             "Peterborough",
        "province":         "ON",
        "property_type":    property_type,
        "property_taxes":   8_000,
        "down_payment_pct": 0.20,
        "interest_rate":    0.055,
        "term_years":       25,
        "hold_years":       30,
        "expense_ratio":    0.40,
        "lease_type":       "Normal",
        "construction_cost": 0,
        "annual_rent":          None,
        "commercial_rent":      62_000.0,
        "residential_rent":     36_000.0 if units else 0.0,
        "commercial_rent_user_entered": True,
        "residential_rent_user_entered": True,
        "vacancy_rate":         0.05,
        "noi_growth_rate":  None,
        "unit_mix": {
            "bachelor": 0, "one_br": units, "two_br": 0,
            "three_br": 0, "four_br": 0, "unknown": 0,
            "floors": FLOORS,
        },
        "floors": FLOORS,
        "results": [],
    }
    base.update(overrides)
    return base


def _reanalyze(record):
    prop     = PropertyMenu._record_to_prop(record)
    analyzer = CommercialPropertyAnalyzer(prop, _resolver())
    return analyzer.to_record(existing=record)


class TestUnitlessFloorPreservation:
    """Every type, no residential units — the configuration the bug destroyed."""

    @pytest.mark.parametrize("ptype", ALL_TYPES, ids=str)
    def test_reanalysis_preserves_floors(self, ptype):
        out = _reanalyze(_stored_record(ptype))
        assert out["floors"] == FLOORS
        assert out["unit_mix"]["floors"] == FLOORS

    @pytest.mark.parametrize("ptype", ALL_TYPES, ids=str)
    def test_second_reanalysis_still_preserves_floors(self, ptype):
        """The 2026-06-09 incident was a batch pass over already-saved records:
        the output of one analysis is the input of the next."""
        out = _reanalyze(_reanalyze(_stored_record(ptype)))
        assert out["floors"] == FLOORS
        assert out["unit_mix"]["floors"] == FLOORS

    @pytest.mark.parametrize("ptype", ALL_TYPES, ids=str)
    def test_saved_rent_not_disturbed(self, ptype):
        """Floor preservation must not knock manually entered rents off the short-circuit."""
        out = _reanalyze(_stored_record(ptype))
        assert out["annual_rent"] == pytest.approx(62_000.0)


class TestWithUnitsFloorPreservation:
    """Types that carry residential units — floors travel on the full UnitMix."""

    @pytest.mark.parametrize("ptype", UNIT_TYPES, ids=str)
    def test_reanalysis_preserves_floors(self, ptype):
        out = _reanalyze(_stored_record(ptype, units=4))
        assert out["floors"] == FLOORS
        assert out["unit_mix"]["floors"] == FLOORS

    @pytest.mark.parametrize("ptype", UNIT_TYPES, ids=str)
    def test_second_reanalysis_still_preserves_floors(self, ptype):
        out = _reanalyze(_reanalyze(_stored_record(ptype, units=4)))
        assert out["floors"] == FLOORS
        assert out["unit_mix"]["floors"] == FLOORS

    @pytest.mark.parametrize("ptype", UNIT_TYPES, ids=str)
    def test_unit_counts_preserved_alongside_floors(self, ptype):
        out = _reanalyze(_stored_record(ptype, units=4))
        assert out["unit_mix"]["one_br"] == 4


class TestLegacyRecordShapes:
    """Older records with missing or partial floor data must not crash and
    must not invent destructive values."""

    @pytest.mark.parametrize("ptype", ALL_TYPES, ids=str)
    def test_missing_unit_mix_uses_top_level_floors(self, ptype):
        out = _reanalyze(_stored_record(ptype, unit_mix=None))
        assert out["floors"] == FLOORS

    @pytest.mark.parametrize("ptype", ALL_TYPES, ids=str)
    def test_genuine_single_floor_stays_one(self, ptype):
        """floors=1 is a legitimate value — preservation must not inflate it."""
        record = _stored_record(ptype)
        record["floors"] = 1
        record["unit_mix"]["floors"] = 1
        out = _reanalyze(record)
        assert out["floors"] == 1
        assert out["unit_mix"]["floors"] == 1


class TestFirstSaveFloorPreservation:
    """A brand-new property has no existing record to fall back on — the
    PropertyInput built by the add form must itself carry the floors
    (via the floors-only UnitMix) so the very first save keeps them."""

    @pytest.mark.parametrize("ptype", ALL_TYPES, ids=str)
    def test_new_unitless_prop_saves_floors(self, ptype):
        prop = PropertyInput(
            address="1 Test St, Peterborough, ON",
            mls_number="X10000099", status="active",
            original_price=800_000, asking_price=800_000,
            total_sq_ft=6_000, property_taxes=8_000,
            down_payment_pct=0.20, interest_rate=0.055,
            term_years=25, hold_years=30,
            listing_date="2025-01-01",
            city="Peterborough", province="ON",
            property_type=ptype,
            commercial_rent=62_000.0,
            commercial_rent_user_entered=True,
            residential_rent_user_entered=True,
            unit_mix=UnitMix(floors=FLOORS),
        )
        out = CommercialPropertyAnalyzer(prop, _resolver()).to_record(existing=None)
        assert out["floors"] == FLOORS
        assert out["unit_mix"]["floors"] == FLOORS

    @pytest.mark.parametrize("ptype", ALL_TYPES, ids=str)
    def test_record_to_prop_carries_floors_for_unitless(self, ptype):
        """_record_to_prop builds a floors-only UnitMix for every unit-less
        type, so floors travel on the prop rather than relying solely on the
        existing-record fallback."""
        prop = PropertyMenu._record_to_prop(_stored_record(ptype))
        assert prop.unit_mix is not None
        assert prop.unit_mix.total_units == 0
        assert prop.unit_mix.floors == FLOORS


class _CsvImporter(CsvHandlerMixin):
    THIN_DIVIDER = ""

    def __init__(self):
        self._store    = MagicMock()
        self._resolver = _resolver()


class TestCsvImportFloorPreservation:
    """First import of a unit-less row must persist its floors, any type."""

    CSV_TYPES = ["Office", "Retail", "Industrial", "Mixed-Use", "Hotel",
                 "Retail-Office", "Residential", "Multi-Family"]

    def _import_row(self, tmp_path, ptype):
        row = {
            "address":         "1 Test St, Peterborough, ON",
            "mls_number":      "X10000099",
            "original_price":  "800000",
            "property_type":   ptype,
            "commercial_rent": "62000",
            "floors":          str(FLOORS),
            "total_sq_ft":     "6000",
        }
        path = tmp_path / "import.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(row.keys()))
            writer.writeheader()
            writer.writerow(row)
        importer = _CsvImporter()
        with patch("builtins.input", return_value=str(path)):
            importer._import_csv()
        assert importer._store.save_property.called, "row was not imported"
        return importer._store.save_property.call_args[0][0]

    @pytest.mark.parametrize("ptype", CSV_TYPES, ids=str)
    def test_unitless_row_keeps_floors(self, ptype, tmp_path):
        record = self._import_row(tmp_path, ptype)
        assert record["floors"] == FLOORS
        assert record["unit_mix"]["floors"] == FLOORS
