import pytest
from models.property_input import UnitMix, PropertyInput
from models.report_row import ReportRow


class TestUnitMix:
    def test_total_units_zero(self):
        mix = UnitMix()
        assert mix.total_units == 0

    def test_total_units_sum(self):
        mix = UnitMix(bachelor=1, one_br=2, two_br=3, three_br=1, four_br=0, unknown=1)
        assert mix.total_units == 8

    def test_unit_types_returns_six_tuples(self):
        mix = UnitMix(one_br=3, two_br=2)
        types = mix.unit_types()
        assert len(types) == 6
        keys = [t[0] for t in types]
        assert "bachelor" in keys
        assert "four_br" in keys

    def test_unit_types_count_and_override(self):
        mix = UnitMix(one_br=5, one_br_rent=900.0)
        types = dict((k, (c, r)) for k, c, r in mix.unit_types())
        assert types["one_br"] == (5, 900.0)
        assert types["bachelor"] == (0, None)

    def test_floors_default(self):
        assert UnitMix().floors == 1

    def test_floors_explicit(self):
        assert UnitMix(floors=4).floors == 4


class TestPropertyInput:
    def _make(self, **kwargs):
        defaults = dict(
            original_price=500_000, asking_price=480_000,
            total_sq_ft=5000, property_taxes=7500,
            down_payment_pct=0.25, interest_rate=0.055,
            term_years=25, hold_years=10,
        )
        defaults.update(kwargs)
        return PropertyInput(**defaults)

    def test_basic_creation(self):
        p = self._make()
        assert p.asking_price == 480_000
        assert p.down_payment_pct == 0.25

    def test_defaults(self):
        p = self._make()
        assert p.status == "active"
        # no property_type → __post_init__ falls back to 0.40
        assert p.expense_ratio == pytest.approx(0.40)
        assert p.lease_type == "Normal"
        assert p.construction_cost == 0.0
        assert p.hotel_rooms == 0

    def test_optional_fields_none(self):
        p = self._make()
        assert p.annual_rent is None
        assert p.city is None
        assert p.unit_mix is None

    def test_annual_rent_set(self):
        p = self._make(annual_rent=60_000)
        assert p.annual_rent == 60_000

    def test_unit_mix_attached(self):
        mix = UnitMix(two_br=4)
        p = self._make(unit_mix=mix)
        assert p.unit_mix.total_units == 4

    def test_hotel_fields(self):
        p = self._make(hotel_rooms=30, hotel_adr=120.0, hotel_occupancy=0.70)
        assert p.hotel_rooms == 30
        assert p.hotel_adr == 120.0
        assert p.hotel_occupancy == 0.70

    def test_industrial_fields(self):
        p = self._make(
            ind_warehouse_sqft=8000, ind_office_sqft=1000,
            ind_dock_doors=2, ind_clear_height_ft=24
        )
        assert p.ind_warehouse_sqft == 8000
        assert p.ind_dock_doors == 2


# ── Expense ratio defaults (bug #6 fix) ──────────────────────────────────────

