import pytest
from unittest.mock import MagicMock, patch
from models.property_input import PropertyInput, UnitMix
from analysis.rent_resolver import RentResolver


# ── Helpers ───────────────────────────────────────────────────────────────────

def _prop(**kwargs):
    defaults = dict(
        original_price=500_000, asking_price=500_000,
        total_sq_ft=5000, property_taxes=8000,
        down_payment_pct=0.25, interest_rate=0.055,
        term_years=25, hold_years=10,
    )
    defaults.update(kwargs)
    return PropertyInput(**defaults)


def _resolver(comm_rates=None, res_rates=None, store=None):
    comm = MagicMock()
    comm.get_rent_per_sqft.side_effect = lambda city, prov, ptype: (
        comm_rates.get(ptype) if comm_rates else None
    )
    res = MagicMock()
    res.get_rates.return_value = res_rates
    return RentResolver(comm, res, store)


# ── Mode 1: Direct annual_rent ─────────────────────────────────────────────────

class TestDirectRent:
    def test_returns_provided_rent(self):
        r = _resolver()
        prop = _prop(annual_rent=60_000)
        rent, breakdown = r.resolve(prop)
        assert rent == 60_000

    def test_breakdown_message(self):
        r = _resolver()
        prop = _prop(annual_rent=60_000)
        _, breakdown = r.resolve(prop)
        assert "directly" in breakdown[0].lower()

    def test_comm_rent_attribute_set(self):
        r = _resolver()
        prop = _prop(annual_rent=60_000)
        r.resolve(prop)
        assert r._comm_rent == 60_000
        assert r._res_rent == 0.0


# ── Mode 2: Commercial lookup ─────────────────────────────────────────────────

class TestCommercialMode:
    def test_basic_commercial(self):
        r = _resolver(comm_rates={"Retail": 30.0})
        prop = _prop(city="Ottawa", province="ON", property_type="Retail",
                     total_sq_ft=5000)
        rent, _ = r.resolve(prop)
        assert rent == pytest.approx(150_000)

    def test_missing_city_raises(self):
        r = _resolver(comm_rates=None)
        prop = _prop(city="Unknown", province="ON", property_type="Retail",
                     total_sq_ft=5000)
        with pytest.raises(ValueError, match="No commercial rate"):
            r.resolve(prop)

    def test_missing_city_province_raises(self):
        r = _resolver(comm_rates={"Retail": 30.0})
        prop = _prop(city=None, province=None, property_type="Retail")
        with pytest.raises(ValueError, match="city and province"):
            r.resolve(prop)

    def test_breakdown_contains_rate_info(self):
        r = _resolver(comm_rates={"Office": 20.0})
        prop = _prop(city="Ottawa", province="ON", property_type="Office",
                     total_sq_ft=4000)
        _, breakdown = r.resolve(prop)
        assert any("20" in line or "Office" in line for line in breakdown)

    def test_logs_missing_when_rate_absent(self):
        store = MagicMock()
        r = _resolver(comm_rates=None, store=store)
        prop = _prop(city="Barrie", province="ON", property_type="Office",
                     total_sq_ft=3000)
        with pytest.raises(ValueError):
            r.resolve(prop)
        store.log_missing_city.assert_called()


# ── Mode 3: Residential unit_mix ──────────────────────────────────────────────

class TestResidentialMode:
    def _res_prop(self, mix, rates=None, **kwargs):
        r = _resolver(res_rates=rates or {"one_br": 1200, "two_br": 1600, "unknown": 1400})
        prop = _prop(city="Ottawa", province="ON", unit_mix=mix, **kwargs)
        return r, prop

    def test_basic_unit_mix(self):
        mix = UnitMix(one_br=2, two_br=1)
        r, prop = self._res_prop(mix)
        rent, _ = r.resolve(prop)
        # (1200*2 + 1600*1) * 12
        assert rent == pytest.approx((1200*2 + 1600) * 12)

    def test_override_rent_used(self):
        mix = UnitMix(one_br=2, one_br_rent=1500.0)
        r, prop = self._res_prop(mix)
        rent, _ = r.resolve(prop)
        assert rent == pytest.approx(1500 * 2 * 12)

    def test_no_city_rates_uses_override(self):
        mix = UnitMix(one_br=3, one_br_rent=1000.0)
        r = _resolver(res_rates=None)
        prop = _prop(city="Timbuktu", province="ON", unit_mix=mix)
        rent, breakdown = r.resolve(prop)
        assert rent == pytest.approx(1000 * 3 * 12)
        assert any("specified" in line for line in breakdown)

    def test_unknown_unit_uses_avg(self):
        mix = UnitMix(unknown=4)
        rates = {"bachelor": 800, "one_br": 1200, "two_br": 1600, "unknown": 1200}
        r = _resolver(res_rates=rates)
        prop = _prop(city="Ottawa", province="ON", unit_mix=mix)
        rent, _ = r.resolve(prop)
        assert rent == pytest.approx(1200 * 4 * 12)

    def test_no_rates_no_override_skipped(self):
        mix = UnitMix(two_br=3)
        r = _resolver(res_rates=None)
        prop = _prop(city="Unknown", province="ON", unit_mix=mix)
        rent, breakdown = r.resolve(prop)
        assert rent == 0.0
        assert any("no rate" in line for line in breakdown)


