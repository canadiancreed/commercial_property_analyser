import pytest
from models.property_input import PropertyInput
from analysis.metrics.property_types import HotelMetrics, IndustrialMetrics


def _make_prop(**kwargs):
    defaults = dict(
        original_price=2_000_000, asking_price=2_000_000,
        total_sq_ft=10_000, property_taxes=30_000,
        down_payment_pct=0.30, interest_rate=0.06,
        term_years=25, hold_years=10,
        expense_ratio=0.55,
    )
    defaults.update(kwargs)
    return PropertyInput(**defaults)


# ── HotelMetrics ─────────────────────────────────────────────────────────────

class TestHotelMetrics:
    def _hotel_prop(self, rooms=50, adr=150.0, occ=0.70):
        return _make_prop(
            property_type="Hotel",
            hotel_rooms=rooms, hotel_adr=adr, hotel_occupancy=occ,
        )

    def _annual_rev(self, rooms=50, adr=150.0, occ=0.70):
        return rooms * adr * occ * 365

    def test_revpar(self):
        prop = self._hotel_prop(adr=150.0, occ=0.70)
        m = HotelMetrics(prop, self._annual_rev())
        assert m.revpar == pytest.approx(150.0 * 0.70)

    def test_nrevpar_range(self):
        prop = self._hotel_prop(adr=150.0, occ=0.70)
        m = HotelMetrics(prop, self._annual_rev())
        assert m.nrevpar_low  == pytest.approx(m.revpar * (1 - HotelMetrics.NREVPAR_DIST_COST_LOW))
        assert m.nrevpar_mid  == pytest.approx(m.revpar * (1 - HotelMetrics.NREVPAR_DIST_COST_MID))
        assert m.nrevpar_high == pytest.approx(m.revpar * (1 - HotelMetrics.NREVPAR_DIST_COST_HIGH))
        assert m.nrevpar_high < m.nrevpar_mid < m.nrevpar_low

    def test_gop_margin(self):
        prop = self._hotel_prop()
        rev = self._annual_rev()
        m = HotelMetrics(prop, rev)
        # gop_margin = (1 - expense_ratio) * 100 = 45%
        assert m.gop_margin == pytest.approx(45.0)

    def test_gop_amount(self):
        prop = self._hotel_prop()
        rev = self._annual_rev()
        m = HotelMetrics(prop, rev)
        assert m.gop_amount == pytest.approx(rev * 0.45)

    def test_ffe_reserve(self):
        prop = self._hotel_prop()
        rev = self._annual_rev()
        m = HotelMetrics(prop, rev)
        assert m.ffe_reserve == pytest.approx(rev * 0.04)

    def test_rev_per_room(self):
        prop = self._hotel_prop(rooms=50)
        rev = self._annual_rev(rooms=50)
        m = HotelMetrics(prop, rev)
        assert m.rev_per_room == pytest.approx(rev / 50)

    def test_cpor(self):
        prop = self._hotel_prop(rooms=50, adr=150.0, occ=0.70)
        rev = self._annual_rev()
        m = HotelMetrics(prop, rev)
        occupied_nights = 50 * 0.70 * 365
        expected = (rev * 0.55) / occupied_nights
        assert m.cpor == pytest.approx(expected, rel=0.01)

    def test_zero_rooms(self):
        prop = _make_prop(hotel_rooms=0, hotel_adr=0, hotel_occupancy=0)
        m = HotelMetrics(prop, 500_000)
        assert m.rev_per_room == 0
        assert m.cpor == 0

    def test_revpar_grade_excellent(self):
        prop = self._hotel_prop(adr=200.0, occ=0.75)  # revpar = 150
        m = HotelMetrics(prop, self._annual_rev(adr=200.0, occ=0.75))
        assert m._revpar_grade() == "EXCELLENT"

    def test_revpar_grade_good(self):
        prop = self._hotel_prop(adr=120.0, occ=0.70)  # revpar = 84
        m = HotelMetrics(prop, self._annual_rev(adr=120.0, occ=0.70))
        assert m._revpar_grade() == "GOOD"

    def test_revpar_grade_fair(self):
        prop = self._hotel_prop(adr=80.0, occ=0.70)  # revpar = 56
        m = HotelMetrics(prop, self._annual_rev(adr=80.0, occ=0.70))
        assert m._revpar_grade() == "FAIR"

    def test_revpar_grade_poor(self):
        prop = self._hotel_prop(adr=50.0, occ=0.60)  # revpar = 30
        m = HotelMetrics(prop, self._annual_rev(adr=50.0, occ=0.60))
        assert m._revpar_grade() == "POOR"

    def test_occupancy_grade_good(self):
        prop = self._hotel_prop(occ=0.75)
        m = HotelMetrics(prop, self._annual_rev(occ=0.75))
        assert m._occ_grade() == "GOOD"

    def test_occupancy_grade_fair(self):
        prop = self._hotel_prop(occ=0.60)
        m = HotelMetrics(prop, self._annual_rev(occ=0.60))
        assert m._occ_grade() == "FAIR"

    def test_occupancy_grade_poor(self):
        prop = self._hotel_prop(occ=0.40)
        m = HotelMetrics(prop, self._annual_rev(occ=0.40))
        assert m._occ_grade() == "POOR"

    def test_gop_grade_good(self):
        prop = _make_prop(hotel_rooms=50, hotel_adr=150.0, hotel_occupancy=0.70,
                          expense_ratio=0.60)  # gop = 40% → GOOD
        m = HotelMetrics(prop, self._annual_rev())
        assert m._gop_grade() == "GOOD"

    def test_gop_grade_poor(self):
        prop = _make_prop(hotel_rooms=50, hotel_adr=150.0, hotel_occupancy=0.70,
                          expense_ratio=0.80)  # gop = 20% → POOR
        m = HotelMetrics(prop, self._annual_rev())
        assert m._gop_grade() == "POOR"

    def test_rows_has_revpar(self):
        prop = self._hotel_prop()
        m = HotelMetrics(prop, self._annual_rev())
        metrics = {r.metric for r in m.rows()}
        assert "RevPAR" in metrics

    def test_rows_has_gop(self):
        prop = self._hotel_prop()
        m = HotelMetrics(prop, self._annual_rev())
        metrics = {r.metric for r in m.rows()}
        assert "GOP Margin" in metrics