class TestExpenseRatioDefaults:

    def _prop(self, **kwargs):
        base = dict(
            original_price=500_000, asking_price=500_000,
            total_sq_ft=5_000, property_taxes=8_000,
            down_payment_pct=0.25, interest_rate=0.055, term_years=25,
        )
        base.update(kwargs)
        return PropertyInput(**base)

    # ── per-type defaults come from constants ─────────────────────────────────

    def test_hotel_defaults_above_60pct(self):
        """Hotel must default to ≥ 0.60 (STR/CoStar 2023: full-service ~63%)."""
        assert self._prop(property_type="Hotel").expense_ratio >= 0.60

    def test_office_default(self):
        from models.constants import EXPENSE_RATIO_DEFAULTS
        assert self._prop(property_type="Office").expense_ratio == pytest.approx(
            EXPENSE_RATIO_DEFAULTS["office"]
        )

    def test_retail_default(self):
        from models.constants import EXPENSE_RATIO_DEFAULTS
        assert self._prop(property_type="Retail").expense_ratio == pytest.approx(
            EXPENSE_RATIO_DEFAULTS["retail"]
        )

    def test_industrial_default(self):
        from models.constants import EXPENSE_RATIO_DEFAULTS
        assert self._prop(property_type="Industrial").expense_ratio == pytest.approx(
            EXPENSE_RATIO_DEFAULTS["industrial"]
        )

    def test_multifamily_default(self):
        from models.constants import EXPENSE_RATIO_DEFAULTS
        assert self._prop(property_type="Multi-Family").expense_ratio == pytest.approx(
            EXPENSE_RATIO_DEFAULTS["multi-family"]
        )

    def test_residential_default(self):
        from models.constants import EXPENSE_RATIO_DEFAULTS
        assert self._prop(property_type="Residential").expense_ratio == pytest.approx(
            EXPENSE_RATIO_DEFAULTS["residential"]
        )

    def test_mixed_use_default(self):
        from models.constants import EXPENSE_RATIO_DEFAULTS
        assert self._prop(property_type="Mixed-Use").expense_ratio == pytest.approx(
            EXPENSE_RATIO_DEFAULTS["mixed-use"]
        )

    def test_unknown_type_falls_back_to_040(self):
        """An unrecognised property type must fall back to 0.40."""
        assert self._prop(property_type="Warehouse").expense_ratio == pytest.approx(0.40)

    def test_no_property_type_falls_back_to_040(self):
        """No property_type at all must fall back to 0.40."""
        assert self._prop().expense_ratio == pytest.approx(0.40)

    # ── NNN lease overrides property type ────────────────────────────────────

    def test_nnn_lease_overrides_hotel_default(self):
        """NNN lease must win over property-type default, even for hotels."""
        from models.constants import EXPENSE_RATIO_DEFAULTS
        prop = self._prop(property_type="Hotel", lease_type="NNN")
        assert prop.expense_ratio == pytest.approx(EXPENSE_RATIO_DEFAULTS["nnn"])

    def test_nnn_lease_overrides_office_default(self):
        from models.constants import EXPENSE_RATIO_DEFAULTS
        prop = self._prop(property_type="Office", lease_type="NNN")
        assert prop.expense_ratio == pytest.approx(EXPENSE_RATIO_DEFAULTS["nnn"])

    # ── explicit value is never overridden ────────────────────────────────────

    def test_explicit_value_not_overridden_for_hotel(self):
        """An explicitly supplied expense_ratio must never be replaced by a type default."""
        prop = self._prop(property_type="Hotel", expense_ratio=0.55)
        assert prop.expense_ratio == pytest.approx(0.55)

    def test_explicit_value_not_overridden_for_nnn(self):
        prop = self._prop(lease_type="NNN", expense_ratio=0.12)
        assert prop.expense_ratio == pytest.approx(0.12)

    def test_explicit_zero_not_overridden(self):
        """expense_ratio=0.0 is a valid explicit value and must not be replaced."""
        prop = self._prop(expense_ratio=0.0)
        assert prop.expense_ratio == pytest.approx(0.0)


class TestReportRow:
    def test_to_dict(self):
        row = ReportRow("Cap Rate", "7.50%", "GOOD")
        d = row.to_dict()
        assert d == {"metric": "Cap Rate", "value": "7.50%", "grade": "GOOD"}

    def test_str_format(self):
        row = ReportRow("Cap Rate", "7.50%", "GOOD")
        s = str(row)
        assert "Cap Rate" in s
        assert "7.50%" in s
        assert "GOOD" in s

    def test_str_pads_metric(self):
        row = ReportRow("X", "Y", "Z")
        s = str(row)
        # metric field padded to 25 chars
        assert s.startswith("X" + " " * 24)

    def test_grade_empty(self):
        row = ReportRow("Note", "some text", "")
        assert row.to_dict()["grade"] == ""
