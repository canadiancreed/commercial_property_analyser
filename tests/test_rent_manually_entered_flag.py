"""
Tests for the two-key rent provenance flags:
  commercial_rent_user_entered  — freeze only the commercial component
  residential_rent_user_entered — freeze only the residential component

Scenarios covered:
  - Default values and backward-compat rent_manually_entered property
  - Both flags True  → full short-circuit, resolver never called
  - Both flags False → full re-derive from market (stale stored values ignored)
  - comm True, res False  → commercial frozen, residential re-derived (partial freeze)
  - comm False, res True  → residential frozen, commercial re-derived (partial freeze)
  - needs_residential_recalc overrides res_frozen (units present, no stored res rent)
  - Persistence: to_record() writes both keys; _record_to_prop() reads them
  - Backward compat: old records with rent_manually_entered=True load correctly
  - _reanalyze_city propagates rate updates to resolver-derived components
"""
import pytest
from unittest.mock import MagicMock, patch
from models.property_input import PropertyInput, UnitMix
from analysis.rent_resolver import RentResolver


# ── Helpers ───────────────────────────────────────────────────────────────────

def _prop(**kwargs):
    defaults = dict(
        original_price=500_000, asking_price=500_000,
        total_sq_ft=5_000, property_taxes=8_000,
        down_payment_pct=0.25, interest_rate=0.055,
        term_years=25, hold_years=10,
    )
    defaults.update(kwargs)
    return PropertyInput(**defaults)


def _resolver(comm_rate=None, res_rates=None):
    comm = MagicMock()
    comm.get_rent_per_sqft.return_value = comm_rate
    res = MagicMock()
    res.get_rates.return_value = res_rates
    return RentResolver(comm, res)


# ── Defaults and backward-compat property ─────────────────────────────────────

class TestDefaults:
    def test_both_flags_default_false(self):
        prop = _prop()
        assert prop.commercial_rent_user_entered is False
        assert prop.residential_rent_user_entered is False

    def test_rent_manually_entered_false_when_both_false(self):
        prop = _prop()
        assert prop.rent_manually_entered is False

    def test_rent_manually_entered_true_when_comm_true(self):
        prop = _prop(commercial_rent_user_entered=True)
        assert prop.rent_manually_entered is True

    def test_rent_manually_entered_true_when_res_true(self):
        prop = _prop(residential_rent_user_entered=True)
        assert prop.rent_manually_entered is True

    def test_rent_manually_entered_true_when_both_true(self):
        prop = _prop(commercial_rent_user_entered=True, residential_rent_user_entered=True)
        assert prop.rent_manually_entered is True


# ── Both flags True → full short-circuit ──────────────────────────────────────

class TestBothFrozen:
    def test_uses_stored_rents_directly(self):
        r = _resolver(comm_rate=30.0, res_rates={"one_br": 1_500})
        prop = _prop(
            commercial_rent=80_000, residential_rent=36_000,
            commercial_rent_user_entered=True, residential_rent_user_entered=True,
            city="Ottawa", province="ON", property_type="Mixed-Use",
        )
        rent, _ = r.resolve(prop)
        assert rent == pytest.approx(116_000)
        assert r._comm_rent == pytest.approx(80_000)
        assert r._res_rent  == pytest.approx(36_000)

    def test_resolver_never_calls_market_lookups(self):
        r = _resolver(comm_rate=30.0)
        prop = _prop(
            commercial_rent=80_000, residential_rent=36_000,
            commercial_rent_user_entered=True, residential_rent_user_entered=True,
        )
        r.resolve(prop)
        r._commercial.get_rent_per_sqft.assert_not_called()
        r._residential.get_rates.assert_not_called()

    def test_breakdown_says_directly(self):
        r = _resolver()
        prop = _prop(
            commercial_rent=80_000, residential_rent=36_000,
            commercial_rent_user_entered=True, residential_rent_user_entered=True,
        )
        _, breakdown = r.resolve(prop)
        assert any("directly" in l.lower() for l in breakdown)

    def test_comm_only_frozen_both_flag_short_circuits(self):
        """commercial_rent set and flagged, residential absent — only comm returned."""
        r = _resolver(comm_rate=30.0)
        prop = _prop(
            commercial_rent=50_000,
            commercial_rent_user_entered=True, residential_rent_user_entered=True,
        )
        rent, _ = r.resolve(prop)
        assert rent == pytest.approx(50_000)


