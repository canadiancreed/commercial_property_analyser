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
    # v5.0.0: all data lives in the DB (empty, unseeded for tests).
    return DataStore(properties_path=str(tmp_path / name))


def _seeded_store(tmp_path, name="seeded.db"):
    return DataStore(properties_path=str(tmp_path / name), seed=True)


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
    """Commercial + residential rents live in their own SQLite tables (v5.0.0: seeded
    from data/seeds, then authoritative)."""

    def test_commercial_saves_and_persists(self, tmp_path):
        _store(tmp_path).save_commercial_rates(
            "Ottawa", "ON", {"Office": 20.0, "Retail": 30.0})
        idx = _store(tmp_path).load_commercial_rates()   # a fresh instance still sees it
        assert idx["ottawa"]["office"] == 20.0 and idx["ottawa"]["retail"] == 30.0

    def test_residential_nulls_persist(self, tmp_path):
        _store(tmp_path).save_residential_rates("Ottawa", "ON", {"one_br": 1200, "two_br": None})
        idx = _store(tmp_path).load_residential_rates()
        assert idx["ottawa"]["one_br"] == 1200.0 and idx["ottawa"]["two_br"] is None

    def test_rows_live_in_dedicated_tables(self, tmp_path):
        s = _store(tmp_path)
        s.save_commercial_rates("Ottawa", "ON", {"Office": 20.0})
        s.save_residential_rates("Ottawa", "ON", {"one_br": 1200})
        conn = sqlite3.connect(str(tmp_path / "props.db"))
        c = conn.execute("SELECT city, property_type, rate FROM commercial_rents").fetchone()
        r = conn.execute("SELECT city, unit_type, rent FROM residential_rents").fetchone()
        conn.close()
        assert c == ("Ottawa", "Office", 20.0)
        assert r == ("Ottawa", "one_br", 1200.0)

    def test_seeded_store_has_shipped_rates_and_sources(self, tmp_path):
        s = _seeded_store(tmp_path)
        assert len(s.load_commercial_rates()) > 50          # the shipped rate cities
        assert any(src for src in s.load_commercial_sources().values())

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

    def test_seed_guard_does_not_reclobber_edits(self, tmp_path):
        s = _seeded_store(tmp_path)
        s.save_commercial_rates("Ottawa", "ON", {"Office": 99.0})   # user edit
        # A fresh seeded instance must not re-seed over the edit (guard persisted).
        assert _seeded_store(tmp_path).load_commercial_rates()["ottawa"]["office"] == 99.0


class TestSchemaVersion:
    def _user_version(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "props.db"))
        v = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        return v

    def test_fresh_db_stamped_current(self, tmp_path):
        _store(tmp_path).load_properties()                 # triggers _connect
        assert self._user_version(tmp_path) == DataStore.SCHEMA_VERSION

    def test_old_db_upgraded_in_place(self, tmp_path):
        s = _store(tmp_path)
        s.load_properties()
        conn = sqlite3.connect(str(tmp_path / "props.db"))  # simulate pre-versioning DB
        conn.execute("PRAGMA user_version = 0"); conn.commit(); conn.close()
        s.load_properties()                                 # next connect restamps
        assert self._user_version(tmp_path) == DataStore.SCHEMA_VERSION


