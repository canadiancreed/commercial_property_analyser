import json
import os
import shutil
import sqlite3
from datetime import date


def _migrate_v4_fix_city_distance_keys(conn) -> None:
    """v5.1.7: repair two city_distances rows whose keys were misspelled in the seed
    (`Fenlon Falls`, `St. Marys`) so they match the canonical spelling used by the
    properties and city_demographics (`Fenelon Falls`, `St Marys`). Without this, those
    towns' distance data never joined to their demographics and the properties silently
    lost their distance-to-centre input. Existing DBs seeded before the seed was fixed
    still carry the bad rows, so correct them in place."""
    fixes = [
        ("fenlon falls", "fenelon falls", "Fenelon Falls"),
        ("st. marys", "st marys", "St Marys"),
    ]
    for bad, good, good_city in fixes:
        if not conn.execute(
                "SELECT 1 FROM city_distances WHERE city_key=?", (bad,)).fetchone():
            continue
        if conn.execute(
                "SELECT 1 FROM city_distances WHERE city_key=?", (good,)).fetchone():
            # Canonical row already exists — just drop the stale duplicate.
            conn.execute("DELETE FROM city_distances WHERE city_key=?", (bad,))
        else:
            conn.execute(
                "UPDATE city_distances SET city_key=?, city=? WHERE city_key=?",
                (good, good_city, bad))


def _migrate_v5_fix_rent_city_keys(conn) -> None:
    """v5.7.1: canonicalize misspelled rent-table city keys. The v4 migration fixed these
    same misspellings in city_distances (Fenlon Falls→Fenelon Falls, St. Marys→St Marys),
    but commercial_rents and residential_rents carried them too, from the rate seed. The
    rent lookup (CommercialRentLoader / ResidentialRentLoader) keys on the canonical form —
    as properties, demographics and distances do — so these rows were orphaned and the
    affected listings resolved no market rent. Repoint them. `UPDATE OR REPLACE` lets the
    real rate win over a canonical stub on the rare DB that already holds both. Table names
    are trusted literals; the keys are passed as parameters."""
    fixes = [
        ("st. marys",    "st marys",      "St Marys"),
        ("fenlon falls", "fenelon falls", "Fenelon Falls"),
    ]
    for table in ("commercial_rents", "residential_rents"):
        for bad, good, good_city in fixes:
            if conn.execute(
                    f"SELECT 1 FROM {table} WHERE city_key=? LIMIT 1", (bad,)).fetchone():
                conn.execute(
                    f"UPDATE OR REPLACE {table} "
                    "SET city_key=?, city=? WHERE city_key=?", (good, good_city, bad))