# ── Both flags False → full re-derive ─────────────────────────────────────────

class TestNeitherFrozen:
    def test_stale_commercial_rent_ignored(self):
        r = _resolver(comm_rate=25.0)
        prop = _prop(
            commercial_rent=99_999,  # stale stored value
            commercial_rent_user_entered=False, residential_rent_user_entered=False,
            city="Ottawa", province="ON", property_type="Office",
            total_sq_ft=4_000,
        )
        rent, _ = r.resolve(prop)
        assert rent == pytest.approx(25.0 * 4_000)
        r._commercial.get_rent_per_sqft.assert_called_once()

    def test_stale_residential_rent_ignored(self):
        r = _resolver(res_rates={"one_br": 1_200})
        mix = UnitMix(one_br=3)
        prop = _prop(
            residential_rent=50_000,  # stale stored value
            commercial_rent_user_entered=False, residential_rent_user_entered=False,
            city="Ottawa", province="ON", unit_mix=mix,
        )
        rent, _ = r.resolve(prop)
        assert rent == pytest.approx(1_200 * 3 * 12)

    def test_stale_mixed_use_rents_both_re_derived(self):
        comm = MagicMock()
        comm.get_rent_per_sqft.return_value = 20.0
        res = MagicMock()
        res.get_rates.return_value = {"one_br": 1_000}
        r = RentResolver(comm, res)
        mix = UnitMix(one_br=2, floors=2)
        prop = _prop(
            commercial_rent=999, residential_rent=999,  # stale
            commercial_rent_user_entered=False, residential_rent_user_entered=False,
            city="Ottawa", province="ON", property_type="Mixed-Use",
            unit_mix=mix, total_sq_ft=4_000,
        )
        rent, _ = r.resolve(prop)
        # comm: (4000/2) * 20 = 40_000; res: 1000 * 2 * 12 = 24_000
        assert rent == pytest.approx(64_000)


# ── Partial freeze: commercial frozen, residential re-derived ─────────────────

class TestCommFrozenResDerived:
    def test_commercial_uses_stored_residential_uses_market(self):
        comm = MagicMock()
        comm.get_rent_per_sqft.return_value = 20.0
        res = MagicMock()
        res.get_rates.return_value = {"one_br": 1_000}
        r = RentResolver(comm, res)
        mix = UnitMix(one_br=2, floors=2)
        prop = _prop(
            commercial_rent=55_000,  # user-entered
            residential_rent=999,    # stale — should be ignored
            commercial_rent_user_entered=True,
            residential_rent_user_entered=False,
            city="Ottawa", province="ON", property_type="Mixed-Use",
            unit_mix=mix, total_sq_ft=4_000,
        )
        rent, breakdown = r.resolve(prop)
        assert r._comm_rent == pytest.approx(55_000)
        assert r._res_rent  == pytest.approx(1_000 * 2 * 12)
        assert rent == pytest.approx(55_000 + 24_000)
        assert any("directly" in l.lower() for l in breakdown)

    def test_commercial_market_lookup_not_called_when_comm_frozen(self):
        comm = MagicMock()
        res = MagicMock()
        res.get_rates.return_value = {"one_br": 1_000}
        r = RentResolver(comm, res)
        mix = UnitMix(one_br=2, floors=2)
        prop = _prop(
            commercial_rent=55_000,
            commercial_rent_user_entered=True,
            residential_rent_user_entered=False,
            city="Ottawa", province="ON", property_type="Mixed-Use",
            unit_mix=mix, total_sq_ft=4_000,
        )
        r.resolve(prop)
        comm.get_rent_per_sqft.assert_not_called()
        res.get_rates.assert_called_once()


