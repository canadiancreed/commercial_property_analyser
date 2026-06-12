"""
Regression tests for the zero-rate stub bug.

Root cause: ensure_city_in_rates wrote {"Office": 0, ...} as a sentinel for
"rate not yet fetched".  The resolver's guards only checked `if rate is None`,
so 0 passed through as a valid rate, producing $0 rent with no error.

Fix:
  - Stubs now use None instead of 0.
  - ensure_city_in_rates migrates existing on-disk zeros to None on first call.
  - load_residential_rates handles None values without raising TypeError.
  - ResidentialRentLoader.get_rates returns None for an all-None stub city.
  - _resolve_residential skips None per-unit values and excludes 0/None from avg.

Coverage:
  1. Sentinel / migration  (store layer)
  2. Loaders return None for stubs  (store layer)
  3. All property types raise / skip correctly with None stubs  (resolver layer)
  4. _resolve_residential handles partially-populated cities  (resolver layer)
  5. _reanalyze_all counts stub cities as skipped, not updated  (end-to-end)
"""

import json
import os
import pytest
from unittest.mock import MagicMock

from data.store import DataStore, CommercialRentLoader, ResidentialRentLoader
from analysis.rent_resolver import RentResolver
from analysis.analyzer import CommercialPropertyAnalyzer
from models.property_input import PropertyInput, UnitMix
from ui.menu import PropertyMenu


# ── Shared helpers ────────────────────────────────────────────────────────────

def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _make_store(tmp_path, comm_cities=None, res_cities=None):
    comm = str(tmp_path / "comm.json")
    res  = str(tmp_path / "res.json")
    os.makedirs(str(tmp_path), exist_ok=True)
    with open(comm, "w") as f:
        json.dump({"cities": comm_cities or {}}, f)
    with open(res, "w") as f:
        json.dump({"cities": res_cities or {}}, f)
    return DataStore(
        commercial_path=comm, residential_path=res,
        properties_path=str(tmp_path / "props.json"),
        missing_path=str(tmp_path / "miss.json"),
    )


def _prop(**kwargs):
    defaults = dict(
        original_price=500_000, asking_price=500_000,
        total_sq_ft=5_000, property_taxes=8_000,
        down_payment_pct=0.25, interest_rate=0.055,
        term_years=25, hold_years=10,
    )
    defaults.update(kwargs)
    return PropertyInput(**defaults)


def _mock_resolver(comm_rate=None, res_rates=None, store=None):
    comm = MagicMock()
    comm.get_rent_per_sqft.return_value = comm_rate
    res = MagicMock()
    res.get_rates.return_value = res_rates
    return RentResolver(comm, res, store)