class TestCityDataStubsAndDelete:
    # ── 4.12.5: delete a city's rate entry (both tables) ──────────────────────
    def test_delete_city_rates_removes_both_tables(self, tmp_path):
        s = _store(tmp_path)
        s.save_commercial_city("Walkerton", "ON", {"Office": 12.5})
        s.save_residential_city("Walkerton", "ON", {"one_br": 1100})
        n = s.delete_city_rates("walkerton", "on")   # caseless
        assert n >= 2
        assert "walkerton" not in s.load_commercial_rates()
        assert "walkerton" not in s.load_residential_rates()

    def test_delete_city_rates_clears_missing_entry(self, tmp_path):
        s = _store(tmp_path)
        s.ensure_city_in_rates("Erin", "ON")         # stubs + a missing_rent_data entry
        before = s.read_app_data("missing_rent_data")
        assert any(k.lower() == "erin, on" for k in before)
        s.delete_city_rates("Erin", "ON")
        after = s.read_app_data("missing_rent_data")
        assert not any(k.lower() == "erin, on" for k in after)

    # ── 4.12.6: blank demographics / distances stubs on a new city ────────────
    def test_ensure_demographics_stub_created_once(self, tmp_path):
        s = _store(tmp_path)
        assert s.ensure_city_in_demographics("St Marys") is True
        assert s.ensure_city_in_demographics("st marys") is False   # idempotent, caseless
        assert s.load_city_demographics()["st marys"]["population"] is None

    def test_ensure_distances_stub_created_once(self, tmp_path):
        s = _store(tmp_path)
        assert s.ensure_city_in_distances("st marys") is True
        assert s.ensure_city_in_distances("St Marys") is False      # idempotent, Title key
        assert s.load_city_distances()["St Marys"]["distance_km"] is None

    def test_ensure_reference_data_reports_new_city(self, tmp_path):
        s = _store(tmp_path)
        created = s.ensure_city_reference_data("Orangeville", "ON")
        assert created == {"rates": True, "demographics": True,
                           "distances": True, "any_created": True}

    def test_ensure_reference_data_quiet_when_present(self, tmp_path):
        s = _store(tmp_path)
        s.save_commercial_city("Guelph", "ON", {"Office": 15.0})
        s.save_residential_city("Guelph", "ON", {"one_br": 1200})
        s.ensure_city_in_demographics("Guelph")
        s.ensure_city_in_distances("Guelph")
        created = s.ensure_city_reference_data("Guelph", "ON")
        assert created["rates"] is False and created["any_created"] is False

    # ── delete a city's demographics / distance row (City data tab) ───────────
    def test_delete_city_demographics_removes_row(self, tmp_path):
        s = _store(tmp_path)
        s.save_city_demographics("Stratford", {"population": 33000, "population_2016": 31000})
        assert "stratford" in s.load_city_demographics()
        n = s.delete_city_demographics("STRATFORD")           # caseless
        assert n == 1
        assert "stratford" not in s.load_city_demographics()

    def test_delete_city_demographics_absent_is_noop(self, tmp_path):
        s = _store(tmp_path)
        assert s.delete_city_demographics("Nowhere") == 0

    def test_delete_city_distance_removes_row(self, tmp_path):
        s = _store(tmp_path)
        s.save_city_distance("Stratford", {"distance_km": 60, "nearest_centre": "London"})
        assert "Stratford" in s.load_city_distances()
        n = s.delete_city_distance("stratford")               # caseless
        assert n == 1
        assert "Stratford" not in s.load_city_distances()

    def test_delete_city_distance_absent_is_noop(self, tmp_path):
        s = _store(tmp_path)
        assert s.delete_city_distance("Nowhere") == 0