class DataStore:
    """
    Owns all JSON file loading and saving.
    All other classes call DataStore; none touch the filesystem directly.
    """

    PROPERTIES_PATH  = "properties.db"          # the SQLite database (all data lives here)
    PROPERTIES_JSON_LEGACY = "properties.json"  # one-time legacy import (import_properties_from_json)

    def __init__(self,
                 properties_path:  str = PROPERTIES_PATH,
                 seed:             bool = False,
                 # Legacy path args retained for signature compatibility; no longer read
                 # (v5.0.0 seeds all reference data from data/seeds into the DB).
                 commercial_path=None, residential_path=None, missing_path=None,
                 demographics_path=None, distances_path=None):
        self._properties_path = properties_path
        # When True, the first data access seeds the DB from data/seeds. The app/CLI pass
        # seed=True; tests leave it False for a controlled, empty DB (read_config /
        # read_app_data still resolve individual docs from the embedded defaults).
        self._seed = seed

    @staticmethod
    def _read(path: str) -> dict:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Data file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _write(path: str, data: dict):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        # Keep a rollback copy of the last good file; copy (not rename) so
        # the live file always exists even if we crash before the replace.
        if os.path.exists(path):
            shutil.copy2(path, path + ".bak")
        os.replace(tmp, path)

    # ------------------------------------------------------------------
    # Settings / reference config (SQLite-backed: the `config` table)
    #
    # One JSON document per logical name (financing, score_weights, screener,
    # underwriting, industrial_*, vacancy_rates, geographic_crosswalk, ui_prefs).
    # Seeded once from data/seeds (ensure_seeded); the DB is then the live source.
    # (v5.0.0: no .json file is read.)
    # ------------------------------------------------------------------

    def _read_doc(self, table: str, name: str, default=None, fallback=None) -> dict:
        """Shared reader for the `config` / `app_data` document tables. Returns the row's
        doc; if absent, seeds from `default` (an explicit dict) else the embedded
        `fallback` dict, inserting it so later reads are stable."""
        self._maybe_seed()
        conn = self._connect()
        try:
            row = conn.execute(f"SELECT json FROM {table} WHERE name = ?", (name,)).fetchone()
            if row is not None:
                return json.loads(row["json"])
            seed = default if default is not None else fallback
            if not seed:
                return {}
            # Round-trip through JSON so callers never receive (and can't mutate) the
            # shared embedded-seed object.
            seed_json = json.dumps(seed, ensure_ascii=False)
            conn.execute(
                f"INSERT OR IGNORE INTO {table} (name, json, updated_at) VALUES (?, ?, ?)",
                (name, seed_json, date.today().isoformat()))
            conn.commit()
            return json.loads(seed_json)
        finally:
            conn.close()

    def _write_doc(self, table: str, name: str, doc: dict) -> dict:
        conn = self._connect()
        try:
            conn.execute(
                f"INSERT OR REPLACE INTO {table} (name, json, updated_at) VALUES (?, ?, ?)",
                (name, json.dumps(doc, ensure_ascii=False), date.today().isoformat()))
            conn.commit()
        finally:
            conn.close()
        return doc

    def read_config(self, name: str, default: dict = None) -> dict:
        """Return the config document for ``name`` (seeded from data/seeds on first use).
        ``default`` is an optional explicit fallback dict used only if the row and the
        embedded seed are both absent."""
        from data import seeds
        return self._read_doc("config", name, default=default,
                              fallback=seeds.CONFIG_DEFAULTS.get(name))

    def write_config(self, name: str, cfg: dict) -> dict:
        """Upsert the config document for ``name`` (the DB is the live source)."""
        return self._write_doc("config", name, cfg)

    def read_app_data(self, name: str, default: dict = None) -> dict:
        """Return a runtime-state document (missing-city reports, price-check progress,
        the fetched interest-rate cache). Seeds from data/seeds on first use."""
        from data import seeds
        return self._read_doc("app_data", name, default=default,
                              fallback=seeds.APP_DATA_DEFAULTS.get(name))

    def write_app_data(self, name: str, doc: dict) -> dict:
        """Upsert a runtime-state document (the DB is the live source)."""
        return self._write_doc("app_data", name, doc)

    # ------------------------------------------------------------------
    # Seeding (v5.0.0): the DB is the single source of truth. On first use the
    # reference/config/runtime data is populated from data/seeds (data-as-code,
    # generated from the former config/ + json/ files). INSERT OR IGNORE so it
    # never clobbers edits; a meta flag makes it run once per database. No .json
    # file is read or written at runtime.
    # ------------------------------------------------------------------

    def ensure_seeded(self) -> None:
        """Populate config / app_data / rate tables / city tables from the embedded
        seed on first use. Idempotent (meta-guarded + INSERT OR IGNORE); instance-
        cached so repeated lookups don't re-query the guard."""
        if getattr(self, "_seeded_checked", False):
            return
        conn = self._connect()
        try:
            done = conn.execute("SELECT value FROM meta WHERE key = 'seeded'").fetchone()
            if not done:
                from data import seeds
                now = date.today().isoformat()
                for name, doc in seeds.CONFIG_DEFAULTS.items():
                    conn.execute(
                        "INSERT OR IGNORE INTO config (name, json, updated_at) VALUES (?, ?, ?)",
                        (name, json.dumps(doc, ensure_ascii=False), now))
                for name, doc in seeds.APP_DATA_DEFAULTS.items():
                    conn.execute(
                        "INSERT OR IGNORE INTO app_data (name, json, updated_at) VALUES (?, ?, ?)",
                        (name, json.dumps(doc, ensure_ascii=False), now))
                for city, cdata in seeds.COMMERCIAL_RATES.get("cities", {}).items():
                    ck = city.strip().lower(); prov = cdata.get("province"); src = cdata.get("source") or ""
                    for ptype, rate in cdata.get("types", {}).items():
                        conn.execute(
                            "INSERT OR IGNORE INTO commercial_rents "
                            "(city_key, city, province, property_type, rate, source) VALUES (?,?,?,?,?,?)",
                            (ck, city, prov, ptype, rate, src))
                for city, cdata in seeds.RESIDENTIAL_RATES.get("cities", {}).items():
                    ck = city.strip().lower(); prov = cdata.get("province")
                    for unit, rent in cdata.get("units", {}).items():
                        conn.execute(
                            "INSERT OR IGNORE INTO residential_rents "
                            "(city_key, city, province, unit_type, rent) VALUES (?,?,?,?,?)",
                            (ck, city, prov, unit, rent))
                for key, d in seeds.CITY_DEMOGRAPHICS.items():
                    ck = (key or "").strip().lower()
                    conn.execute(
                        "INSERT OR IGNORE INTO city_demographics "
                        "(city_key, city, population, population_2016, growth_pct_annual, source, notes) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (ck, key.strip().title(), d.get("population"), d.get("population_2016"),
                         d.get("growth_pct_annual"), d.get("source", ""), d.get("notes", "")))
                for city, d in seeds.CITY_DISTANCES.items():
                    ck = (city or "").strip().lower()
                    conn.execute(
                        "INSERT OR IGNORE INTO city_distances "
                        "(city_key, city, distance_km, nearest_centre) VALUES (?,?,?,?)",
                        (ck, city.strip(), d.get("distance_km"), d.get("nearest_centre", "")))
                conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES ('seeded', ?)", (now,))
                conn.commit()
        finally:
            conn.close()
        self._seeded_checked = True

    def _maybe_seed(self) -> None:
        """Lazy seed trigger used by the data accessors — seeds only when this store opted
        in (seed=True). Tests (seed=False) keep an empty DB; read_config / read_app_data
        still resolve individual docs from the embedded defaults."""
        if self._seed:
            self.ensure_seeded()

    def ensure_rates_migrated(self) -> None:
        """Back-compat alias used by the rate accessors — gated by the seed flag."""
        self._maybe_seed()

    # ------------------------------------------------------------------
    # Commercial rates
    # ------------------------------------------------------------------

    def load_commercial_rates(self) -> dict:
        """Returns {city_lower: {type_lower: rate}} for fast lookup."""
        self.ensure_rates_migrated()
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT city_key, property_type, rate FROM commercial_rents"
            ).fetchall()
        finally:
            conn.close()
        index = {}
        for r in rows:
            index.setdefault(r["city_key"], {})[r["property_type"].strip().lower()] = r["rate"]
        return index

    def load_commercial_sources(self) -> dict:
        """Returns {city_lower: source_string} from the commercial rate table.

        The per-city ``source`` field is prefixed ``Src:`` (sourced from a broker
        report) or ``Est:`` (estimate); used to grade rate confidence.
        """
        self.ensure_rates_migrated()
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT city_key, source FROM commercial_rents"
            ).fetchall()
        finally:
            conn.close()
        return {r["city_key"]: (r["source"] or "") for r in rows}

    def save_commercial_rates(self, city: str, province: str, rates: dict):
        """Replace a city's commercial rates (mirrors the old whole-city overwrite)."""
        self.ensure_rates_migrated()
        city_key = city.strip().lower()
        conn = self._connect()
        try:
            conn.execute("DELETE FROM commercial_rents WHERE city_key = ?", (city_key,))
            for ptype, rate in rates.items():
                conn.execute(
                    "INSERT INTO commercial_rents "
                    "(city_key, city, province, property_type, rate, source) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (city_key, city, province, ptype, rate, None),
                )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Residential rates
    # ------------------------------------------------------------------

    def load_residential_rates(self) -> dict:
        """Returns {city_lower: {unit_type: monthly_rent_or_None}} for fast lookup."""
        self.ensure_rates_migrated()
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT city_key, unit_type, rent FROM residential_rents"
            ).fetchall()
        finally:
            conn.close()
        index = {}
        for r in rows:
            rent = float(r["rent"]) if r["rent"] is not None else None
            index.setdefault(r["city_key"], {})[r["unit_type"]] = rent
        return index

    def save_residential_rates(self, city: str, province: str, units: dict):
        """Replace a city's residential rates (mirrors the old whole-city overwrite)."""
        self.ensure_rates_migrated()
        city_key = city.strip().lower()
        conn = self._connect()
        try:
            conn.execute("DELETE FROM residential_rents WHERE city_key = ?", (city_key,))
            for unit, rent in units.items():
                conn.execute(
                    "INSERT INTO residential_rents "
                    "(city_key, city, province, unit_type, rent) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (city_key, city, province, unit, rent),
                )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Editable rate views (city + province + per-type/unit values)
    # ------------------------------------------------------------------

    def load_commercial_rate_rows(self) -> list:
        """Editable view: [{city, province, types: {Type: rate}, source}] by city."""
        self.ensure_rates_migrated()
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT city_key, city, province, property_type, rate, source "
                "FROM commercial_rents ORDER BY city, property_type"
            ).fetchall()
        finally:
            conn.close()
        out = {}
        for r in rows:
            e = out.setdefault(r["city_key"], {
                "city": r["city"], "province": r["province"],
                "types": {}, "source": r["source"] or "",
            })
            e["types"][r["property_type"]] = r["rate"]
        return sorted(out.values(), key=lambda e: (e["city"] or "").lower())

    def load_residential_rate_rows(self) -> list:
        """Editable view: [{city, province, units: {unit: rent}}] by city."""
        self.ensure_rates_migrated()
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT city_key, city, province, unit_type, rent "
                "FROM residential_rents ORDER BY city, unit_type"
            ).fetchall()
        finally:
            conn.close()
        out = {}
        for r in rows:
            e = out.setdefault(r["city_key"], {
                "city": r["city"], "province": r["province"], "units": {},
            })
            e["units"][r["unit_type"]] = r["rent"]
        return sorted(out.values(), key=lambda e: (e["city"] or "").lower())

    # ------------------------------------------------------------------
    # Property analyses (SQLite-backed)
    #
    # Properties are the only high-churn, frequently-rewritten data, so they live
    # in a SQLite database (self._properties_path) rather than one JSON file that
    # was fully rewritten (all ~8 MB) on every single save. Each record is stored
    # losslessly as a JSON blob in `data`; a few columns (city/province/status/
    # type/price) are mirrored for indexing and future queries. The public API —
    # load/save/delete/update and the index-based positions — is unchanged, so no
    # other module needs to know the storage changed. Rates / missing / progress
    # stay JSON (read-mostly reference data).
    # ------------------------------------------------------------------

    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS properties (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            address       TEXT NOT NULL,
            listing_date  TEXT NOT NULL DEFAULT '',
            city          TEXT,
            province      TEXT,
            status        TEXT,
            property_type TEXT,
            asking_price  REAL,
            data          TEXT NOT NULL,
            UNIQUE(address, listing_date)
        );
        CREATE INDEX IF NOT EXISTS idx_properties_city   ON properties(city);
        CREATE INDEX IF NOT EXISTS idx_properties_status ON properties(status);

        CREATE TABLE IF NOT EXISTS commercial_rents (
            city_key      TEXT NOT NULL,          -- lowercased lookup key
            city          TEXT NOT NULL,          -- display casing
            province      TEXT,
            property_type TEXT NOT NULL,          -- 'Office', 'Retail', ...
            rate          REAL,                   -- $/sqft, NULL = unfilled stub
            source        TEXT,                   -- per-city 'Src:'/'Est:' provenance
            PRIMARY KEY (city_key, property_type)
        );
        CREATE TABLE IF NOT EXISTS residential_rents (
            city_key  TEXT NOT NULL,              -- lowercased lookup key
            city      TEXT NOT NULL,              -- display casing
            province  TEXT,
            unit_type TEXT NOT NULL,              -- 'bachelor', 'one_br', ...
            rent      REAL,                       -- monthly rent, NULL = unfilled stub
            PRIMARY KEY (city_key, unit_type)
        );

        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

        -- Settings/reference config: one JSON document per logical name ('financing',
        -- 'score_weights', 'screener', 'underwriting', 'industrial_*', 'vacancy_rates',
        -- 'geographic_crosswalk', 'ui_prefs'). Seeded once from data/seeds on first run,
        -- then this table is the live source. (v5.0.0: all config moved here.)
        CREATE TABLE IF NOT EXISTS config (
            name       TEXT PRIMARY KEY,
            json       TEXT NOT NULL,
            updated_at TEXT
        );

        -- Runtime-state documents (not user "settings"): the missing-city reports,
        -- price-check progress, and the fetched interest-rate cache. (v5.0.0)
        CREATE TABLE IF NOT EXISTS app_data (
            name       TEXT PRIMARY KEY,
            json       TEXT NOT NULL,
            updated_at TEXT
        );

        -- Per-city reference data (was city_demographics.json / city_distances.json). (v5.0.0)
        CREATE TABLE IF NOT EXISTS city_demographics (
            city_key          TEXT PRIMARY KEY,   -- lowercased lookup key
            city              TEXT NOT NULL,       -- display casing
            population        INTEGER,
            population_2016   INTEGER,
            growth_pct_annual REAL,
            source            TEXT,
            notes             TEXT
        );
        CREATE TABLE IF NOT EXISTS city_distances (
            city_key       TEXT PRIMARY KEY,       -- lowercased lookup key
            city           TEXT NOT NULL,          -- display casing (keys the distances view)
            distance_km    REAL,
            nearest_centre TEXT
        );
    """

    # Current on-disk schema version (SQLite PRAGMA user_version). The baseline schema
    # above is version 1. When the schema changes in a future release, bump this and add
    # the forward step to _MIGRATIONS below; _apply_migrations runs the pending steps and
    # restamps user_version on the next connect. Keeps old databases upgradable in place.
    #   v2 — added the `config` table (created above via IF NOT EXISTS, so existing DBs
    #        gain it on connect; no data step needed — config rows seed on first read).
    #   v3 — added app_data + city_demographics + city_distances tables (v5.0.0: all
    #        remaining JSON data moved into the DB). Created via IF NOT EXISTS; rows seed
    #        from data/seeds via ensure_seeded(), so no explicit data migration step.
    #   v4 — (v5.1.7) fix two misspelled city_distances keys so they join to the matching
    #        demographics/properties rows (Fenlon Falls→Fenelon Falls, St. Marys→St Marys).
    #   v5 — (v5.7.1) repoint misspelled rent-table keys to the canonical spelling
    #        (st. marys→st marys, fenlon falls→fenelon falls), matching the v4 fix that
    #        corrected the same names in city_distances but missed the rent tables.
    SCHEMA_VERSION = 5
    _MIGRATIONS = {   # {target_version: callable(conn)} — tables auto-create; seeding is lazy
        4: _migrate_v4_fix_city_distance_keys,
        5: _migrate_v5_fix_rent_city_keys,
    }

    def _connect(self) -> sqlite3.Connection:
        """Open the properties DB, creating the file + schema on first use."""
        parent = os.path.dirname(self._properties_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(self._properties_path)
        conn.row_factory = sqlite3.Row
        conn.executescript(self._SCHEMA)
        self._apply_migrations(conn)
        return conn

    def _apply_migrations(self, conn) -> None:
        """Run any pending forward migrations and stamp the schema version."""
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version >= self.SCHEMA_VERSION:
            return
        for target in range(version + 1, self.SCHEMA_VERSION + 1):
            step = self._MIGRATIONS.get(target)
            if step is not None:
                step(conn)
        # PRAGMA can't be parameterised; SCHEMA_VERSION is a trusted int constant.
        conn.execute(f"PRAGMA user_version = {int(self.SCHEMA_VERSION)}")
        conn.commit()

    # ------------------------------------------------------------------
    # Read-only DB explorer (v5.1.0): introspect the schema + browse/query data.
    # Every method here is READ-ONLY — browsing enforces identifier whitelisting and
    # run_readonly_query enforces a single read-only statement + PRAGMA query_only.
    # ------------------------------------------------------------------

    def list_tables(self) -> list:
        """User tables (excludes sqlite_* internals) with row counts:
        [{"name": str, "rows": int}], sorted by name."""
        self._maybe_seed()
        conn = self._connect()
        try:
            names = [r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            return [{"name": n, "rows": conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0]}
                    for n in names]
        finally:
            conn.close()

    def _table_exists(self, name: str) -> bool:
        conn = self._connect()
        try:
            return conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
                (name,)).fetchone() is not None
        finally:
            conn.close()

    def table_schema(self, name: str) -> list:
        """Column metadata for a table: [{name, type, notnull, pk}]. [] for an unknown table."""
        if not self._table_exists(name):
            return []
        conn = self._connect()
        try:
            return [{"name": r["name"], "type": r["type"], "notnull": bool(r["notnull"]),
                     "pk": bool(r["pk"])} for r in conn.execute(f'PRAGMA table_info("{name}")')]
        finally:
            conn.close()

    def table_page(self, name: str, limit: int = 50, offset: int = 0) -> dict:
        """A page of rows from a table: {"columns": [...], "rows": [[...], ...], "total": int}.
        `name` is whitelisted against the real schema; limit is clamped to 1..500."""
        if not self._table_exists(name):
            return {"columns": [], "rows": [], "total": 0}
        limit = max(1, min(int(limit or 50), 500))
        offset = max(0, int(offset or 0))
        conn = self._connect()
        try:
            total = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            cur = conn.execute(f'SELECT * FROM "{name}" LIMIT ? OFFSET ?', (limit, offset))
            cols = [d[0] for d in cur.description]
            return {"columns": cols, "rows": [list(r) for r in cur.fetchall()], "total": total}
        finally:
            conn.close()

    def run_readonly_query(self, sql: str) -> dict:
        """Run ONE read-only statement (SELECT / WITH…SELECT / PRAGMA / EXPLAIN) and return
        {"columns": [...], "rows": [[...]]}. Rejects anything else (raises ValueError) and runs
        under PRAGMA query_only so a write can never occur even if a check is bypassed."""
        import form_logic
        ok, cleaned = form_logic.is_readonly_sql(sql)
        if not ok:
            raise ValueError("Only a single read-only SELECT / WITH / PRAGMA / EXPLAIN query is allowed.")
        conn = self._connect()
        try:
            conn.execute("PRAGMA query_only = ON")
            cur = conn.execute(cleaned)
            cols = [d[0] for d in (cur.description or [])]
            return {"columns": cols, "rows": [list(r) for r in cur.fetchall()]}
        finally:
            conn.close()

    @staticmethod
    def _row_columns(record: dict) -> tuple:
        """The mirrored (indexable) columns + JSON blob pulled from a record."""
        return (
            record.get("address", ""),
            record.get("listing_date", ""),
            record.get("city"),
            record.get("province"),
            record.get("status"),
            record.get("property_type"),
            record.get("asking_price"),
            json.dumps(record, ensure_ascii=False),
        )

    def load_properties(self) -> list:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT data FROM properties ORDER BY id").fetchall()
        finally:
            conn.close()
        return [json.loads(r["data"]) for r in rows]

    def save_property(self, record: dict):
        """Insert or replace a property record (matched on address + listing_date).

        Mirrors the old JSON behaviour: an existing record with the same key is
        removed and the new one appended (so it sorts last by insertion order)."""
        addr    = record.get("address", "")
        listing = record.get("listing_date", "")
        conn = self._connect()
        try:
            conn.execute(
                "DELETE FROM properties WHERE address = ? AND listing_date = ?",
                (addr, listing),
            )
            conn.execute(
                "INSERT INTO properties "
                "(address, listing_date, city, province, status, property_type, asking_price, data) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                self._row_columns(record),
            )
            conn.commit()
        finally:
            conn.close()

    def _ordered_ids(self, conn) -> list:
        return [r["id"] for r in conn.execute("SELECT id FROM properties ORDER BY id")]

    def delete_property(self, index: int) -> bool:
        conn = self._connect()
        try:
            ids = self._ordered_ids(conn)
            if index < 0 or index >= len(ids):
                return False
            conn.execute("DELETE FROM properties WHERE id = ?", (ids[index],))
            conn.commit()
            return True
        finally:
            conn.close()

    def update_property(self, index: int, fields: dict) -> bool:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT id, data FROM properties ORDER BY id").fetchall()
            if index < 0 or index >= len(rows):
                return False
            row    = rows[index]
            record = json.loads(row["data"])
            record.update(fields)
            conn.execute(
                "UPDATE properties SET address=?, listing_date=?, city=?, province=?, "
                "status=?, property_type=?, asking_price=?, data=? WHERE id=?",
                (*self._row_columns(record), row["id"]),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def migrate_vacancy_rate_to_null(self) -> int:
        """One-time migration: clears frozen vacancy_rate values so they re-resolve
        from the vacancy resolver on next analysis. Safe to run on every startup;
        returns the number of records updated (0 once migration is complete)."""
        conn = self._connect()
        try:
            rows  = conn.execute("SELECT id, data FROM properties").fetchall()
            count = 0
            for r in rows:
                record = json.loads(r["data"])
                if record.get("vacancy_rate") is not None:
                    record["vacancy_rate"] = None
                    conn.execute(
                        "UPDATE properties SET data = ? WHERE id = ?",
                        (json.dumps(record, ensure_ascii=False), r["id"]),
                    )
                    count += 1
            if count:
                conn.commit()
            return count
        finally:
            conn.close()

    def normalize_addresses(self, cleaner) -> int:
        """One-time cleanup: legacy imports stored the full 'street, city, province' in the
        address field. `cleaner(address, city, province) -> street` strips the trailing
        city/province that duplicate the record's own fields. Updates in place by db id,
        skipping any change that would collide with another record's (address, listing_date);
        guarded by a meta flag so it runs once per database. Returns the number cleaned."""
        if getattr(self, "_addr_normalized_checked", False):
            return 0
        conn = self._connect()
        try:
            if conn.execute("SELECT value FROM meta WHERE key='normalized_addresses'").fetchone():
                self._addr_normalized_checked = True
                return 0
            rows = conn.execute(
                "SELECT id, address, listing_date, city, province, data FROM properties"
            ).fetchall()
            keys = {(r["address"], r["listing_date"]) for r in rows}
            count = 0
            for r in rows:
                new_addr = cleaner(r["address"], r["city"], r["province"])
                if not new_addr or new_addr == r["address"]:
                    continue
                new_key = (new_addr, r["listing_date"])
                if new_key in keys and new_key != (r["address"], r["listing_date"]):
                    continue   # would clash with another record — leave this one as-is
                record = json.loads(r["data"])
                record["address"] = new_addr
                conn.execute(
                    "UPDATE properties SET address = ?, data = ? WHERE id = ?",
                    (new_addr, json.dumps(record, ensure_ascii=False), r["id"]),
                )
                keys.discard((r["address"], r["listing_date"]))
                keys.add(new_key)
                count += 1
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('normalized_addresses', ?)",
                (date.today().isoformat(),),
            )
            conn.commit()
            self._addr_normalized_checked = True
            return count
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # One-time JSON → SQLite migration
    # ------------------------------------------------------------------

    def import_properties_from_json(self, json_path: str = None) -> int:
        """Load every record from a legacy properties.json into the database.
        Returns the number of records imported. Non-destructive: the JSON file is
        left untouched."""
        path = json_path or self.PROPERTIES_JSON_LEGACY
        if not os.path.exists(path):
            return 0
        with open(path, "r", encoding="utf-8") as f:
            records = json.load(f).get("properties", [])
        conn = self._connect()
        try:
            for record in records:
                conn.execute(
                    "INSERT OR REPLACE INTO properties "
                    "(address, listing_date, city, province, status, property_type, asking_price, data) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    self._row_columns(record),
                )
            conn.commit()
        finally:
            conn.close()
        return len(records)

    def ensure_properties_migrated(self, json_path: str = None) -> int:
        """Auto-import the legacy properties.json ONCE, the first time the app runs
        against the new database. Guarded by a meta flag so emptying the database
        never re-triggers the import, and the JSON file is never modified. Returns
        the number of records imported (0 if already migrated or no JSON present)."""
        conn = self._connect()
        try:
            done = conn.execute(
                "SELECT value FROM meta WHERE key = 'migrated_from_json'"
            ).fetchone()
        finally:
            conn.close()
        if done:
            return 0
        count = self.import_properties_from_json(json_path)
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('migrated_from_json', ?)",
                (date.today().isoformat(),),
            )
            conn.commit()
        finally:
            conn.close()
        return count

    # ------------------------------------------------------------------
    # realtor.ca price-check progress (resume/checkpoint)
    # ------------------------------------------------------------------

    def load_price_check_progress(self) -> dict:
        """Returns {key: row} of results saved so far, or {} if no run is in progress
        (v5.0.0: the 'price_check_progress' app_data doc)."""
        return (self.read_app_data("price_check_progress") or {}).get("checked", {})

    def save_price_check_result(self, key: str, row: dict):
        """Checkpoint a single price-check result (app_data) so an interrupted sweep can
        resume."""
        data = self.read_app_data("price_check_progress") or {}
        data.setdefault("checked", {})[key] = row
        data["updated_at"] = date.today().isoformat()
        self.write_app_data("price_check_progress", data)

    def clear_price_check_progress(self):
        """Reset the saved progress (app_data)."""
        self.write_app_data("price_check_progress", {"checked": {}})

    # ------------------------------------------------------------------
    # Missing cities report
    # ------------------------------------------------------------------

    def load_missing_cities(self) -> dict:
        """The 'missing_cities' report (app_data): {key: {city, province, missing[],
        property_types[], first_seen, last_seen}}."""
        raw = self.read_app_data("missing_cities") or {}
        seen, result, changed = {}, {}, False
        for k, v in raw.items():
            norm = k.strip().lower()
            if norm in seen:
                existing = result[seen[norm]]
                for m in v.get("missing", []):
                    if m not in existing.get("missing", []):
                        existing.setdefault("missing", []).append(m)
                for pt in v.get("property_types", []):
                    if pt not in existing.get("property_types", []):
                        existing.setdefault("property_types", []).append(pt)
                changed = True
            else:
                seen[norm] = k
                result[k]  = v
        if changed:
            self.write_app_data("missing_cities", result)
        return result

    def log_missing_city(self, city: str, province: str, missing_type: str,
                         property_types: list = None):
        city     = city.strip().title()
        province = province.strip().upper()
        data     = self.load_missing_cities()
        norm_key = f"{city}, {province}"
        for old_key in [k for k in data if k.lower() == norm_key.lower() and k != norm_key]:
            data[norm_key] = data.pop(old_key)
        key   = norm_key
        entry = data.get(key, {
            "city":           city,
            "province":       province,
            "missing":        [],
            "property_types": [],
            "first_seen":     date.today().isoformat(),
        })
        if missing_type not in entry["missing"]:
            entry["missing"].append(missing_type)
        if property_types:
            for pt in property_types:
                if pt not in entry["property_types"]:
                    entry["property_types"].append(pt)
        entry["last_seen"] = date.today().isoformat()
        data[key] = entry
        self.write_app_data("missing_cities", data)

    _COMMERCIAL_STUB_TYPES = ("Office", "Retail", "Industrial", "Mixed-Use")
    _RESIDENTIAL_STUB_UNITS = ("bachelor", "one_br", "two_br", "three_br",
                               "four_br", "unknown")

    def ensure_city_in_rates(self, city: str, province: str):
        """Adds None-filled stubs for missing cities; migrates old zero stubs to None."""
        self.ensure_rates_migrated()
        city     = city.strip().title()
        province = province.strip().upper()
        key      = f"{city}, {province}"
        city_lower = city.lower()

        conn = self._connect()
        try:
            # Migrate any legacy zero-filled stubs → None so the resolver's None
            # guards fire correctly instead of treating $0/sqft as a valid rate.
            conn.execute("UPDATE commercial_rents  SET rate = NULL WHERE rate = 0")
            conn.execute("UPDATE residential_rents SET rent = NULL WHERE rent = 0")

            comm_exists = conn.execute(
                "SELECT 1 FROM commercial_rents WHERE city_key = ? LIMIT 1", (city_lower,)
            ).fetchone()
            res_exists = conn.execute(
                "SELECT 1 FROM residential_rents WHERE city_key = ? LIMIT 1", (city_lower,)
            ).fetchone()

            needs_update = False
            if not comm_exists:
                for ptype in self._COMMERCIAL_STUB_TYPES:
                    conn.execute(
                        "INSERT OR IGNORE INTO commercial_rents "
                        "(city_key, city, province, property_type, rate, source) "
                        "VALUES (?, ?, ?, ?, NULL, NULL)",
                        (city_lower, city, province, ptype),
                    )
                needs_update = True
            if not res_exists:
                for unit in self._RESIDENTIAL_STUB_UNITS:
                    conn.execute(
                        "INSERT OR IGNORE INTO residential_rents "
                        "(city_key, city, province, unit_type, rent) "
                        "VALUES (?, ?, ?, ?, NULL)",
                        (city_lower, city, province, unit),
                    )
                needs_update = True
            conn.commit()
        finally:
            conn.close()

        if needs_update:
            missing = self.read_app_data("missing_rent_data") or {}
            if key not in missing:
                missing[key] = {
                    "city":       city,
                    "province":   province,
                    "first_seen": date.today().isoformat(),
                }
            missing[key]["last_seen"] = date.today().isoformat()
            self.write_app_data("missing_rent_data", missing)

    def clear_missing_city(self, key: str):
        data = self.load_missing_cities()
        if key in data:
            del data[key]
            self.write_app_data("missing_cities", data)

    def save_commercial_city(self, city: str, province: str, rates: dict):
        """Saves commercial rates and removes city from missing report if complete."""
        city     = city.strip().title()
        province = province.strip().upper()
        self.save_commercial_rates(city, province, rates)
        missing  = self.load_missing_cities()
        norm     = f"{city}, {province}".lower()
        key      = next((k for k in missing if k.lower() == norm), None)
        if key is None:
            return
        entry        = missing[key]
        needed_types = entry.get("property_types", [])
        if needed_types:
            still_missing = [t for t in needed_types if t not in rates]
            if still_missing:
                entry["property_types"] = still_missing
                missing[key] = entry
                self.write_app_data("missing_cities", missing)
                return
        if "commercial" in entry["missing"]:
            entry["missing"].remove("commercial")
        entry["property_types"] = []
        if not entry["missing"]:
            del missing[key]
        else:
            missing[key] = entry
        self.write_app_data("missing_cities", missing)

    def save_residential_city(self, city: str, province: str, units: dict):
        """Saves residential rates and removes city from missing report if complete."""
        city     = city.strip().title()
        province = province.strip().upper()
        self.save_residential_rates(city, province, units)
        missing  = self.load_missing_cities()
        norm     = f"{city}, {province}".lower()
        key      = next((k for k in missing if k.lower() == norm), None)
        if key is None:
            return
        entry = missing[key]
        if "residential" in entry["missing"]:
            entry["missing"].remove("residential")
        if not entry["missing"]:
            del missing[key]
        else:
            missing[key] = entry
        self.write_app_data("missing_cities", missing)

    def delete_city_rates(self, city: str, province: str) -> int:
        """Remove a city's rate entry entirely — both the commercial and residential
        rate rows — and drop it from the missing-cities report. Returns the number of
        rate rows deleted. Properties in that city keep their last stored report; they
        simply lose the market rate until it's re-added or they're re-analyzed."""
        self._maybe_seed()
        city_key = city.strip().lower()
        conn = self._connect()
        try:
            c = conn.execute("DELETE FROM commercial_rents WHERE city_key = ?", (city_key,)).rowcount
            r = conn.execute("DELETE FROM residential_rents WHERE city_key = ?", (city_key,)).rowcount
            conn.commit()
        finally:
            conn.close()
        # Clear the city from both missing-city reports (missing_cities + the
        # missing_rent_data report ensure_city_in_rates writes), any case.
        norm = f"{city.strip().title()}, {province.strip().upper()}".lower()
        for k in [k for k in self.load_missing_cities() if k.lower() == norm]:
            self.clear_missing_city(k)
        self._clear_missing_rent_city(norm)
        return (c or 0) + (r or 0)

    def _clear_missing_rent_city(self, norm_key: str):
        """Remove a city (normalized 'city, prov' key, any case) from the
        'missing_rent_data' report (app_data) that ensure_city_in_rates populates."""
        data = self.read_app_data("missing_rent_data") or {}
        removed = [k for k in data if k.lower() == norm_key]
        for k in removed:
            del data[k]
        if removed:
            self.write_app_data("missing_rent_data", data)

    # ------------------------------------------------------------------
    # Per-city reference data (city_demographics / city_distances tables, v5.0.0)
    #
    # Return shapes mirror the former JSON: demographics keyed by lowercase city,
    # distances keyed by display casing — so the scorer / editors / dashboard are
    # unchanged. ensure_city_in_* add a blank stub so a new city shows up "needs data".
    # ------------------------------------------------------------------

    def load_city_demographics(self) -> dict:
        """{city_key: {population, population_2016, growth_pct_annual, source, notes}}."""
        self._maybe_seed()
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM city_demographics").fetchall()
        finally:
            conn.close()
        return {r["city_key"]: {
            "population": r["population"], "population_2016": r["population_2016"],
            "growth_pct_annual": r["growth_pct_annual"],
            "source": r["source"] or "", "notes": r["notes"] or ""} for r in rows}

    def save_city_demographics(self, city: str, data: dict) -> None:
        """Upsert one city's demographics row (keyed by lowercase city)."""
        ck = (city or "").strip().lower()
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO city_demographics "
                "(city_key, city, population, population_2016, growth_pct_annual, source, notes) "
                "VALUES (?,?,?,?,?,?,?)",
                (ck, city.strip().title(), data.get("population"), data.get("population_2016"),
                 data.get("growth_pct_annual"), data.get("source", ""), data.get("notes", "")))
            conn.commit()
        finally:
            conn.close()

    def load_city_distances(self) -> dict:
        """{city_display: {distance_km, nearest_centre}} (display-cased key)."""
        self._maybe_seed()
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM city_distances").fetchall()
        finally:
            conn.close()
        return {r["city"]: {"distance_km": r["distance_km"],
                            "nearest_centre": r["nearest_centre"] or ""} for r in rows}

    def save_city_distance(self, city: str, data: dict) -> None:
        """Upsert one city's distance row."""
        city = (city or "").strip().title(); ck = city.lower()
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO city_distances "
                "(city_key, city, distance_km, nearest_centre) VALUES (?,?,?,?)",
                (ck, city, data.get("distance_km"), data.get("nearest_centre", "")))
            conn.commit()
        finally:
            conn.close()

    def delete_city_demographics(self, city: str) -> int:
        """Remove one city's demographics row. Returns rows deleted (0 or 1)."""
        ck = (city or "").strip().lower()
        conn = self._connect()
        try:
            n = conn.execute("DELETE FROM city_demographics WHERE city_key=?", (ck,)).rowcount
            conn.commit()
        finally:
            conn.close()
        return n or 0

    def delete_city_distance(self, city: str) -> int:
        """Remove one city's distance row. Returns rows deleted (0 or 1)."""
        ck = (city or "").strip().lower()
        conn = self._connect()
        try:
            n = conn.execute("DELETE FROM city_distances WHERE city_key=?", (ck,)).rowcount
            conn.commit()
        finally:
            conn.close()
        return n or 0

    def ensure_city_in_demographics(self, city: str) -> bool:
        """Add a blank demographics stub if the city is absent. True when one was created."""
        city = (city or "").strip()
        if not city:
            return False
        ck = city.lower()
        self._maybe_seed()
        conn = self._connect()
        try:
            if conn.execute("SELECT 1 FROM city_demographics WHERE city_key=? LIMIT 1", (ck,)).fetchone():
                return False
            conn.execute(
                "INSERT OR IGNORE INTO city_demographics "
                "(city_key, city, population, population_2016, growth_pct_annual, source, notes) "
                "VALUES (?,?,NULL,NULL,NULL,'','')", (ck, city.title()))
            conn.commit()
        finally:
            conn.close()
        return True

    def ensure_city_in_distances(self, city: str) -> bool:
        """Add a blank distance stub if the city is absent. True when one was created."""
        city = (city or "").strip().title()
        if not city:
            return False
        ck = city.lower()
        self._maybe_seed()
        conn = self._connect()
        try:
            if conn.execute("SELECT 1 FROM city_distances WHERE city_key=? LIMIT 1", (ck,)).fetchone():
                return False
            conn.execute(
                "INSERT OR IGNORE INTO city_distances "
                "(city_key, city, distance_km, nearest_centre) VALUES (?,?,NULL,'')", (ck, city))
            conn.commit()
        finally:
            conn.close()
        return True

    def ensure_city_reference_data(self, city: str, province: str) -> dict:
        """Ensure a city exists (blank) across every reference store — rates,
        demographics, distances — so an added property for a new city never leaves a
        gap. Returns which stores were newly stubbed: keys rates/demographics/distances
        plus any_created."""
        self.ensure_city_in_rates(city, province)
        demo = self.ensure_city_in_demographics(city)
        dist = self.ensure_city_in_distances(city)
        # A city "needs rates" when it still has only unfilled (null) rate stubs.
        rates_needed = not self._city_has_any_rate(city)
        return {"rates": rates_needed, "demographics": demo, "distances": dist,
                "any_created": bool(rates_needed or demo or dist)}

    def _city_has_any_rate(self, city: str) -> bool:
        """True when the city has at least one non-null commercial or residential rate."""
        city_key = city.strip().lower()
        conn = self._connect()
        try:
            c = conn.execute(
                "SELECT 1 FROM commercial_rents WHERE city_key = ? AND rate IS NOT NULL LIMIT 1",
                (city_key,)).fetchone()
            r = conn.execute(
                "SELECT 1 FROM residential_rents WHERE city_key = ? AND rent IS NOT NULL LIMIT 1",
                (city_key,)).fetchone()
        finally:
            conn.close()
        return bool(c or r)


