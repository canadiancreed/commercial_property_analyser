"""
Tests for explicit commercial_rent / residential_rent inputs across every property type.

Verifies that user-provided rent figures are:
  1. Honoured over city-data lookups for every property type
  2. Stored in the correct field (_comm_rent vs _res_rent)
  3. Compatible with unit_mix being preserved alongside explicit rents
  4. Fall back to city/market-rate data when no explicit rent is given
"""
import pytest
from unittest.mock import MagicMock
from models.property_input import PropertyInput, UnitMix
from analysis.rent_resolver import RentResolver


# ── Helpers ───────────────────────────────────────────────────────────────────

def _prop(**kwargs):
    defaults = dict(
        original_price=500_000, asking_price=500_000,
        total_sq_ft=5_000, property_taxes=8_000,
        down_payment_pct=0.25, interest_rate=0.055,
        term_years=25, hold_years=10,
        city="Ottawa", province="ON",
    )
    defaults.update(kwargs)
    if "commercial_rent_user_entered" not in defaults:
        defaults["commercial_rent_user_entered"] = bool(defaults.get("commercial_rent"))
    if "residential_rent_user_entered" not in defaults:
        defaults["residential_rent_user_entered"] = bool(defaults.get("residential_rent"))
    defaults.pop("rent_manually_entered", None)
    return PropertyInput(**defaults)


def _resolver(comm_rates=None, res_rates=None):
    comm = MagicMock()
    comm.get_rent_per_sqft.side_effect = lambda city, prov, ptype: (
        comm_rates.get(ptype) if comm_rates else None
    )
    res = MagicMock()
    res.get_rates.return_value = res_rates
    return RentResolver(comm, res)


# ── Pure commercial types: explicit commercial_rent bypasses city lookup ───────
# Covers: Office, Retail, Industrial
# (Hotel and Retail-Office have their own classes below due to special resolver paths)

PURE_COMMERCIAL_TYPES = ["Office", "Retail", "Industrial"]


class TestPureCommercialExplicitRent:
    @pytest.mark.parametrize("ptype", PURE_COMMERCIAL_TYPES)
    def test_explicit_rent_used_not_city_data(self, ptype):
        """commercial_rent provided → resolver returns it directly, no $/sqft lookup."""
        r = _resolver(comm_rates={ptype: 25.0})
        prop = _prop(commercial_rent=99_000, property_type=ptype)
        rent, breakdown = r.resolve(prop)
        assert rent == 99_000
        r._commercial.get_rent_per_sqft.assert_not_called()
        assert any("directly" in line.lower() for line in breakdown)

    @pytest.mark.parametrize("ptype", PURE_COMMERCIAL_TYPES)
    def test_comm_rent_attributed_correctly(self, ptype):
        """_comm_rent gets the value; _res_rent stays 0."""
        r = _resolver()
        prop = _prop(commercial_rent=55_000, property_type=ptype)
        r.resolve(prop)
        assert r._comm_rent == 55_000
        assert r._res_rent == 0.0

    @pytest.mark.parametrize("ptype", PURE_COMMERCIAL_TYPES)
    def test_city_data_used_when_no_explicit_rent(self, ptype):
        """No commercial_rent → resolver falls through to $/sqft city lookup."""
        r = _resolver(comm_rates={ptype: 20.0})
        prop = _prop(property_type=ptype)
        rent, _ = r.resolve(prop)
        assert rent == pytest.approx(20.0 * 5_000)
        r._commercial.get_rent_per_sqft.assert_called_once()


# ── Residential types: explicit residential_rent bypasses market-rate lookup ──
# Covers: Residential, Multi-Family

RESIDENTIAL_TYPES = ["Residential", "Multi-Family"]