class TestCityKeyAlignment:
    """v5.1.7: Fenelon Falls / St Marys were misspelled in the distances seed, so their
    distance rows never joined to the matching demographics/properties rows."""

    def test_seeded_distance_keys_align_with_demographics(self, tmp_path):
        s = _seeded_store(tmp_path)
        demo = set(s.load_city_demographics())                      # lowercase keys
        dist = {k.lower() for k in s.load_city_distances()}         # display -> lowercase
        for city in ("fenelon falls", "st marys"):
            assert city in demo, f"{city} missing from demographics seed"
            assert city in dist, f"{city} missing from distances seed"
        # The two tables must agree on exactly the same set of cities.
        assert demo == dist

    def test_migration_repairs_misspelled_distance_keys(self, tmp_path):
        # Simulate a DB seeded before the fix: bad keys + a stamp one version behind.
        s = _store(tmp_path)
        s.load_properties()                                         # create schema
        conn = sqlite3.connect(str(tmp_path / "props.db"))
        conn.execute("INSERT INTO city_distances (city_key, city, distance_km, nearest_centre)"
                     " VALUES ('fenlon falls','Fenlon Falls',68.0,'Peterborough'),"
                     "        ('st. marys','St. Marys',42.0,'London')")
        conn.execute("PRAGMA user_version = 3")
        conn.commit(); conn.close()
        s.load_properties()                                         # next connect migrates
        dist = s.load_city_distances()
        keys = {k.lower() for k in dist}
        assert "fenelon falls" in keys and "st marys" in keys
        assert "fenlon falls" not in keys and "st. marys" not in keys
        assert dist["Fenelon Falls"]["distance_km"] == 68.0
        assert dist["St Marys"]["nearest_centre"] == "London"

    def test_migration_repairs_misspelled_rent_keys(self, tmp_path):
        # A DB seeded before the v5 fix: misspelled rent rows (`st. marys`, `fenlon falls`)
        # stamped one schema version behind so the migration runs on next connect.
        s = _store(tmp_path)
        s.load_properties()                                         # create schema
        conn = sqlite3.connect(str(tmp_path / "props.db"))
        conn.execute("INSERT INTO commercial_rents (city_key, city, province, property_type, rate, source)"
                     " VALUES ('st. marys','St. Marys','ON','Retail',16.0,'Src'),"
                     "        ('fenlon falls','Fenlon Falls','ON','Retail',12.0,'Src')")
        conn.execute("INSERT INTO residential_rents (city_key, city, province, unit_type, rent)"
                     " VALUES ('st. marys','St. Marys','ON','one_br',1300.0),"
                     "        ('fenlon falls','Fenlon Falls','ON','one_br',1100.0)")
        conn.execute("PRAGMA user_version = 4")
        conn.commit(); conn.close()
        s.load_properties()                                         # next connect migrates
        conn = sqlite3.connect(str(tmp_path / "props.db"))
        comm = {r[0] for r in conn.execute("SELECT DISTINCT city_key FROM commercial_rents")}
        res  = {r[0] for r in conn.execute("SELECT DISTINCT city_key FROM residential_rents")}
        rate = conn.execute("SELECT rate, city FROM commercial_rents "
                            "WHERE city_key='st marys' AND property_type='Retail'").fetchone()
        fen  = conn.execute("SELECT rate, city FROM commercial_rents "
                            "WHERE city_key='fenelon falls' AND property_type='Retail'").fetchone()
        uv   = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        assert {"st marys", "fenelon falls"} <= comm
        assert "st. marys" not in comm and "fenlon falls" not in comm
        assert {"st marys", "fenelon falls"} <= res
        assert "st. marys" not in res and "fenlon falls" not in res
        assert rate == (16.0, "St Marys")       # rate + display casing repointed, not lost
        assert fen  == (12.0, "Fenelon Falls")
        assert uv == DataStore.SCHEMA_VERSION

    def test_seeded_rent_keys_use_canonical_city_spellings(self, tmp_path):
        # Guards the seed fix: the rent seeds must use the canonical keys the rent lookup
        # (and demographics/distances) use, not the misspelled `St. Marys` / `Fenlon Falls`.
        s = _seeded_store(tmp_path)
        comm = s.load_commercial_rates()
        res  = s.load_residential_rates()
        for canon, bad in (("st marys", "st. marys"), ("fenelon falls", "fenlon falls")):
            assert canon in comm and bad not in comm
            assert canon in res  and bad not in res


class TestDbExplorer:
    # ── 5.1.0: read-only DB introspection + query ─────────────────────────────
    def test_list_tables_includes_core_with_counts(self, tmp_path):
        s = _store(tmp_path)
        s.save_property(_rec())
        tbls = {t["name"]: t["rows"] for t in s.list_tables()}
        assert "properties" in tbls and "config" in tbls
        assert "sqlite_sequence" not in tbls   # internals excluded
        assert tbls["properties"] == 1

    def test_table_schema_reports_columns_and_pk(self, tmp_path):
        cols = {c["name"]: c for c in _store(tmp_path).table_schema("config")}
        assert set(cols) == {"name", "json", "updated_at"}
        assert cols["name"]["pk"] is True

    def test_table_schema_unknown_table_empty(self, tmp_path):
        assert _store(tmp_path).table_schema("nope; drop table x") == []

    def test_table_page_returns_rows_and_total(self, tmp_path):
        s = _store(tmp_path)
        for i in range(3):
            s.save_property(_rec(addr=f"{i} St"))
        page = s.table_page("properties", limit=2, offset=0)
        assert page["total"] == 3 and len(page["rows"]) == 2
        assert "address" in page["columns"]

    def test_run_readonly_query_returns_data(self, tmp_path):
        s = _store(tmp_path)
        s.save_commercial_rates("Ottawa", "ON", {"Office": 20.0})
        res = s.run_readonly_query("SELECT city, rate FROM commercial_rents")
        assert res["columns"] == ["city", "rate"]
        assert res["rows"] == [["Ottawa", 20.0]]

    def test_run_readonly_query_rejects_writes(self, tmp_path):
        import pytest
        s = _store(tmp_path)
        s.save_property(_rec())
        with pytest.raises(ValueError):
            s.run_readonly_query("DELETE FROM properties")
        assert s.table_page("properties")["total"] == 1   # untouched