# ── Partial freeze: residential frozen, commercial re-derived ─────────────────

class TestResFrozenCommDerived:
    def test_residential_uses_stored_commercial_uses_market(self):
        comm = MagicMock()
        comm.get_rent_per_sqft.return_value = 20.0
        res = MagicMock()
        res.get_rates.return_value = {"one_br": 1_000}
        r = RentResolver(comm, res)
        mix = UnitMix(one_br=2, floors=2)
        prop = _prop(
            commercial_rent=999,     # stale — should be ignored
            residential_rent=40_000, # user-entered
            commercial_rent_user_entered=False,
            residential_rent_user_entered=True,
            city="Ottawa", province="ON", property_type="Mixed-Use",
            unit_mix=mix, total_sq_ft=4_000,
        )
        rent, breakdown = r.resolve(prop)
        assert r._comm_rent == pytest.approx(20.0 * (4_000 / 2))
        assert r._res_rent  == pytest.approx(40_000)
        assert rent == pytest.approx(40_000 + 40_000)
        assert any("directly" in l.lower() for l in breakdown)

    def test_residential_market_lookup_not_called_when_res_frozen(self):
        comm = MagicMock()
        comm.get_rent_per_sqft.return_value = 20.0
        res = MagicMock()
        r = RentResolver(comm, res)
        mix = UnitMix(one_br=2, floors=2)
        prop = _prop(
            residential_rent=40_000,
            commercial_rent_user_entered=False,
            residential_rent_user_entered=True,
            city="Ottawa", province="ON", property_type="Mixed-Use",
            unit_mix=mix, total_sq_ft=4_000,
        )
        r.resolve(prop)
        res.get_rates.assert_not_called()
        comm.get_rent_per_sqft.assert_called_once()


# ── needs_residential_recalc overrides res_frozen ────────────────────────────

class TestResidentialRecalcOverride:
    def test_units_present_no_stored_res_recalculates_even_when_res_frozen(self):
        """If res_frozen=True but residential_rent is None/0, there's nothing to freeze —
        the resolver must derive from unit mix."""
        r = _resolver(res_rates={"one_br": 1_000})
        mix = UnitMix(one_br=2)
        prop = _prop(
            residential_rent=None,  # nothing stored to freeze
            residential_rent_user_entered=True,  # flag set but no value
            city="Ottawa", province="ON", unit_mix=mix,
        )
        rent, _ = r.resolve(prop)
        assert rent == pytest.approx(1_000 * 2 * 12)
        r._residential.get_rates.assert_called_once()


# ── Persistence: to_record() and _record_to_prop() ───────────────────────────

