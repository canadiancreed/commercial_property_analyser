"""SQLite-specific behaviour for the property store.

The generic property CRUD contract is covered by test_data_store.py (which now runs
against SQLite unchanged). These tests cover what's new: real persistence, lossless
nested-field round-trips, the mirrored index columns, insertion ordering, and the
one-time JSON → SQLite migration guard.
"""
import json
import os
import sqlite3

from data.store import DataStore


def _store(tmp_path, name="props.db"):
    return DataStore(
        commercial_path=str(tmp_path / "comm.json"),
        residential_path=str(tmp_path / "res.json"),
        properties_path=str(tmp_path / name),
        missing_path=str(tmp_path / "miss.json"),
    )


def _rec(addr="1 Main St", listing="2025-01-01", **extra):
    r = {"address": addr, "listing_date": listing, "asking_price": 500_000,
         "city": "Ottawa", "province": "ON", "status": "active",
         "property_type": "Office"}
    r.update(extra)
    return r


class TestSqlitePersistence:
    def test_persists_across_instances(self, tmp_path):
        """A fresh DataStore at the same path sees previously-saved data (real DB)."""
        _store(tmp_path).save_property(_rec())
        props = _store(tmp_path).load_properties()
        assert len(props) == 1 and props[0]["address"] == "1 Main St"

    def test_nested_fields_roundtrip(self, tmp_path):
        s = _store(tmp_path)
        rec = _rec(unit_mix={"one_br": 3, "two_br": 2, "floors": 2},
                   results=[{"metric": "Cap Rate", "value": "6.00%", "grade": "A"}],
                   rent_breakdown=[{"type": "one_br", "rent": 1200}],
                   vacancy_rate=None, notes="unïcödé ✓")
        s.save_property(rec)
        loaded = s.load_properties()[0]
        assert loaded == rec

    def test_mirrored_columns_populated(self, tmp_path):
        s = _store(tmp_path)
        s.save_property(_rec(city="Guelph", asking_price=750_000, status="inactive"))
        conn = sqlite3.connect(str(tmp_path / "props.db"))
        row = conn.execute(
            "SELECT city, province, status, property_type, asking_price FROM properties"
        ).fetchone()
        conn.close()
        assert row == ("Guelph", "ON", "inactive", "Office", 750_000)

    def test_order_preserved_by_insertion(self, tmp_path):
        s = _store(tmp_path)
        for i in range(3):
            s.save_property(_rec(addr=f"{i} St"))
        assert [p["address"] for p in s.load_properties()] == ["0 St", "1 St", "2 St"]

    def test_resave_moves_to_end(self, tmp_path):
        """Re-saving an existing key appends it last — matches the old JSON behaviour."""
        s = _store(tmp_path)
        for i in range(3):
            s.save_property(_rec(addr=f"{i} St"))
        s.save_property(_rec(addr="0 St", asking_price=1))
        assert [p["address"] for p in s.load_properties()] == ["1 St", "2 St", "0 St"]

    def test_migrate_vacancy_rate_clears_only_non_null(self, tmp_path):
        s = _store(tmp_path)
        s.save_property(_rec("1 St", vacancy_rate=0.05))
        s.save_property(_rec("2 St", vacancy_rate=None))
        assert s.migrate_vacancy_rate_to_null() == 1
        assert all(p["vacancy_rate"] is None for p in s.load_properties())
        assert s.migrate_vacancy_rate_to_null() == 0  # idempotent


