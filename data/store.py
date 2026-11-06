import json
import os
import shutil
import sqlite3
from datetime import date


class DataStore:
    """
    Owns all JSON file loading and saving.
    All other classes call DataStore; none touch the filesystem directly.
    """

    COMMERCIAL_PATH  = "json/commercial_rents.json"
    RESIDENTIAL_PATH = "json/residential_rents.json"
    PROPERTIES_PATH  = "properties.db"        # SQLite database (was properties.json)
    PROPERTIES_JSON_LEGACY = "properties.json"  # imported once into the DB on first run
    MISSING_PATH     = "json/missing_cities.json"
    MISSING_RENT_PATH = "json/missing_rent_data.json"
    PRICE_CHECK_PROGRESS_PATH = "json/price_check_progress.json"

    def __init__(self,
                 commercial_path:  str = COMMERCIAL_PATH,
                 residential_path: str = RESIDENTIAL_PATH,
                 properties_path:  str = PROPERTIES_PATH,
                 missing_path:     str = MISSING_PATH):
        self._commercial_path  = commercial_path
        self._residential_path = residential_path
        self._properties_path  = properties_path
        self._missing_path     = missing_path

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
    # Settings config (SQLite-backed: the `config` table)
    #
    # financing.json + score_weights.json (scoring weights, thresholds, and the
    # city-opportunity weights/knobs) live here as one JSON document per logical
    # name. The JSON files remain the shipped DEFAULTS; read_config seeds a missing
    # row from the file once, then the DB is the live source (edited in Settings).
    # ------------------------------------------------------------------

    def read_config(self, name: str, seed_path: str = None) -> dict:
        """Return the config document for ``name``. If the row is absent, seed it
        once from ``seed_path`` (when that file exists) and return that, otherwise
        return {}. Self-healing migration-on-read — no explicit boot step needed."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT json FROM config WHERE name = ?", (name,)
            ).fetchone()
            if row is not None:
                return json.loads(row["json"])
            seed = {}
            if seed_path and os.path.exists(seed_path):
                with open(seed_path, "r", encoding="utf-8") as f:
                    seed = json.load(f)
                conn.execute(
                    "INSERT OR IGNORE INTO config (name, json, updated_at) VALUES (?, ?, ?)",
                    (name, json.dumps(seed, ensure_ascii=False), date.today().isoformat()),
                )
                conn.commit()
            return seed
        finally:
            conn.close()

    def write_config(self, name: str, cfg: dict) -> dict:
        """Upsert the config document for ``name`` (the DB is the live source)."""
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO config (name, json, updated_at) VALUES (?, ?, ?)",
                (name, json.dumps(cfg, ensure_ascii=False), date.today().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()
        return cfg

    # ------------------------------------------------------------------
    # Rent rates (SQLite-backed: commercial_rents + residential_rents tables)
    #
    # Rents moved out of commercial_rents.json / residential_rents.json into their
    # own normalised tables (one row per city+type / city+unit). The JSON files
    # remain the one-time migration source (imported transparently on first use,
    # guarded so it never re-runs or overwrites DB edits). Return shapes are
    # unchanged, so RentResolver / the loaders / the rate editor are untouched.
    # ------------------------------------------------------------------

    def ensure_rates_migrated(self) -> None:
        """Import the legacy rent JSON files into the rate tables ONCE per database.

        Instance-cached so repeated rate lookups don't re-query the guard. Guarded
        by a meta flag (persisted), and imports with INSERT OR IGNORE so it never
        clobbers rows already written to the DB."""
        if getattr(self, "_rates_migrated_checked", False):
            return
        conn = self._connect()
        try:
            done = conn.execute(
                "SELECT value FROM meta WHERE key = 'migrated_rates'"
            ).fetchone()
        finally:
            conn.close()
        if not done:
            self._import_rates_from_json()
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES ('migrated_rates', ?)",
                    (date.today().isoformat(),),
                )
                conn.commit()
            finally:
                conn.close()
        self._rates_migrated_checked = True

    def _import_rates_from_json(self) -> None:
        conn = self._connect()
        try:
            if os.path.exists(self._commercial_path):
                try:
                    raw = self._read(self._commercial_path)
                except Exception:
                    raw = {"cities": {}}
                for city, cdata in raw.get("cities", {}).items():
                    city_key = city.strip().lower()
                    province = cdata.get("province")
                    source   = cdata.get("source") or ""
                    for ptype, rate in cdata.get("types", {}).items():
                        conn.execute(
                            "INSERT OR IGNORE INTO commercial_rents "
                            "(city_key, city, province, property_type, rate, source) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (city_key, city, province, ptype, rate, source),
                        )
            if os.path.exists(self._residential_path):
                try:
                    raw = self._read(self._residential_path)
                except Exception:
                    raw = {"cities": {}}
                for city, cdata in raw.get("cities", {}).items():
                    city_key = city.strip().lower()
                    province = cdata.get("province")
                    for unit, rent in cdata.get("units", {}).items():
                        conn.execute(
                            "INSERT OR IGNORE INTO residential_rents "
                            "(city_key, city, province, unit_type, rent) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (city_key, city, province, unit, rent),
                        )
            conn.commit()
        finally:
            conn.close()

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

        -- Settings config: one JSON document per logical name ('financing',
        -- 'score_weights'). The JSON files remain the shipped defaults; read_config
        -- seeds a missing row from the file once, then this table is the live source.
        CREATE TABLE IF NOT EXISTS config (
            name       TEXT PRIMARY KEY,
            json       TEXT NOT NULL,
            updated_at TEXT
        );
    """

    # Current on-disk schema version (SQLite PRAGMA user_version). The baseline schema
    # above is version 1. When the schema changes in a future release, bump this and add
    # the forward step to _MIGRATIONS below; _apply_migrations runs the pending steps and
    # restamps user_version on the next connect. Keeps old databases upgradable in place.
    #   v2 — added the `config` table (created above via IF NOT EXISTS, so existing DBs
    #        gain it on connect; no data step needed — config rows seed on first read).
    SCHEMA_VERSION = 2
    _MIGRATIONS = {}   # {target_version: callable(conn)} — v1/v2 need no explicit step

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
        """Returns {key: row} of results saved so far, or {} if no run is in progress."""
        path = self.PRICE_CHECK_PROGRESS_PATH
        if not os.path.exists(path):
            return {}
        try:
            return self._read(path).get("checked", {})
        except Exception:
            return {}

    def save_price_check_result(self, key: str, row: dict):
        """Checkpoint a single price-check result so an interrupted sweep can resume.

        Saved on every property; written without a .bak copy since the file is
        transient progress, not durable data.
        """
        path = self.PRICE_CHECK_PROGRESS_PATH
        if os.path.exists(path):
            try:
                data = self._read(path)
            except Exception:
                data = {"checked": {}}
        else:
            data = {"checked": {}}
        data.setdefault("checked", {})[key] = row
        data["updated_at"] = date.today().isoformat()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)

    def clear_price_check_progress(self):
        """Remove the saved progress file (and any stray temp/backup siblings)."""
        for p in (self.PRICE_CHECK_PROGRESS_PATH,
                  self.PRICE_CHECK_PROGRESS_PATH + ".bak",
                  self.PRICE_CHECK_PROGRESS_PATH + ".tmp"):
            if os.path.exists(p):
                os.remove(p)

    # ------------------------------------------------------------------
    # Missing cities report
    # ------------------------------------------------------------------

    def load_missing_cities(self) -> dict:
        if not os.path.exists(self._missing_path):
            return {}
        raw = self._read(self._missing_path)
        seen, result = {}, {}
        for k, v in raw.items():
            norm = k.strip().lower()
            if norm in seen:
                existing = result[seen[norm]]
                for m in v.get("missing", []):
                    if m not in existing["missing"]:
                        existing["missing"].append(m)
                for pt in v.get("property_types", []):
                    if pt not in existing.get("property_types", []):
                        existing.setdefault("property_types", []).append(pt)
            else:
                seen[norm] = k
                result[k]  = v
        if len(result) != len(raw):
            self._write(self._missing_path, result)
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
        os.makedirs(os.path.dirname(self._missing_path), exist_ok=True)
        self._write(self._missing_path, data)

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
            missing = {}
            if os.path.exists(self.MISSING_RENT_PATH):
                try:
                    missing = self._read(self.MISSING_RENT_PATH)
                except Exception:
                    missing = {}
            if key not in missing:
                missing[key] = {
                    "city":       city,
                    "province":   province,
                    "first_seen": date.today().isoformat(),
                }
            missing[key]["last_seen"] = date.today().isoformat()
            os.makedirs(os.path.dirname(self.MISSING_RENT_PATH), exist_ok=True)
            self._write(self.MISSING_RENT_PATH, missing)

    def clear_missing_city(self, key: str):
        data = self.load_missing_cities()
        if key in data:
            del data[key]
            self._write(self._missing_path, data)

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
                self._write(self._missing_path, missing)
                return
        if "commercial" in entry["missing"]:
            entry["missing"].remove("commercial")
        entry["property_types"] = []
        if not entry["missing"]:
            del missing[key]
        else:
            missing[key] = entry
        self._write(self._missing_path, missing)

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
        self._write(self._missing_path, missing)


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