class TestPersistence:
    def _analyzer(self, prop):
        from analysis.analyzer import CommercialPropertyAnalyzer
        comm = MagicMock()
        comm.get_rent_per_sqft.return_value = 20.0
        res = MagicMock()
        res.get_rates.return_value = {"one_br": 1_200}
        return CommercialPropertyAnalyzer(prop, RentResolver(comm, res))

    def test_to_record_writes_both_flags_true(self):
        prop = _prop(
            commercial_rent=60_000, residential_rent=30_000,
            commercial_rent_user_entered=True, residential_rent_user_entered=True,
            city="Ottawa", province="ON", property_type="Mixed-Use",
            listing_date="2025-01-01",
            unit_mix=UnitMix(one_br=2, floors=2), total_sq_ft=4_000,
        )
        record = self._analyzer(prop).to_record()
        assert record["commercial_rent_user_entered"] is True
        assert record["residential_rent_user_entered"] is True

    def test_to_record_writes_both_flags_false(self):
        prop = _prop(
            city="Ottawa", province="ON", property_type="Office",
            total_sq_ft=3_000, listing_date="2025-01-01",
        )
        record = self._analyzer(prop).to_record()
        assert record["commercial_rent_user_entered"] is False
        assert record["residential_rent_user_entered"] is False

    def test_to_record_writes_partial_flags(self):
        prop = _prop(
            commercial_rent=55_000,
            commercial_rent_user_entered=True, residential_rent_user_entered=False,
            city="Ottawa", province="ON", property_type="Mixed-Use",
            listing_date="2025-01-01",
            unit_mix=UnitMix(one_br=2, floors=2), total_sq_ft=4_000,
        )
        record = self._analyzer(prop).to_record()
        assert record["commercial_rent_user_entered"] is True
        assert record["residential_rent_user_entered"] is False

    def test_record_to_prop_reads_two_key_flags(self):
        from ui.menu import PropertyMenu
        record = {
            "address": "123 Main St", "mls_number": "", "status": "active",
            "original_price": 500_000, "asking_price": 500_000,
            "total_sq_ft": 3_000, "property_taxes": 8_000,
            "down_payment_pct": 0.25, "interest_rate": 0.055, "term_years": 25,
            "hold_years": 10, "city": "Ottawa", "province": "ON",
            "property_type": "Office", "unit_mix": {},
            "commercial_rent": 60_000, "residential_rent": None,
            "commercial_rent_user_entered": True,
            "residential_rent_user_entered": False,
        }
        prop = PropertyMenu._record_to_prop(record)
        assert prop.commercial_rent_user_entered is True
        assert prop.residential_rent_user_entered is False

    def test_record_to_prop_missing_flags_default_false(self):
        """Legacy records with no flags at all default both to False."""
        from ui.menu import PropertyMenu
        record = {
            "address": "123 Main St", "mls_number": "", "status": "active",
            "original_price": 500_000, "asking_price": 500_000,
            "total_sq_ft": 3_000, "property_taxes": 8_000,
            "down_payment_pct": 0.25, "interest_rate": 0.055, "term_years": 25,
            "hold_years": 10, "city": "Ottawa", "province": "ON",
            "property_type": "Office", "unit_mix": {},
            "commercial_rent": 60_000, "residential_rent": None,
        }
        prop = PropertyMenu._record_to_prop(record)
        assert prop.commercial_rent_user_entered is False
        assert prop.residential_rent_user_entered is False
        assert prop.rent_manually_entered is False


# ── Backward compat: old single-flag records ──────────────────────────────────

class TestBackwardCompat:
    def test_old_rent_manually_entered_true_sets_both_keys(self):
        """Old record with rent_manually_entered=True and no two-key fields
        should load with both component flags True (conservative: protect both)."""
        from ui.menu import PropertyMenu
        record = {
            "address": "123 Main St", "mls_number": "", "status": "active",
            "original_price": 500_000, "asking_price": 500_000,
            "total_sq_ft": 3_000, "property_taxes": 8_000,
            "down_payment_pct": 0.25, "interest_rate": 0.055, "term_years": 25,
            "hold_years": 10, "city": "Ottawa", "province": "ON",
            "property_type": "Office", "unit_mix": {},
            "commercial_rent": 60_000, "residential_rent": None,
            "rent_manually_entered": True,
        }
        prop = PropertyMenu._record_to_prop(record)
        assert prop.commercial_rent_user_entered is True
        assert prop.residential_rent_user_entered is True

    def test_old_rent_manually_entered_false_sets_both_keys_false(self):
        from ui.menu import PropertyMenu
        record = {
            "address": "123 Main St", "mls_number": "", "status": "active",
            "original_price": 500_000, "asking_price": 500_000,
            "total_sq_ft": 3_000, "property_taxes": 8_000,
            "down_payment_pct": 0.25, "interest_rate": 0.055, "term_years": 25,
            "hold_years": 10, "city": "Ottawa", "province": "ON",
            "property_type": "Office", "unit_mix": {},
            "commercial_rent": 60_000, "residential_rent": None,
            "rent_manually_entered": False,
        }
        prop = PropertyMenu._record_to_prop(record)
        assert prop.commercial_rent_user_entered is False
        assert prop.residential_rent_user_entered is False

    def test_two_key_fields_take_precedence_over_old_flag(self):
        """If the new keys are present they win, even if old flag disagrees."""
        from ui.menu import PropertyMenu
        record = {
            "address": "123 Main St", "mls_number": "", "status": "active",
            "original_price": 500_000, "asking_price": 500_000,
            "total_sq_ft": 3_000, "property_taxes": 8_000,
            "down_payment_pct": 0.25, "interest_rate": 0.055, "term_years": 25,
            "hold_years": 10, "city": "Ottawa", "province": "ON",
            "property_type": "Office", "unit_mix": {},
            "commercial_rent": 60_000, "residential_rent": 20_000,
            "rent_manually_entered": True,         # old flag says both manual
            "commercial_rent_user_entered": True,  # new: comm manual
            "residential_rent_user_entered": False, # new: res derived
        }
        prop = PropertyMenu._record_to_prop(record)
        assert prop.commercial_rent_user_entered is True
        assert prop.residential_rent_user_entered is False


