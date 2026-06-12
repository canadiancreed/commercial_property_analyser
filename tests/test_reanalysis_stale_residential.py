"""
Regression tests for stale residential_rent=0.0 on Mixed-Use properties.

Context: properties created before city residential data existed are stored with
residential_rent=0.0.  On re-analysis the full pipeline must recalculate
residential income from the unit_mix rather than treating the stored zero as an
explicit "no residential income" signal.

Three layers are tested:
  1. _record_to_prop  — how the stored record is converted to PropertyInput
  2. RentResolver     — that the correct path fires given the PropertyInput
  3. End-to-end       — full record → _record_to_prop → analyzer → to_record()
"""

import pytest
from unittest.mock import MagicMock

from models.property_input import PropertyInput, UnitMix
from analysis.rent_resolver import RentResolver
from analysis.analyzer import CommercialPropertyAnalyzer
from ui.menu import PropertyMenu


# ── Helpers ───────────────────────────────────────────────────────────────────

COMM_RATE   = 15.0   # $/sqft/yr (Midland Mixed-Use market rate)
ONE_BR_RATE = 1_550  # $/mo
UNK_RATE    = 2_050  # $/mo


def _resolver(comm_rate=COMM_RATE, res_rates=None):
    if res_rates is None:
        res_rates = {"one_br": ONE_BR_RATE, "unknown": UNK_RATE}
    comm = MagicMock()
    comm.get_rent_per_sqft.return_value = comm_rate
    res = MagicMock()
    res.get_rates.return_value = res_rates
    return RentResolver(comm, res)


def _stored_record(**overrides):
    """Minimal stored JSON record for a 2-floor Mixed-Use property."""
    base = {
        "address":          "262 King St, Midland, ON",
        "mls_number":       "X12345",
        "status":           "active",
        "listing_date":     "2025-01-01",
        "asking_price":     550_000,
        "original_price":   550_000,
        "total_sq_ft":      2_725,
        "city":             "Midland",
        "province":         "ON",
        "property_type":    "Mixed-Use",
        "property_taxes":   6_000,
        "down_payment_pct": 0.20,
        "interest_rate":    0.055,
        "term_years":       25,
        "hold_years":       30,
        "expense_ratio":    0.40,
        "lease_type":       "Normal",
        "construction_cost": 0,
        "annual_rent":      20_437.5,
        "commercial_rent":  20_437.5,
        "residential_rent": 0.0,          # stale — stored before city data existed
        "vacancy_rate":     0.09,
        "noi_growth_rate":  None,
        "unit_mix": {
            "bachelor": 0, "one_br": 2, "two_br": 0,
            "three_br": 0, "four_br": 0, "unknown": 0,
            "floors": 2,
        },
        "floors": 2,
        "results": [],
    }
    base.update(overrides)
    return base


# ── Layer 1: _record_to_prop ──────────────────────────────────────────────────

class TestRecordToProp:

    def test_stale_residential_rent_becomes_none(self):
        """residential_rent=0.0 stored in JSON → prop.residential_rent is None.
        This is the 'or None' conversion in _record_to_prop."""
        prop = PropertyMenu._record_to_prop(_stored_record())
        assert prop.residential_rent is None

    def test_commercial_rent_preserved(self):
        prop = PropertyMenu._record_to_prop(_stored_record())
        assert prop.commercial_rent == pytest.approx(20_437.5)

    def test_unit_mix_rebuilt_with_units(self):
        prop = PropertyMenu._record_to_prop(_stored_record())
        assert prop.unit_mix is not None
        assert prop.unit_mix.total_units == 2
        assert prop.unit_mix.one_br == 2
        assert prop.unit_mix.floors == 2

    def test_annual_rent_suppressed_when_commercial_rent_present(self):
        """annual_rent must be None so resolver doesn't short-circuit via Mode 1."""
        prop = PropertyMenu._record_to_prop(_stored_record())
        assert prop.annual_rent is None

    def test_positive_residential_rent_preserved(self):
        """When residential_rent is genuinely provided (non-zero), it survives the conversion."""
        prop = PropertyMenu._record_to_prop(_stored_record(residential_rent=37_200.0))
        assert prop.residential_rent == pytest.approx(37_200.0)

    def test_no_units_gives_floors_only_unit_mix(self):
        """Record with all-zero unit counts → floors-only UnitMix on
        PropertyInput (zero units, but the floor count is preserved)."""
        record = _stored_record()
        record["unit_mix"] = {
            "bachelor": 0, "one_br": 0, "two_br": 0,
            "three_br": 0, "four_br": 0, "unknown": 0, "floors": 2,
        }
        prop = PropertyMenu._record_to_prop(record)
        assert prop.unit_mix is not None
        assert prop.unit_mix.total_units == 0
        assert prop.unit_mix.floors == 2


# ── Layer 2: RentResolver ─────────────────────────────────────────────────────