# ── IndustrialMetrics ─────────────────────────────────────────────────────────

class TestIndustrialMetrics:
    def _ind_prop(self, **kwargs):
        defaults = dict(
            property_type="Industrial",
            total_sq_ft=10_000,
            ind_warehouse_sqft=8_000,
            ind_office_sqft=1_000,
            ind_yard_sqft=2_000,
            ind_dock_doors=2,
            ind_drive_in_doors=1,
            ind_clear_height_ft=24.0,
        )
        defaults.update(kwargs)
        return _make_prop(**defaults)

    def test_warehouse_income(self):
        prop = self._ind_prop()
        m = IndustrialMetrics(prop, base_industrial_rate=12.0)
        # height 24 > 18 → premium = (24-18)*0.02 = 0.12 → rate = 12 * 1.12 = 13.44
        expected_wh_rate = 12.0 * (1 + (24 - 18) * 0.02)
        assert m.warehouse_rate == pytest.approx(expected_wh_rate)
        assert m.warehouse_income == pytest.approx(8_000 * expected_wh_rate)

    def test_no_height_premium(self):
        prop = self._ind_prop(ind_clear_height_ft=15.0)
        m = IndustrialMetrics(prop, 12.0)
        assert m.warehouse_rate == pytest.approx(12.0)

    def test_office_rate_default(self):
        prop = self._ind_prop(ind_office_sqft=1000)
        m = IndustrialMetrics(prop, 12.0)
        expected_rate = m.warehouse_rate * IndustrialMetrics.OFFICE_PREMIUM_RATIO
        assert m.office_rate == pytest.approx(expected_rate)

    def test_office_rate_explicit(self):
        prop = self._ind_prop(ind_office_sqft=1000)
        prop2 = _make_prop(
            property_type="Industrial", total_sq_ft=10_000,
            ind_warehouse_sqft=8_000, ind_office_sqft=1_000,
            ind_yard_sqft=2_000, ind_dock_doors=2, ind_drive_in_doors=1,
            ind_clear_height_ft=24.0, ind_office_rate=20.0,
        )
        m = IndustrialMetrics(prop2, 12.0)
        assert m.office_rate == pytest.approx(20.0)

    def test_yard_rate_default(self):
        prop = self._ind_prop()
        m = IndustrialMetrics(prop, 12.0)
        expected = m.warehouse_rate * IndustrialMetrics.YARD_RATE_RATIO
        assert m.yard_rate == pytest.approx(expected)

    def test_total_income(self):
        prop = self._ind_prop()
        m = IndustrialMetrics(prop, 12.0)
        expected = m.warehouse_income + m.office_income + m.yard_income
        assert m.total_income == pytest.approx(expected)

    def test_blended_rate(self):
        prop = self._ind_prop()
        m = IndustrialMetrics(prop, 12.0)
        covered = m.warehouse_sqft + m.office_sqft
        expected = (m.warehouse_income + m.office_income) / covered
        assert m.blended_rate == pytest.approx(expected)

    def test_height_grade_excellent(self):
        prop = self._ind_prop(ind_clear_height_ft=30.0)
        m = IndustrialMetrics(prop, 12.0)
        assert m._height_grade() == "EXCELLENT"

    def test_height_grade_good(self):
        prop = self._ind_prop(ind_clear_height_ft=24.0)
        m = IndustrialMetrics(prop, 12.0)
        assert m._height_grade() == "GOOD"

    def test_height_grade_fair(self):
        prop = self._ind_prop(ind_clear_height_ft=18.0)
        m = IndustrialMetrics(prop, 12.0)
        assert m._height_grade() == "FAIR"

    def test_height_grade_poor(self):
        prop = self._ind_prop(ind_clear_height_ft=12.0)
        m = IndustrialMetrics(prop, 12.0)
        assert m._height_grade() == "POOR"

    def test_height_grade_zero(self):
        prop = self._ind_prop(ind_clear_height_ft=0)
        m = IndustrialMetrics(prop, 12.0)
        assert m._height_grade() == ""

    def test_dock_door_grade(self):
        prop = self._ind_prop(ind_dock_doors=2)
        m = IndustrialMetrics(prop, 12.0)
        dock_rows = [r for r in m.rows() if r.metric == "Dock Doors"]
        assert dock_rows[0].grade == "GOOD"

    def test_single_dock_door_fair(self):
        prop = self._ind_prop(ind_dock_doors=1)
        m = IndustrialMetrics(prop, 12.0)
        dock_rows = [r for r in m.rows() if r.metric == "Dock Doors"]
        assert dock_rows[0].grade == "FAIR"

    def test_rows_has_total(self):
        prop = self._ind_prop()
        m = IndustrialMetrics(prop, 12.0)
        metrics = {r.metric for r in m.rows()}
        assert "Total Industrial Rev" in metrics

    def test_warehouse_sqft_fallback(self):
        # If ind_warehouse_sqft not provided, fallback = total - office
        prop = _make_prop(
            property_type="Industrial", total_sq_ft=10_000,
            ind_warehouse_sqft=0, ind_office_sqft=2_000,
            ind_yard_sqft=0, ind_clear_height_ft=0,
        )
        m = IndustrialMetrics(prop, 12.0)
        assert m.warehouse_sqft == pytest.approx(8_000)

    # ── rows() branch coverage ────────────────────────────────────────────────

    def test_rows_no_clear_height(self):
        """clear_height=0 → if self.clear_height: is False — Clear Height row omitted."""
        prop = _make_prop(
            property_type="Industrial", total_sq_ft=5_000,
            ind_warehouse_sqft=5_000, ind_office_sqft=0,
            ind_yard_sqft=0, ind_dock_doors=0,
            ind_drive_in_doors=0, ind_clear_height_ft=0,
        )
        m = IndustrialMetrics(prop, 12.0)
        metrics = {r.metric for r in m.rows()}
        assert "Clear Height" not in metrics
        assert "Total Industrial Rev" in metrics

    def test_rows_no_dock_doors(self):
        """dock_doors=0 → Dock Doors row omitted."""
        prop = _make_prop(
            property_type="Industrial", total_sq_ft=5_000,
            ind_warehouse_sqft=5_000, ind_office_sqft=0,
            ind_yard_sqft=0, ind_dock_doors=0,
            ind_drive_in_doors=0, ind_clear_height_ft=0,
        )
        m = IndustrialMetrics(prop, 12.0)
        metrics = {r.metric for r in m.rows()}
        assert "Dock Doors" not in metrics

    def test_rows_no_drive_in_doors(self):
        """drive_in_doors=0 → Drive-In Doors row omitted."""
        prop = _make_prop(
            property_type="Industrial", total_sq_ft=5_000,
            ind_warehouse_sqft=5_000, ind_office_sqft=0,
            ind_yard_sqft=0, ind_dock_doors=1,
            ind_drive_in_doors=0, ind_clear_height_ft=0,
        )
        m = IndustrialMetrics(prop, 12.0)
        metrics = {r.metric for r in m.rows()}
        assert "Drive-In Doors" not in metrics

    def test_rows_no_office_sqft(self):
        """office_sqft=0 → Office Component rows omitted."""
        prop = _make_prop(
            property_type="Industrial", total_sq_ft=5_000,
            ind_warehouse_sqft=5_000, ind_office_sqft=0,
            ind_yard_sqft=0, ind_dock_doors=0,
            ind_drive_in_doors=0, ind_clear_height_ft=0,
        )
        m = IndustrialMetrics(prop, 12.0)
        metrics = {r.metric for r in m.rows()}
        assert "Office Component" not in metrics
        assert "Office Income" not in metrics

    def test_rows_no_yard_sqft(self):
        """yard_sqft=0 → Yard/Storage rows omitted."""
        prop = _make_prop(
            property_type="Industrial", total_sq_ft=5_000,
            ind_warehouse_sqft=5_000, ind_office_sqft=0,
            ind_yard_sqft=0, ind_dock_doors=0,
            ind_drive_in_doors=0, ind_clear_height_ft=0,
        )
        m = IndustrialMetrics(prop, 12.0)
        metrics = {r.metric for r in m.rows()}
        assert "Yard/Storage" not in metrics

    def test_rows_no_blended_rate(self):
        """covered_sqft=0 → blended_rate=0 → Blended Rate row omitted."""
        prop = _make_prop(
            property_type="Industrial", total_sq_ft=0,
            ind_warehouse_sqft=0, ind_office_sqft=0,
            ind_yard_sqft=0, ind_dock_doors=0,
            ind_drive_in_doors=0, ind_clear_height_ft=0,
        )
        m = IndustrialMetrics(prop, 12.0)
        assert m.blended_rate == 0
        metrics = {r.metric for r in m.rows()}
        assert "Blended Rate" not in metrics