# ── Mixed-use ─────────────────────────────────────────────────────────────────

class TestMixedUseMode:
    def test_mixed_combines_comm_and_res(self):
        comm = MagicMock()
        comm.get_rent_per_sqft.return_value = 30.0
        res = MagicMock()
        res.get_rates.return_value = {"one_br": 1200, "two_br": 1600, "unknown": 1400}
        r = RentResolver(comm, res)
        # Mixed-use: 1 comm floor + 2 res units
        mix = UnitMix(one_br=2, floors=2)
        prop = _prop(city="Ottawa", province="ON", property_type="Mixed-Use",
                     unit_mix=mix, total_sq_ft=4000)
        rent, _ = r.resolve(prop)
        # comm floor: 4000/2 sqft * 30 = 60000
        # res: 1200*2*12 = 28800
        assert rent == pytest.approx(60_000 + 28_800)

    def test_stale_zero_residential_with_units_recalculates(self):
        """residential_rent=0.0 stored from before city data existed, but unit_mix has units.
        Must NOT short-circuit — residential component must be recalculated from unit_mix."""
        comm = MagicMock()
        comm.get_rent_per_sqft.return_value = 15.0
        res = MagicMock()
        res.get_rates.return_value = {"one_br": 1550, "unknown": 2050}
        r = RentResolver(comm, res)
        mix = UnitMix(one_br=2, floors=2)
        prop = _prop(
            city="Midland", province="ON", property_type="Mixed-Use",
            total_sq_ft=2725, unit_mix=mix,
            commercial_rent=20437.5,
            residential_rent=0.0,   # stale stored zero — must not short-circuit
        )
        rent, _ = r.resolve(prop)
        # comm: 2725/2 * 15 = 20437.5, res: 2 * 1550 * 12 = 37200
        assert rent == pytest.approx(20437.5 + 37_200)
        assert r._res_rent == pytest.approx(37_200)

    def test_stale_none_residential_with_units_recalculates(self):
        """residential_rent=None (as _record_to_prop converts 0.0→None via 'or None'),
        commercial_rent stored, unit_mix has units — must recalculate residential."""
        comm = MagicMock()
        comm.get_rent_per_sqft.return_value = 15.0
        res = MagicMock()
        res.get_rates.return_value = {"one_br": 1550, "unknown": 2050}
        r = RentResolver(comm, res)
        mix = UnitMix(one_br=2, floors=2)
        prop = _prop(
            city="Midland", province="ON", property_type="Mixed-Use",
            total_sq_ft=2725, unit_mix=mix,
            commercial_rent=20437.5,
            residential_rent=None,  # what _record_to_prop produces from stored 0.0
        )
        rent, _ = r.resolve(prop)
        assert rent == pytest.approx(20437.5 + 37_200)
        assert r._res_rent == pytest.approx(37_200)

    def test_missing_commercial_rate_in_mixed_skips(self):
        comm = MagicMock()
        comm.get_rent_per_sqft.return_value = None
        res = MagicMock()
        res.get_rates.return_value = {"one_br": 1200}
        r = RentResolver(comm, res)
        mix = UnitMix(one_br=2, floors=2)
        prop = _prop(city="Ottawa", province="ON", property_type="Mixed-Use",
                     unit_mix=mix, total_sq_ft=4000)
        rent, breakdown = r.resolve(prop)
        # Commercial skipped, only residential
        assert rent == pytest.approx(1200 * 2 * 12)
        assert any("missing" in line.lower() or "⚠" in line for line in breakdown)


# ── Hotel ─────────────────────────────────────────────────────────────────────

class TestHotelMode:
    def test_hotel_revenue(self):
        r = _resolver()
        prop = _prop(property_type="Hotel", hotel_rooms=50,
                     hotel_adr=150.0, hotel_occupancy=0.70)
        rent, breakdown = r.resolve(prop)
        expected = 50 * 150 * 0.70 * 365
        assert rent == pytest.approx(expected)

    def test_hotel_missing_fields_raises(self):
        r = _resolver()
        prop = _prop(property_type="Hotel", hotel_rooms=50, hotel_adr=150.0,
                     hotel_occupancy=None)
        with pytest.raises(ValueError, match="Hotel requires"):
            r.resolve(prop)

    def test_hotel_fallback_to_annual_rent(self):
        r = _resolver()
        prop = _prop(property_type="Hotel", hotel_rooms=50,
                     hotel_adr=None, hotel_occupancy=None, annual_rent=500_000)
        rent, _ = r.resolve(prop)
        assert rent == 500_000


