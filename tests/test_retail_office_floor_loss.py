"""
Regression tests for the Retail-Office floor-loss bug.

Context: a unit-less Retail-Office stores its floor count only on UnitMix.
Three paths used to drop it:
  1. _record_to_prop built a UnitMix only when residential units existed, so a
     unit-less Retail-Office loaded for re-analysis lost its floors.
  2. analyzer.to_record() then wrote floors=1 back, permanently destroying the
     stored value (PropertyInput has no top-level `floors` field, so the old
     getattr fallbacks always yielded 1).
  3. CSV import never built a UnitMix for a unit-less Retail-Office row, so
     floors were lost on first import.
With floors collapsed to 1 and no saved commercial_rent, the resolver priced
the whole building at the ground-floor Retail rate across all square footage.

Four layers are tested:
  1. _record_to_prop  — floors survive record → PropertyInput conversion
  2. RentResolver     — multi-floor Retail-Office rent uses every floor
  3. End-to-end       — record → _record_to_prop → analyzer → to_record()
  4. CSV import       — floors survive a unit-less Retail-Office row
"""

import csv
import pytest
from unittest.mock import MagicMock, patch

from models.property_input import PropertyInput, UnitMix
from analysis.rent_resolver import RentResolver
from analysis.analyzer import CommercialPropertyAnalyzer
from ui.menu import PropertyMenu
from ui.csv_handler import CsvHandlerMixin


# ── Helpers ───────────────────────────────────────────────────────────────────

RETAIL_RATE = 30.0   # $/sqft/yr
OFFICE_RATE = 20.0   # $/sqft/yr
SQ_FT       = 3_000
FLOORS      = 3
# 3 floors → 1,000 sqft/floor: ground Retail 30,000 + 2 Office floors 40,000
EXPECTED_3F_RENT = 70_000.0


def _resolver():
    comm = MagicMock()
    comm.get_rent_per_sqft.side_effect = (
        lambda city, province, ptype: {"Retail": RETAIL_RATE, "Office": OFFICE_RATE}.get(ptype)
    )
    res = MagicMock()
    res.get_rates.return_value = None
    return RentResolver(comm, res)


def _stored_record(**overrides):
    """Minimal stored JSON record for a 3-floor unit-less Retail-Office."""
    base = {
        "address":          "379 George St N, Peterborough, ON",
        "mls_number":       "X12846518",
        "status":           "active",
        "listing_date":     "2025-01-01",
        "asking_price":     900_000,
        "original_price":   900_000,
        "total_sq_ft":      SQ_FT,
        "city":             "Peterborough",
        "province":         "ON",
        "property_type":    "Retail-Office",
        "property_taxes":   6_000,
        "down_payment_pct": 0.20,
        "interest_rate":    0.055,
        "term_years":       25,
        "hold_years":       30,
        "expense_ratio":    0.40,
        "lease_type":       "Normal",
        "construction_cost": 0,
        "annual_rent":         62_369.0,
        "commercial_rent":     62_369.0,
        "residential_rent":    0.0,
        "commercial_rent_user_entered": True,
        "residential_rent_user_entered": False,
        "vacancy_rate":        0.05,
        "noi_growth_rate":  None,
        "unit_mix": {
            "bachelor": 0, "one_br": 0, "two_br": 0,
            "three_br": 0, "four_br": 0, "unknown": 0,
            "floors": FLOORS,
        },
        "floors": FLOORS,
        "results": [],
    }
    base.update(overrides)
    return base


# ── Layer 1: _record_to_prop ──────────────────────────────────────────────────

class TestRecordToPropFloors:

    def test_unitless_retail_office_keeps_floors(self):
        """No residential units → UnitMix must still carry the stored floors."""
        prop = PropertyMenu._record_to_prop(_stored_record())
        assert prop.unit_mix is not None
        assert prop.unit_mix.total_units == 0
        assert prop.unit_mix.floors == FLOORS

    def test_floors_fall_back_to_top_level_key(self):
        """Older records may lack unit_mix entirely — top-level floors must be used."""
        record = _stored_record(unit_mix=None)
        prop = PropertyMenu._record_to_prop(record)
        assert prop.unit_mix is not None
        assert prop.unit_mix.floors == FLOORS

    def test_unitless_non_retail_office_keeps_floors_too(self):
        """The floors-only UnitMix applies to every unit-less type, not just
        Retail-Office — all property data must be kept, floors included."""
        record = _stored_record(property_type="Mixed-Use")
        prop = PropertyMenu._record_to_prop(record)
        assert prop.unit_mix is not None
        assert prop.unit_mix.total_units == 0
        assert prop.unit_mix.floors == FLOORS


# ── Layer 2: RentResolver ─────────────────────────────────────────────────────