class TestHotelMetricsRowsBranches:
    """Covers the if-branch false paths in HotelMetrics.rows()."""

    def _zero_hotel(self):
        return _make_prop(
            property_type="Hotel",
            hotel_rooms=0, hotel_adr=0.0, hotel_occupancy=0.0,
        )

    def test_rows_zero_rooms_omits_hotel_rooms_row(self):
        m = HotelMetrics(self._zero_hotel(), 500_000)
        metrics = {r.metric for r in m.rows()}
        assert "Hotel Rooms" not in metrics

    def test_rows_zero_adr_omits_adr_row(self):
        m = HotelMetrics(self._zero_hotel(), 500_000)
        metrics = {r.metric for r in m.rows()}
        assert "ADR" not in metrics

    def test_rows_zero_occupancy_omits_occupancy_row(self):
        m = HotelMetrics(self._zero_hotel(), 500_000)
        metrics = {r.metric for r in m.rows()}
        assert "Occupancy Rate" not in metrics

    def test_rows_zero_revpar_omits_revpar_row(self):
        m = HotelMetrics(self._zero_hotel(), 500_000)
        metrics = {r.metric for r in m.rows()}
        assert "RevPAR" not in metrics
        assert "NRevPAR" not in metrics

    def test_rows_zero_rooms_omits_rev_per_room(self):
        m = HotelMetrics(self._zero_hotel(), 500_000)
        metrics = {r.metric for r in m.rows()}
        assert "Rev/Room/Yr" not in metrics

    def test_rows_zero_cpor_omits_cpor(self):
        m = HotelMetrics(self._zero_hotel(), 500_000)
        metrics = {r.metric for r in m.rows()}
        assert "CPOR" not in metrics

    def test_rows_zero_still_has_gop_and_ffe(self):
        """GOP Margin, GOP Amount, FF&E Reserve always appear regardless of zeros."""
        m = HotelMetrics(self._zero_hotel(), 500_000)
        metrics = {r.metric for r in m.rows()}
        assert "GOP Margin" in metrics
        assert "GOP Amount" in metrics
        assert "FF&E Reserve" in metrics

    def test_gop_grade_fair(self):
        """gop_margin between 25-35 → FAIR."""
        # expense_ratio=0.70 → gop_margin = 30%
        prop = _make_prop(hotel_rooms=50, hotel_adr=150.0, hotel_occupancy=0.70,
                          expense_ratio=0.70)
        m = HotelMetrics(prop, 50 * 150.0 * 0.70 * 365)
        assert m._gop_grade() == "FAIR"

    def test_gop_grade_good(self):
        """gop_margin >= 35 → GOOD."""
        # expense_ratio=0.60 → gop_margin = 40%
        prop = _make_prop(hotel_rooms=50, hotel_adr=150.0, hotel_occupancy=0.70,
                          expense_ratio=0.60)
        m = HotelMetrics(prop, 50 * 150.0 * 0.70 * 365)
        assert m._gop_grade() == "GOOD"


# ── Issue #11: NRevPAR OTA discount must be configurable, not hardcoded 15% ───

class TestNRevPARConfigurable:

    @staticmethod
    def _hotel_prop():
        return _make_prop(
            property_type="Hotel",
            hotel_rooms=50, hotel_adr=150.0, hotel_occupancy=0.70,
            expense_ratio=0.65,
        )

    def test_nrevpar_range_ordering(self):
        prop = self._hotel_prop()
        m    = HotelMetrics(prop, 500_000)
        assert m.nrevpar_high < m.nrevpar_mid < m.nrevpar_low

    def test_nrevpar_range_uses_constants(self):
        prop = self._hotel_prop()
        m    = HotelMetrics(prop, 500_000)
        assert m.nrevpar_low  == pytest.approx(m.revpar * (1 - HotelMetrics.NREVPAR_DIST_COST_LOW),  rel=1e-6)
        assert m.nrevpar_mid  == pytest.approx(m.revpar * (1 - HotelMetrics.NREVPAR_DIST_COST_MID),  rel=1e-6)
        assert m.nrevpar_high == pytest.approx(m.revpar * (1 - HotelMetrics.NREVPAR_DIST_COST_HIGH), rel=1e-6)