# ── _reanalyze_city propagates rate updates ───────────────────────────────────

class TestReanalyzeCityBehaviour:
    """
    _reanalyze_city must re-derive resolver-derived components when rates change,
    and must leave user-entered components untouched.
    """

    def _make_resolver(self, comm_rate, res_rate):
        comm = MagicMock()
        comm.get_rent_per_sqft.return_value = comm_rate
        res = MagicMock()
        res.get_rates.return_value = {"one_br": res_rate} if res_rate else None
        return RentResolver(comm, res)

    def test_resolver_derived_commercial_updates_on_reanalysis(self):
        """commercial_rent_user_entered=False → rate change propagates."""
        r = self._make_resolver(comm_rate=20.0, res_rate=None)
        prop = _prop(
            commercial_rent=80_000,   # old derived value at old rate
            commercial_rent_user_entered=False,
            city="Ottawa", province="ON", property_type="Office",
            total_sq_ft=4_000,
        )
        rent, _ = r.resolve(prop)
        assert rent == pytest.approx(20.0 * 4_000)  # new rate applied

    def test_user_entered_commercial_unchanged_on_reanalysis(self):
        """commercial_rent_user_entered=True → stored value preserved despite rate change."""
        r = self._make_resolver(comm_rate=20.0, res_rate=None)
        prop = _prop(
            commercial_rent=55_000,
            commercial_rent_user_entered=True,
            residential_rent_user_entered=True,  # both frozen for pure commercial
            city="Ottawa", province="ON", property_type="Office",
            total_sq_ft=4_000,
        )
        rent, _ = r.resolve(prop)
        assert rent == pytest.approx(55_000)
        r._commercial.get_rent_per_sqft.assert_not_called()

    def test_mixed_use_rate_change_updates_derived_res_not_manual_comm(self):
        """Mixed-use: comm frozen by user, res re-derived when rate changes."""
        comm = MagicMock()
        comm.get_rent_per_sqft.return_value = 25.0  # changed rate — should be ignored
        res = MagicMock()
        res.get_rates.return_value = {"one_br": 1_500}  # new rate
        r = RentResolver(comm, res)
        mix = UnitMix(one_br=2, floors=2)
        prop = _prop(
            commercial_rent=55_000,   # user-entered, must survive
            residential_rent=20_000,  # old derived value
            commercial_rent_user_entered=True,
            residential_rent_user_entered=False,
            city="Ottawa", province="ON", property_type="Mixed-Use",
            unit_mix=mix, total_sq_ft=4_000,
        )
        rent, _ = r.resolve(prop)
        assert r._comm_rent == pytest.approx(55_000)
        assert r._res_rent  == pytest.approx(1_500 * 2 * 12)
        comm.get_rent_per_sqft.assert_not_called()
        res.get_rates.assert_called_once()