class CommercialRentLoader:
    """Wraps the commercial rate index from DataStore for clean lookups."""

    def __init__(self, data_store: DataStore):
        self._store = data_store

    def get_rent_per_sqft(self, city: str, province: str, property_type: str):
        """Returns rate float, or None if city/type not found."""
        index    = self._store.load_commercial_rates()
        city_key = city.strip().lower()
        type_key = property_type.strip().lower()
        if city_key not in index or type_key not in index[city_key]:
            return None
        return index[city_key][type_key]

    def get_rate_source(self, city: str, province: str):
        """Returns 'Src', 'Est', or None describing the city's rate provenance."""
        sources = self._store.load_commercial_sources()
        s = (sources.get(city.strip().lower(), "") or "").lower()
        has_src, has_est = "src" in s, "est" in s
        if has_src and not has_est:
            return "Src"
        if has_est and not has_src:
            return "Est"
        if has_est and has_src:
            # Mixed tag across asset types — treat as the weaker (estimate).
            return "Est"
        return None


class ResidentialRentLoader:
    """Wraps the residential rate index from DataStore for clean lookups."""

    def __init__(self, data_store: DataStore):
        self._store = data_store

    def get_rates(self, city: str, province: str):
        """Returns rate dict, or None if city not found or all rates are unfilled stubs."""
        index = self._store.load_residential_rates()
        key   = city.strip().lower()
        rates = index.get(key)
        if rates is None:
            return None
        if all(v is None for v in rates.values()):
            return None
        return rates