class TestResolverStaleResidential:

    def _prop(self, commercial_rent, residential_rent, units=2,
              commercial_rent_user_entered=False, residential_rent_user_entered=False):
        """Build a PropertyInput that mirrors what _record_to_prop produces."""
        mix = UnitMix(one_br=units, floors=2) if units > 0 else None
        return PropertyInput(
            address="262 King St, Midland, ON",
            mls_number="X12345", status="active",
            original_price=550_000, asking_price=550_000,
            total_sq_ft=2_725, property_taxes=6_000,
            down_payment_pct=0.20, interest_rate=0.055,
            term_years=25, hold_years=30,
            city="Midland", province="ON",
            property_type="Mixed-Use",
            commercial_rent=commercial_rent,
            residential_rent=residential_rent,
            unit_mix=mix,
            commercial_rent_user_entered=commercial_rent_user_entered,
            residential_rent_user_entered=residential_rent_user_entered,
        )

    def test_none_residential_with_units_triggers_recalc(self):
        """commercial_rent set, residential_rent=None, unit_mix has units → recalculate."""
        r = _resolver()
        prop = self._prop(commercial_rent=20_437.5, residential_rent=None)
        rent, _ = r.resolve(prop)
        expected_comm = COMM_RATE * (2_725 / 2)       # 20437.5
        expected_res  = ONE_BR_RATE * 2 * 12           # 37200
        assert rent == pytest.approx(expected_comm + expected_res)
        assert r._res_rent == pytest.approx(expected_res)

    def test_zero_residential_with_units_triggers_recalc(self):
        """commercial_rent set, residential_rent=0.0, unit_mix has units → recalculate."""
        r = _resolver()
        prop = self._prop(commercial_rent=20_437.5, residential_rent=0.0)
        rent, _ = r.resolve(prop)
        assert r._res_rent == pytest.approx(ONE_BR_RATE * 2 * 12)

    def test_positive_residential_rent_short_circuits(self):
        """Both rents manually entered and non-zero → early exit, no city lookup."""
        r = _resolver()
        prop = self._prop(commercial_rent=20_437.5, residential_rent=37_200.0,
                          commercial_rent_user_entered=True, residential_rent_user_entered=True)
        rent, breakdown = r.resolve(prop)
        assert rent == pytest.approx(20_437.5 + 37_200.0)
        r._commercial.get_rent_per_sqft.assert_not_called()
        r._residential.get_rates.assert_not_called()
        assert any("directly" in line.lower() for line in breakdown)

    def test_no_units_commercial_only_short_circuits(self):
        """commercial_rent manually entered, no unit_mix → early exit used."""
        r = _resolver()
        prop = self._prop(commercial_rent=20_437.5, residential_rent=None, units=0,
                          commercial_rent_user_entered=True, residential_rent_user_entered=True)
        rent, breakdown = r.resolve(prop)
        assert rent == pytest.approx(20_437.5)
        r._commercial.get_rent_per_sqft.assert_not_called()

    def test_city_lookup_fires_for_comm_component(self):
        """When residential recalc is needed, commercial is also recalculated via city lookup."""
        r = _resolver()
        prop = self._prop(commercial_rent=20_437.5, residential_rent=None)
        r.resolve(prop)
        r._commercial.get_rent_per_sqft.assert_called_once()

    def test_residential_lookup_fires_for_res_component(self):
        r = _resolver()
        prop = self._prop(commercial_rent=20_437.5, residential_rent=None)
        r.resolve(prop)
        r._residential.get_rates.assert_called_once()


# ── Layer 3: End-to-end pipeline ──────────────────────────────────────────────

class TestEndToEndReanalysis:
    """Full record → _record_to_prop → CommercialPropertyAnalyzer → to_record()."""

    def _analyze(self, record):
        prop     = PropertyMenu._record_to_prop(record)
        analyzer = CommercialPropertyAnalyzer(prop, _resolver())
        return analyzer.to_record(existing=record)

    def test_residential_rent_updated_in_output(self):
        """to_record() must contain the recalculated residential_rent, not 0.0."""
        out = self._analyze(_stored_record())
        assert out["residential_rent"] == pytest.approx(ONE_BR_RATE * 2 * 12)

    def test_annual_rent_includes_residential(self):
        expected_comm = COMM_RATE * (2_725 / 2)
        expected_res  = ONE_BR_RATE * 2 * 12
        out = self._analyze(_stored_record())
        assert out["annual_rent"] == pytest.approx(expected_comm + expected_res)

    def test_reanalysis_is_idempotent(self):
        """Running to_record() twice produces the same residential_rent both times."""
        first  = self._analyze(_stored_record())
        second = self._analyze(first)
        assert second["residential_rent"] == pytest.approx(first["residential_rent"])
        assert second["annual_rent"]      == pytest.approx(first["annual_rent"])

    def test_noi_improves_after_recalc(self):
        """NOI with residential recalc must exceed NOI from commercial-only rent."""
        out = self._analyze(_stored_record())
        # NOI = EGI × (1 - expense_ratio); EGI = annual_rent × (1 - vacancy)
        # With correct rent ~57637 vs old ~20437 — cap rate must be above 3%
        results = {r["metric"]: r["value"] for r in out["results"]}
        cap_str = results.get("Cap Rate", "0%").rstrip("%")
        assert float(cap_str) > 3.0

    def test_previously_correct_property_unchanged(self):
        """270 King St (Retail-Office, no units) must not be affected — res stays 0."""
        record = _stored_record(
            address="270 King St, Midland, ON",
            property_type="Retail-Office",
            total_sq_ft=3_707,
            asking_price=900_000,
            original_price=900_000,
            annual_rent=55_605.0,
            commercial_rent=55_605.0,
            residential_rent=0.0,
            unit_mix={"bachelor":0,"one_br":0,"two_br":0,"three_br":0,"four_br":0,"unknown":0,"floors":1},
            floors=1,
        )
        prop     = PropertyMenu._record_to_prop(record)
        analyzer = CommercialPropertyAnalyzer(prop, _resolver())
        out      = analyzer.to_record(existing=record)
        assert out["residential_rent"] == pytest.approx(0.0)