class TestResolverRetailOfficeFloors:

    def _prop(self, unit_mix):
        return PropertyInput(
            address="379 George St N, Peterborough, ON",
            mls_number="X12846518", status="active",
            original_price=900_000, asking_price=900_000,
            total_sq_ft=SQ_FT, property_taxes=6_000,
            down_payment_pct=0.20, interest_rate=0.055,
            term_years=25, hold_years=30,
            city="Peterborough", province="ON",
            property_type="Retail-Office",
            unit_mix=unit_mix,
        )

    def test_multi_floor_rent_uses_all_floors(self):
        """3 floors → ground Retail + 2 upper Office floors, not Retail across
        the whole building at floors=1."""
        rent, breakdown = _resolver().resolve(self._prop(UnitMix(floors=FLOORS)))
        assert rent == pytest.approx(EXPECTED_3F_RENT)
        assert any("Upper 2 floors Office" in line for line in breakdown)

    def test_missing_unit_mix_defaults_to_one_floor(self):
        """Without a UnitMix the resolver assumes 1 floor (no phantom
        PropertyInput.floors attribute to fall back on)."""
        rent, _ = _resolver().resolve(self._prop(None))
        assert rent == pytest.approx(RETAIL_RATE * SQ_FT)


# ── Layer 3: End-to-end re-analysis ───────────────────────────────────────────

class TestEndToEndFloorPreservation:

    def _analyze(self, record):
        prop     = PropertyMenu._record_to_prop(record)
        analyzer = CommercialPropertyAnalyzer(prop, _resolver())
        return analyzer.to_record(existing=record)

    def test_reanalysis_preserves_floors(self):
        """The original bug: re-analysis wrote floors=1 back to the record."""
        out = self._analyze(_stored_record())
        assert out["floors"] == FLOORS
        assert out["unit_mix"]["floors"] == FLOORS

    def test_reanalysis_is_idempotent_on_floors(self):
        first  = self._analyze(_stored_record())
        second = self._analyze(first)
        assert second["floors"] == FLOORS
        assert second["unit_mix"]["floors"] == FLOORS

    def test_saved_commercial_rent_still_short_circuits(self):
        """Floors-only UnitMix must not break the rent short-circuit: a manually
        entered commercial_rent (rent_manually_entered=True) is returned as-is."""
        out = self._analyze(_stored_record())
        assert out["annual_rent"] == pytest.approx(62_369.0)

    def test_cleared_rent_recomputes_with_all_floors(self):
        """The rent-corruption case: with no saved rent, re-analysis must price
        upper floors at the Office rate, not the whole building as ground-floor
        Retail (e.g. $183k→$225k inflation at floors=1)."""
        record = _stored_record(annual_rent=None, commercial_rent=0, residential_rent=0)
        out = self._analyze(record)
        assert out["annual_rent"] == pytest.approx(EXPECTED_3F_RENT)

    def test_to_record_falls_back_to_existing_floors(self):
        """Safety net: even if a future path builds a PropertyInput without a
        UnitMix, to_record() must preserve the stored floors, never write 1."""
        record = _stored_record()
        prop = PropertyMenu._record_to_prop(record)
        prop.unit_mix = None
        analyzer = CommercialPropertyAnalyzer(prop, _resolver())
        out = analyzer.to_record(existing=record)
        assert out["floors"] == FLOORS
        assert out["unit_mix"]["floors"] == FLOORS


# ── Layer 4: CSV import ───────────────────────────────────────────────────────

class _CsvImporter(CsvHandlerMixin):
    THIN_DIVIDER = ""

    def __init__(self):
        self._store    = MagicMock()
        self._resolver = _resolver()


class TestCsvImportFloors:

    def _import_row(self, tmp_path, row):
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

    def test_unitless_retail_office_row_keeps_floors(self, tmp_path):
        """First-import floor loss: a unit-less Retail-Office row with rent
        provided must persist its floors."""
        record = self._import_row(tmp_path, {
            "address":         "379 George St N, Peterborough, ON",
            "mls_number":      "X12846518",
            "original_price":  "900000",
            "property_type":   "Retail-Office",
            "commercial_rent": "62369",
            "floors":          str(FLOORS),
            "total_sq_ft":     str(SQ_FT),
        })
        assert record["floors"] == FLOORS
        assert record["unit_mix"]["floors"] == FLOORS

    def test_unitless_retail_office_row_without_rent_computes_all_floors(self, tmp_path):
        """No rent in the row → market resolution must use every floor."""
        record = self._import_row(tmp_path, {
            "address":        "379 George St N, Peterborough, ON",
            "mls_number":     "X12846518",
            "original_price": "900000",
            "property_type":  "Retail-Office",
            "floors":         str(FLOORS),
            "total_sq_ft":    str(SQ_FT),
        })
        assert record["floors"] == FLOORS
        assert record["annual_rent"] == pytest.approx(EXPECTED_3F_RENT)