class TestResidentialExplicitRent:
    @pytest.mark.parametrize("ptype", RESIDENTIAL_TYPES)
    def test_explicit_rent_used_not_market_rates(self, ptype):
        """residential_rent provided → resolver returns it directly, no market lookup."""
        r = _resolver(res_rates={"one_br": 1_500})
        prop = _prop(
            residential_rent=42_000,
            property_type=ptype,
            unit_mix=UnitMix(one_br=2, floors=1),
        )
        rent, breakdown = r.resolve(prop)
        assert rent == 42_000
        r._residential.get_rates.assert_not_called()
        assert any("directly" in line.lower() for line in breakdown)

    @pytest.mark.parametrize("ptype", RESIDENTIAL_TYPES)
    def test_res_rent_attributed_correctly(self, ptype):
        """_res_rent gets the value; _comm_rent stays 0."""
        r = _resolver()
        prop = _prop(
            residential_rent=36_000,
            property_type=ptype,
            unit_mix=UnitMix(one_br=2, floors=1),
        )
        r.resolve(prop)
        assert r._res_rent == 36_000
        assert r._comm_rent == 0.0

    @pytest.mark.parametrize("ptype", RESIDENTIAL_TYPES)
    def test_market_rates_used_when_no_explicit_rent(self, ptype):
        """No residential_rent → resolver uses city market rates."""
        r = _resolver(res_rates={"one_br": 1_200})
        prop = _prop(
            property_type=ptype,
            unit_mix=UnitMix(one_br=3, floors=1),
        )
        rent, _ = r.resolve(prop)
        assert rent == pytest.approx(1_200 * 3 * 12)
        r._residential.get_rates.assert_called_once()

    @pytest.mark.parametrize("ptype", RESIDENTIAL_TYPES)
    def test_unit_mix_preserved_with_explicit_rent(self, ptype):
        """unit_mix counts survive when residential_rent is also provided."""
        mix = UnitMix(one_br=2, two_br=1, three_br=1, floors=2)
        prop = _prop(residential_rent=48_000, property_type=ptype, unit_mix=mix)
        assert prop.unit_mix.one_br == 2
        assert prop.unit_mix.two_br == 1
        assert prop.unit_mix.three_br == 1
        assert prop.unit_mix.floors == 2


# ── Mixed-Use: both sides tracked independently ───────────────────────────────

class TestMixedUseExplicitRent:
    def test_both_explicit_rents_summed(self):
        r = _resolver()
        prop = _prop(
            commercial_rent=50_000, residential_rent=30_000,
            property_type="Mixed-Use",
            unit_mix=UnitMix(one_br=3, floors=2),
        )
        rent, _ = r.resolve(prop)
        assert rent == 80_000

    def test_comm_and_res_split_correctly(self):
        r = _resolver()
        prop = _prop(
            commercial_rent=50_000, residential_rent=30_000,
            property_type="Mixed-Use",
            unit_mix=UnitMix(one_br=3, floors=2),
        )
        r.resolve(prop)
        assert r._comm_rent == 50_000
        assert r._res_rent == 30_000

    def test_no_city_lookup_when_both_explicit(self):
        r = _resolver(comm_rates={"Mixed-Use": 18.0}, res_rates={"one_br": 1_400})
        prop = _prop(
            commercial_rent=50_000, residential_rent=30_000,
            property_type="Mixed-Use",
            unit_mix=UnitMix(one_br=3, floors=2),
        )
        r.resolve(prop)
        r._commercial.get_rent_per_sqft.assert_not_called()
        r._residential.get_rates.assert_not_called()

    def test_unit_mix_preserved_with_both_explicit_rents(self):
        mix = UnitMix(bachelor=1, one_br=2, two_br=1, floors=3)
        prop = _prop(
            commercial_rent=40_000, residential_rent=25_000,
            property_type="Mixed-Use", unit_mix=mix,
        )
        assert prop.unit_mix.bachelor == 1
        assert prop.unit_mix.one_br == 2
        assert prop.unit_mix.two_br == 1
        assert prop.unit_mix.floors == 3

    def test_city_data_used_when_no_explicit_rents(self):
        """No explicit rents → resolver uses $/sqft for commercial + market rates for residential."""
        r = _resolver(
            comm_rates={"Mixed-Use": 18.0},
            res_rates={"one_br": 1_200},
        )
        prop = _prop(
            property_type="Mixed-Use",
            unit_mix=UnitMix(one_br=2, floors=2),
        )
        rent, _ = r.resolve(prop)
        # commercial: 18 * (5000/2) = 45000; residential: 1200 * 2 * 12 = 28800
        assert rent == pytest.approx(45_000 + 28_800)
        r._commercial.get_rent_per_sqft.assert_called_once()
        r._residential.get_rates.assert_called_once()


# ── Hotel: explicit commercial_rent bypasses ADR calculation ──────────────────