# ── Retail-Office ─────────────────────────────────────────────────────────────

class TestRetailOfficeMode:
    def test_retail_office_two_floors(self):
        comm = MagicMock()
        comm.get_rent_per_sqft.side_effect = lambda city, prov, ptype: (
            {"Retail": 30.0, "Office": 20.0}.get(ptype)
        )
        r = RentResolver(comm, MagicMock())
        mix = UnitMix(floors=2)
        prop = _prop(city="Ottawa", province="ON", property_type="Retail-Office",
                     unit_mix=mix, total_sq_ft=4000)
        rent, breakdown = r.resolve(prop)
        # ground = 2000 * 30 = 60000, upper 1 floor = 2000 * 20 = 40000
        assert rent == pytest.approx(100_000)

    def test_retail_office_missing_raises(self):
        comm = MagicMock()
        comm.get_rent_per_sqft.return_value = None
        r = RentResolver(comm, MagicMock())
        mix = UnitMix(floors=2)
        prop = _prop(city="Ottawa", province="ON", property_type="Retail-Office",
                     unit_mix=mix, total_sq_ft=4000)
        with pytest.raises(ValueError):
            r.resolve(prop)


# ── No type / no rent ─────────────────────────────────────────────────────────

class TestNoRentMode:
    def test_no_type_no_rent_raises(self):
        r = _resolver()
        prop = _prop()  # no annual_rent, no property_type, no unit_mix
        with pytest.raises(ValueError, match="Provide annual_rent"):
            r.resolve(prop)


# ── Branch coverage gaps ───────────────────────────────────────────────────────

class TestRentResolverBranchGaps:

    def test_mixed_missing_comm_also_missing_res_logs_residential(self):
        """Mixed-use: comm rate None AND res rates None → _log_missing called for both."""
        store = MagicMock()
        comm = MagicMock()
        comm.get_rent_per_sqft.return_value = None
        res = MagicMock()
        res.get_rates.return_value = None  # residential also missing
        r = RentResolver(comm, res, store)
        mix = UnitMix(one_br=2, floors=2)
        prop = _prop(city="Nowhere", province="ON", property_type="Mixed-Use",
                     unit_mix=mix, total_sq_ft=4000)
        rent, breakdown = r.resolve(prop)
        # residential also gets logged
        calls = [str(c) for c in store.log_missing_city.call_args_list]
        assert any("residential" in c for c in calls)

    def test_commercial_missing_but_residential_exists_no_res_log(self):
        """Commercial rate missing + residential rates exist → residential NOT logged."""
        store = MagicMock()
        comm = MagicMock()
        comm.get_rent_per_sqft.return_value = None
        res = MagicMock()
        res.get_rates.return_value = {"one_br": 1200}  # residential EXISTS
        r = RentResolver(comm, res, store)
        prop = _prop(city="Ottawa", province="ON", property_type="Office", total_sq_ft=3000)
        with pytest.raises(ValueError, match="No commercial rate"):
            r.resolve(prop)
        # residential log_missing should NOT have been called
        for call in store.log_missing_city.call_args_list:
            assert "residential" not in str(call)

    def test_retail_office_single_floor_no_office_component(self):
        """Retail-Office with 1 floor: office_floors=0, no upper-floor breakdown line."""
        comm = MagicMock()
        comm.get_rent_per_sqft.side_effect = lambda city, prov, ptype: (
            {"Retail": 30.0, "Office": 20.0}.get(ptype)
        )
        r = RentResolver(comm, MagicMock())
        mix = UnitMix(floors=1)
        prop = _prop(city="Ottawa", province="ON", property_type="Retail-Office",
                     unit_mix=mix, total_sq_ft=2000)
        rent, breakdown = r.resolve(prop)
        # Only ground-floor retail: 2000 * 30 = 60000
        assert rent == pytest.approx(60_000)
        assert not any("Upper" in line for line in breakdown)

    def test_resolve_residential_no_avg_rate_skips_unit(self):
        """_resolve_residential: market has no numeric values AND unit not in market
        → city_avg_rate is None → unit skipped with warning."""
        # market dict with no numeric values → known_rates = [] → city_avg_rate = None
        market_no_rates = {"notes": "placeholder"}  # no numeric values
        res = MagicMock()
        res.get_rates.return_value = market_no_rates
        comm = MagicMock()
        comm.get_rent_per_sqft.return_value = None
        r = RentResolver(comm, res)
        # Unit mix with only 'three_br' which is not in market_no_rates
        mix = UnitMix(three_br=2)
        prop = _prop(city="Ottawa", province="ON", unit_mix=mix)
        rent, breakdown = r.resolve(prop)
        assert rent == 0.0
        assert any("skipped" in line or "no rate" in line for line in breakdown)