class TestJsonMigration:
    def _legacy(self, tmp_path, records):
        p = str(tmp_path / "properties.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"properties": records}, f)
        return p

    def test_import_from_json(self, tmp_path):
        legacy = self._legacy(tmp_path, [_rec("1 St"), _rec("2 St")])
        s = _store(tmp_path)
        assert s.import_properties_from_json(legacy) == 2
        assert {p["address"] for p in s.load_properties()} == {"1 St", "2 St"}

    def test_ensure_migrated_runs_once(self, tmp_path):
        legacy = self._legacy(tmp_path, [_rec("1 St"), _rec("2 St")])
        s = _store(tmp_path)
        assert s.ensure_properties_migrated(legacy) == 2
        assert s.ensure_properties_migrated(legacy) == 0   # flag set → no-op
        assert len(s.load_properties()) == 2               # no duplicates

    def test_ensure_migrated_no_reimport_after_delete(self, tmp_path):
        legacy = self._legacy(tmp_path, [_rec("1 St")])
        s = _store(tmp_path)
        s.ensure_properties_migrated(legacy)
        s.delete_property(0)
        assert s.ensure_properties_migrated(legacy) == 0   # guard prevents re-import
        assert s.load_properties() == []

    def test_ensure_migrated_no_json(self, tmp_path):
        s = _store(tmp_path)
        assert s.ensure_properties_migrated(str(tmp_path / "nope.json")) == 0
        assert s.load_properties() == []

    def test_import_leaves_json_untouched(self, tmp_path):
        legacy = self._legacy(tmp_path, [_rec("1 St")])
        _store(tmp_path).import_properties_from_json(legacy)
        assert os.path.exists(legacy)


class TestRateTables:
    """Commercial + residential rents now live in their own SQLite tables, migrated
    once from the legacy JSON and thereafter authoritative."""

    def _seed_comm(self, tmp_path, cities):
        (tmp_path / "comm.json").write_text(json.dumps({"cities": cities}), encoding="utf-8")

    def _seed_res(self, tmp_path, cities):
        (tmp_path / "res.json").write_text(json.dumps({"cities": cities}), encoding="utf-8")

    def test_commercial_migrates_and_persists(self, tmp_path):
        self._seed_comm(tmp_path, {"Ottawa": {"province": "ON",
            "types": {"Office": 20.0, "Retail": 30.0}, "source": "Src: broker"}})
        idx = _store(tmp_path).load_commercial_rates()
        assert idx["ottawa"]["office"] == 20.0 and idx["ottawa"]["retail"] == 30.0
        # Persisted in the DB — a fresh instance still sees it
        assert _store(tmp_path).load_commercial_rates()["ottawa"]["office"] == 20.0

    def test_commercial_source_migrated(self, tmp_path):
        self._seed_comm(tmp_path, {"Ottawa": {"province": "ON",
            "types": {"Office": 20.0}, "source": "Est: model"}})
        assert _store(tmp_path).load_commercial_sources()["ottawa"] == "Est: model"

    def test_residential_migrates_with_nulls(self, tmp_path):
        self._seed_res(tmp_path, {"Ottawa": {"province": "ON",
            "units": {"one_br": 1200, "two_br": None}}})
        idx = _store(tmp_path).load_residential_rates()
        assert idx["ottawa"]["one_br"] == 1200.0 and idx["ottawa"]["two_br"] is None

    def test_rows_live_in_dedicated_tables(self, tmp_path):
        self._seed_comm(tmp_path, {"Ottawa": {"province": "ON", "types": {"Office": 20.0}}})
        self._seed_res(tmp_path, {"Ottawa": {"province": "ON", "units": {"one_br": 1200}}})
        s = _store(tmp_path)
        s.load_commercial_rates(); s.load_residential_rates()  # trigger migration
        conn = sqlite3.connect(str(tmp_path / "props.db"))
        c = conn.execute("SELECT city, property_type, rate FROM commercial_rents").fetchone()
        r = conn.execute("SELECT city, unit_type, rent FROM residential_rents").fetchone()
        conn.close()
        assert c == ("Ottawa", "Office", 20.0)
        assert r == ("Ottawa", "one_br", 1200.0)

    def test_save_commercial_replaces_city(self, tmp_path):
        s = _store(tmp_path)
        s.save_commercial_rates("Guelph", "ON", {"Office": 18.0, "Retail": 25.0})
        s.save_commercial_rates("Guelph", "ON", {"Office": 19.0})
        assert s.load_commercial_rates()["guelph"] == {"office": 19.0}

    def test_save_residential_replaces_city(self, tmp_path):
        s = _store(tmp_path)
        s.save_residential_rates("Guelph", "ON", {"one_br": 1000, "two_br": 1400})
        s.save_residential_rates("Guelph", "ON", {"one_br": 1100})
        assert s.load_residential_rates()["guelph"] == {"one_br": 1100.0}

    def test_migration_guard_does_not_reclobber_edits(self, tmp_path):
        self._seed_comm(tmp_path, {"Ottawa": {"province": "ON", "types": {"Office": 20.0}}})
        s = _store(tmp_path)
        s.load_commercial_rates()                                   # migrate Ottawa=20
        s.save_commercial_rates("Ottawa", "ON", {"Office": 99.0})   # user edit
        # A fresh instance must not re-import the JSON over the edit (guard persisted)
        assert _store(tmp_path).load_commercial_rates()["ottawa"]["office"] == 99.0