class TestHotelExplicitRent:
    def test_explicit_commercial_rent_bypasses_adr_calc(self):
        """commercial_rent provided → Mode 0 fires before hotel ADR path."""
        r = _resolver()
        prop = _prop(
            commercial_rent=120_000,
            property_type="Hotel",
            hotel_rooms=40, hotel_adr=150.0, hotel_occupancy=0.70,
        )
        rent, breakdown = r.resolve(prop)
        assert rent == 120_000
        assert r._comm_rent == 120_000
        assert r._res_rent == 0.0
        assert any("directly" in line.lower() for line in breakdown)

    def test_adr_calculation_used_when_no_explicit_rent(self):
        """No explicit rent → resolver computes revenue from rooms × ADR × occupancy × 365."""
        r = _resolver()
        prop = _prop(
            property_type="Hotel",
            hotel_rooms=40, hotel_adr=150.0, hotel_occupancy=0.70,
        )
        rent, _ = r.resolve(prop)
        expected = 40 * 150.0 * 0.70 * 365
        assert rent == pytest.approx(expected)

    def test_hotel_comm_rent_tracked_from_adr(self):
        r = _resolver()
        prop = _prop(
            property_type="Hotel",
            hotel_rooms=20, hotel_adr=200.0, hotel_occupancy=0.65,
        )
        r.resolve(prop)
        assert r._comm_rent == pytest.approx(20 * 200.0 * 0.65 * 365)
        assert r._res_rent == 0.0


# ── Retail-Office: explicit commercial_rent bypasses dual-rate calculation ─────

class TestRetailOfficeExplicitRent:
    def test_explicit_commercial_rent_used_directly(self):
        """commercial_rent provided → Mode 0 fires before retail+office floor split."""
        r = _resolver(comm_rates={"Retail": 30.0, "Office": 22.0})
        prop = _prop(
            commercial_rent=75_000,
            property_type="Retail-Office",
            unit_mix=UnitMix(floors=3),
        )
        rent, breakdown = r.resolve(prop)
        assert rent == 75_000
        r._commercial.get_rent_per_sqft.assert_not_called()
        assert any("directly" in line.lower() for line in breakdown)

    def test_comm_attributed_correctly(self):
        r = _resolver()
        prop = _prop(commercial_rent=75_000, property_type="Retail-Office")
        r.resolve(prop)
        assert r._comm_rent == 75_000
        assert r._res_rent == 0.0

    def test_dual_rate_calc_used_when_no_explicit_rent(self):
        """No explicit rent → resolver uses ground-floor retail + upper-floor office rates."""
        r = _resolver(comm_rates={"Retail": 30.0, "Office": 20.0})
        prop = _prop(
            property_type="Retail-Office",
            unit_mix=UnitMix(floors=3),
        )
        rent, _ = r.resolve(prop)
        floor_sqft = 5_000 / 3
        expected = (30.0 * floor_sqft) + (20.0 * floor_sqft * 2)
        assert rent == pytest.approx(expected)
        assert r._commercial.get_rent_per_sqft.call_count == 2  # Retail + Office


# ── Cross-type: correct split labelling in breakdown messages ─────────────────

class TestBreakdownMessages:
    @pytest.mark.parametrize("ptype", PURE_COMMERCIAL_TYPES + ["Hotel", "Retail-Office"])
    def test_commercial_label_in_breakdown(self, ptype):
        r = _resolver()
        prop = _prop(commercial_rent=50_000, property_type=ptype)
        _, breakdown = r.resolve(prop)
        assert any("commercial" in line.lower() for line in breakdown)

    @pytest.mark.parametrize("ptype", RESIDENTIAL_TYPES)
    def test_residential_label_in_breakdown(self, ptype):
        r = _resolver()
        prop = _prop(
            residential_rent=36_000, property_type=ptype,
            unit_mix=UnitMix(one_br=2, floors=1),
        )
        _, breakdown = r.resolve(prop)
        assert any("residential" in line.lower() for line in breakdown)

    def test_mixed_use_breakdown_has_both_labels(self):
        r = _resolver()
        prop = _prop(commercial_rent=50_000, residential_rent=30_000, property_type="Mixed-Use")
        _, breakdown = r.resolve(prop)
        text = " ".join(breakdown).lower()
        assert "commercial" in text
        assert "residential" in text