# ═══════════════════════════════════════════════════════════════════════════════
# 1.  Sentinel / migration  (store layer)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSentinelAndMigration:

    def test_new_stub_commercial_values_are_none(self, tmp_path):
        store = _make_store(tmp_path)
        store.ensure_city_in_rates("Stubville", "ON")
        raw = DataStore._read(store._commercial_path)
        types = raw["cities"]["Stubville"]["types"]
        assert all(v is None for v in types.values()), \
            "New commercial stubs must be None, not 0"

    def test_new_stub_residential_values_are_none(self, tmp_path):
        store = _make_store(tmp_path)
        store.ensure_city_in_rates("Stubville", "ON")
        raw = DataStore._read(store._residential_path)
        units = raw["cities"]["Stubville"]["units"]
        assert all(v is None for v in units.values()), \
            "New residential stubs must be None, not 0"

    def test_migration_rewrites_existing_commercial_zeros(self, tmp_path):
        old_comm = {
            "Oldcity": {
                "province": "ON",
                "types": {"Office": 0, "Retail": 0, "Industrial": 0, "Mixed-Use": 0}
            }
        }
        store = _make_store(tmp_path, comm_cities=old_comm)
        store.ensure_city_in_rates("Othercity", "ON")
        raw = DataStore._read(store._commercial_path)
        types = raw["cities"]["Oldcity"]["types"]
        assert all(v is None for v in types.values()), \
            "Legacy zero commercial stubs must be migrated to None"

    def test_migration_rewrites_existing_residential_zeros(self, tmp_path):
        old_res = {
            "Oldcity": {
                "province": "ON",
                "units": {"bachelor": 0, "one_br": 0, "two_br": 0,
                          "three_br": 0, "four_br": 0, "unknown": 0}
            }
        }
        store = _make_store(tmp_path, res_cities=old_res)
        store.ensure_city_in_rates("Othercity", "ON")
        raw = DataStore._read(store._residential_path)
        units = raw["cities"]["Oldcity"]["units"]
        assert all(v is None for v in units.values()), \
            "Legacy zero residential stubs must be migrated to None"

    def test_migration_does_not_touch_real_rates(self, tmp_path):
        populated = {
            "Ottawa": {
                "province": "ON",
                "types": {"Office": 20.0, "Retail": 30.0, "Industrial": 12.0, "Mixed-Use": 18.0}
            }
        }
        store = _make_store(tmp_path, comm_cities=populated)
        store.ensure_city_in_rates("Newcity", "ON")
        idx = store.load_commercial_rates()
        assert idx["ottawa"]["office"] == 20.0
        assert idx["ottawa"]["retail"] == 30.0

    def test_migration_is_idempotent(self, tmp_path):
        store = _make_store(tmp_path)
        store.ensure_city_in_rates("Alpha", "ON")
        store.ensure_city_in_rates("Alpha", "ON")  # second call must not crash
        idx = store.load_commercial_rates()
        assert "alpha" in idx

    def test_stub_city_appears_in_commercial_index_with_none_values(self, tmp_path):
        store = _make_store(tmp_path)
        store.ensure_city_in_rates("Newtown", "ON")
        idx = store.load_commercial_rates()
        assert "newtown" in idx
        assert idx["newtown"]["office"] is None

    def test_stub_city_appears_in_residential_index_with_none_values(self, tmp_path):
        store = _make_store(tmp_path)
        store.ensure_city_in_rates("Newtown", "ON")
        idx = store.load_residential_rates()
        assert "newtown" in idx
        assert idx["newtown"]["one_br"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# 2.  Loader behaviour with None stubs
# ═══════════════════════════════════════════════════════════════════════════════

class TestLoadersWithNullStubs:

    def _stub_store(self, tmp_path):
        store = _make_store(tmp_path)
        store.ensure_city_in_rates("Stubcity", "ON")
        return store

    def test_commercial_loader_returns_none_for_null_stub(self, tmp_path):
        store = self._stub_store(tmp_path)
        loader = CommercialRentLoader(store)
        assert loader.get_rent_per_sqft("Stubcity", "ON", "Office") is None

    def test_commercial_loader_returns_none_for_each_stub_type(self, tmp_path):
        store = self._stub_store(tmp_path)
        loader = CommercialRentLoader(store)
        for ptype in ("Office", "Retail", "Industrial", "Mixed-Use"):
            assert loader.get_rent_per_sqft("Stubcity", "ON", ptype) is None, \
                f"{ptype} stub should return None"

    def test_residential_loader_returns_none_for_all_null_stub(self, tmp_path):
        store = self._stub_store(tmp_path)
        loader = ResidentialRentLoader(store)
        assert loader.get_rates("Stubcity", "ON") is None, \
            "All-None residential stub should return None from loader"

    def test_residential_loader_returns_dict_if_any_real_rate(self, tmp_path):
        """Partially populated city (one real rate) should not be treated as missing."""
        store = self._stub_store(tmp_path)
        # Manually set one real rate
        store.save_residential_rates(
            "Stubcity", "ON",
            {"bachelor": None, "one_br": 1200, "two_br": None,
             "three_br": None, "four_br": None, "unknown": None}
        )
        loader = ResidentialRentLoader(store)
        rates = loader.get_rates("Stubcity", "ON")
        assert rates is not None
        assert rates["one_br"] == 1200.0

    def test_load_residential_rates_handles_null_values_without_error(self, tmp_path):
        """load_residential_rates must not raise TypeError on None values in JSON."""
        store = self._stub_store(tmp_path)
        # Should not raise
        idx = store.load_residential_rates()
        assert "stubcity" in idx


# ═══════════════════════════════════════════════════════════════════════════════
# 3.  Resolver — all property types raise / skip with None stubs
# ═══════════════════════════════════════════════════════════════════════════════

class TestResolverNullStubAllTypes:
    """After the fix, None stubs reach the None guards and raise ValueError
    (pure commercial) or skip the commercial component (mixed-use)."""

    @pytest.mark.parametrize("ptype", ["Office", "Retail", "Industrial"])
    def test_pure_commercial_type_raises_on_null_stub(self, ptype):
        r = _mock_resolver(comm_rate=None)
        prop = _prop(city="Stubville", province="ON", property_type=ptype,
                     total_sq_ft=5_000)
        with pytest.raises(ValueError, match="No commercial rate"):
            r.resolve(prop)

    def test_retail_office_raises_on_null_stub(self):
        r = _mock_resolver(comm_rate=None)
        mix = UnitMix(floors=2)
        prop = _prop(city="Stubville", province="ON", property_type="Retail-Office",
                     unit_mix=mix, total_sq_ft=4_000)
        with pytest.raises(ValueError):
            r.resolve(prop)

    def test_mixed_use_null_comm_stub_skips_commercial_component(self):
        """Mixed-use: None commercial rate → commercial skipped, residential kept."""
        comm = MagicMock()
        comm.get_rent_per_sqft.return_value = None
        res = MagicMock()
        res.get_rates.return_value = {"one_br": 1_200}
        r = RentResolver(comm, res)
        mix = UnitMix(one_br=2, floors=2)
        prop = _prop(city="Stubville", province="ON", property_type="Mixed-Use",
                     unit_mix=mix, total_sq_ft=4_000)
        rent, breakdown = r.resolve(prop)
        # Only residential: 1200 * 2 * 12 = 28800
        assert rent == pytest.approx(1_200 * 2 * 12)
        assert any("⚠" in line or "missing" in line.lower() for line in breakdown)

    def test_mixed_use_both_stubs_null_returns_zero_rent(self):
        """Mixed-use: both commercial and residential stubs → rent = 0."""
        r = _mock_resolver(comm_rate=None, res_rates=None)
        mix = UnitMix(one_br=2, floors=2)
        prop = _prop(city="Stubville", province="ON", property_type="Mixed-Use",
                     unit_mix=mix, total_sq_ft=4_000)
        rent, _ = r.resolve(prop)
        assert rent == 0.0

    def test_residential_all_null_stub_logs_missing(self):
        """Residential/Multi-Family with all-None stub → logs missing, returns 0."""
        store = MagicMock()
        r = _mock_resolver(res_rates=None, store=store)
        mix = UnitMix(one_br=3)
        prop = _prop(city="Stubville", province="ON", unit_mix=mix)
        rent, breakdown = r.resolve(prop)
        assert rent == 0.0
        store.log_missing_city.assert_called()
        assert any("no rate" in line.lower() or "⚠" in line for line in breakdown)

    def test_null_stub_triggers_log_missing_not_zero_passthrough(self):
        """Core regression: None rate must call log_missing, not produce $0 rent silently."""
        store = MagicMock()
        r = _mock_resolver(comm_rate=None, store=store)
        prop = _prop(city="Stubville", province="ON", property_type="Office",
                     total_sq_ft=5_000)
        with pytest.raises(ValueError):
            r.resolve(prop)
        store.log_missing_city.assert_called()

    def test_zero_rate_from_old_stub_would_have_silently_passed(self):
        """Documents the pre-fix behaviour: a mock returning 0 produces $0 rent,
        no error, and _has_rent=False in the analyzer.  This is NOT the current
        behaviour — it illustrates what the migration prevents."""
        r = _mock_resolver(comm_rate=0)
        prop = _prop(city="Stubville", province="ON", property_type="Office",
                     total_sq_ft=5_000, listing_date="2025-01-01")
        rent, _ = r.resolve(prop)
        # $0 rent is what used to happen — now only reachable with an explicit 0 mock
        assert rent == 0.0
        analyzer = CommercialPropertyAnalyzer(prop, _mock_resolver(comm_rate=0))
        assert analyzer._has_rent is False


# ═══════════════════════════════════════════════════════════════════════════════
# 4.  _resolve_residential with partially-populated city (None per-unit values)
# ═══════════════════════════════════════════════════════════════════════════════

class TestResolveResidentialPartialStubs:

    def _r_with_market(self, market):
        res = MagicMock()
        res.get_rates.return_value = market
        comm = MagicMock()
        comm.get_rent_per_sqft.return_value = None
        return RentResolver(comm, res)

    def test_none_unit_value_falls_through_to_avg(self):
        """Unit key present but value is None → falls through to city avg, not $0."""
        market = {"one_br": None, "two_br": 1_600, "unknown": 1_400}
        r = self._r_with_market(market)
        mix = UnitMix(one_br=1, two_br=1)
        prop = _prop(city="Ottawa", province="ON", unit_mix=mix)
        rent, breakdown = r.resolve(prop)
        # avg of real rates: (1600 + 1400) / 2 = 1500; one_br falls back to avg
        # one_br: 1500 * 1 * 12 = 18000; two_br: 1600 * 1 * 12 = 19200
        assert rent == pytest.approx((1_500 + 1_600) * 12)

    def test_none_values_excluded_from_city_avg(self):
        """None values must not count toward the city average rate."""
        market = {"one_br": 1_200, "two_br": None, "unknown": None}
        r = self._r_with_market(market)
        mix = UnitMix(one_br=1, two_br=1)
        prop = _prop(city="Ottawa", province="ON", unit_mix=mix)
        rent, _ = r.resolve(prop)
        # avg is only from one_br=1200; two_br falls back to avg=1200
        assert rent == pytest.approx(1_200 * 2 * 12)

    def test_all_none_market_falls_through_to_missing(self):
        """If get_rates returns None (all stubs), units without override are skipped."""
        r = self._r_with_market(None)
        mix = UnitMix(two_br=3)
        prop = _prop(city="Stubcity", province="ON", unit_mix=mix)
        rent, breakdown = r.resolve(prop)
        assert rent == 0.0
        assert any("no rate" in line.lower() for line in breakdown)

    def test_none_unit_value_with_override_uses_override(self):
        """Override always wins even when market has None for that key."""
        market = {"one_br": None, "two_br": 1_600}
        r = self._r_with_market(market)
        mix = UnitMix(one_br=2, one_br_rent=999.0)
        prop = _prop(city="Ottawa", province="ON", unit_mix=mix)
        rent, _ = r.resolve(prop)
        assert rent == pytest.approx(999 * 2 * 12)

    def test_zero_rates_excluded_from_avg_computation(self):
        """Explicit 0 values (if still present) must not lower the avg to zero."""
        # After migration zeros become None, but guard this at the avg level too.
        market = {"one_br": 1_200, "two_br": 1_600, "unknown": 0}
        r = self._r_with_market(market)
        mix = UnitMix(one_br=1, two_br=1, unknown=1)
        prop = _prop(city="Ottawa", province="ON", unit_mix=mix)
        rent, _ = r.resolve(prop)
        # unknown gets city avg = (1200 + 1600) / 2 = 1400 (0 is excluded)
        assert rent == pytest.approx((1_200 + 1_600 + 1_400) * 12)


# ═══════════════════════════════════════════════════════════════════════════════
# 5.  _reanalyze_all  (end-to-end)
# ═══════════════════════════════════════════════════════════════════════════════

def _minimal_property_record(city="Stubville", ptype="Office", **overrides):
    base = {
        "address":          f"1 Main St, {city}, ON",
        "mls_number":       "X99999",
        "status":           "active",
        "listing_date":     "2025-01-01",
        "asking_price":     500_000,
        "original_price":   500_000,
        "total_sq_ft":      5_000,
        "city":             city,
        "province":         "ON",
        "property_type":    ptype,
        "property_taxes":   7_000,
        "down_payment_pct": 0.20,
        "interest_rate":    0.055,
        "term_years":       25,
        "hold_years":       30,
        "expense_ratio":    None,
        "lease_type":       "Normal",
        "construction_cost": 0,
        "annual_rent":      None,
        "commercial_rent":  None,
        "residential_rent": None,
        "rent_manually_entered": False,
        "unit_mix": {"bachelor":0,"one_br":0,"two_br":0,"three_br":0,"four_br":0,"unknown":0,"floors":1},
        "floors": 1,
        "results": [],
    }
    base.update(overrides)
    return base


class TestReanalyzeAll:

    def _make_menu_with_stub_city(self, tmp_path, ptype="Office"):
        store = _make_store(tmp_path)
        store.save_property(_minimal_property_record(city="Stubcity", ptype=ptype))
        resolver = RentResolver(CommercialRentLoader(store), ResidentialRentLoader(store), store)
        menu = PropertyMenu(store, resolver)
        return menu, store

    def test_stub_city_property_counted_as_skipped(self, tmp_path, capsys):
        """_reanalyze_all must count properties in stub cities as skipped, not updated."""
        menu, _ = self._make_menu_with_stub_city(tmp_path)
        menu._reanalyze_all()
        out = capsys.readouterr().out
        assert "skipped" in out

    def test_stub_city_not_counted_as_updated(self, tmp_path, capsys):
        """A stub-city property must not appear in the updated count."""
        menu, _ = self._make_menu_with_stub_city(tmp_path)
        menu._reanalyze_all()
        out = capsys.readouterr().out
        # Expect "0/1 updated" pattern
        assert "0/1 updated" in out or "0/" in out

    def test_populated_city_property_counted_as_updated(self, tmp_path, capsys):
        """With real rates, _reanalyze_all must count the property as updated."""
        real_comm = {
            "Realcity": {
                "province": "ON",
                "types": {"Office": 20.0, "Retail": 30.0, "Industrial": 12.0, "Mixed-Use": 18.0}
            }
        }
        store = _make_store(tmp_path, comm_cities=real_comm)
        store.save_property(_minimal_property_record(city="Realcity", ptype="Office"))
        resolver = RentResolver(CommercialRentLoader(store), ResidentialRentLoader(store), store)
        menu = PropertyMenu(store, resolver)
        menu._reanalyze_all()
        out = capsys.readouterr().out
        assert "1/1 updated" in out

    def test_reanalyze_with_stub_does_not_produce_partial_income_metrics(self, tmp_path):
        """Core regression: stub city must NOT produce silent $0 income metrics."""
        menu, store = self._make_menu_with_stub_city(tmp_path)
        menu._reanalyze_all()
        props = store.load_properties()
        results = props[0].get("results", [])
        income_metrics = {"NOI", "Cap Rate", "Gross Rent Multiplier"}
        result_names = {r["metric"] for r in results}
        assert not income_metrics.intersection(result_names), \
            "Stub city must not produce income metrics (would be $0-based and wrong)"

    def test_reanalyze_multiple_properties_skips_stub_updates_real(self, tmp_path, capsys):
        """Mixed batch: one stub city + one real city → 1 updated, 1 skipped."""
        real_comm = {
            "Realcity": {
                "province": "ON",
                "types": {"Office": 20.0, "Retail": 30.0, "Industrial": 12.0, "Mixed-Use": 18.0}
            }
        }
        store = _make_store(tmp_path, comm_cities=real_comm)
        store.save_property(_minimal_property_record(city="Stubcity", ptype="Office"))
        store.save_property(_minimal_property_record(
            city="Realcity", ptype="Office",
            address="2 King St, Realcity, ON", mls_number="X11111"
        ))
        resolver = RentResolver(CommercialRentLoader(store), ResidentialRentLoader(store), store)
        menu = PropertyMenu(store, resolver)
        menu._reanalyze_all()
        out = capsys.readouterr().out
        assert "1/2 updated" in out
        assert "1 skipped" in out

    @pytest.mark.parametrize("ptype", ["Office", "Retail", "Industrial", "Retail-Office"])
    def test_stub_city_raises_for_each_commercial_type(self, tmp_path, ptype, capsys):
        """All pure commercial types in a stub city must be counted as skipped."""
        extra = {}
        if ptype == "Retail-Office":
            extra["unit_mix"] = {"bachelor":0,"one_br":0,"two_br":0,"three_br":0,
                                  "four_br":0,"unknown":0,"floors":2}
            extra["floors"] = 2
        menu, _ = self._make_menu_with_stub_city(tmp_path, ptype=ptype)
        menu._reanalyze_all()
        out = capsys.readouterr().out
        assert "skipped" in out, f"{ptype} stub should be counted as skipped"
