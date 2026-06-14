import json
import os
import shutil
from datetime import date


class DataStore:
    """
    Owns all JSON file loading and saving.
    All other classes call DataStore; none touch the filesystem directly.
    """

    COMMERCIAL_PATH  = "json/commercial_rents.json"
    RESIDENTIAL_PATH = "json/residential_rents.json"
    PROPERTIES_PATH  = "properties.json"
    MISSING_PATH     = "json/missing_cities.json"
    MISSING_RENT_PATH = "json/missing_rent_data.json"

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
    # Commercial rates
    # ------------------------------------------------------------------

    def load_commercial_rates(self) -> dict:
        """Returns {city_lower: {type_lower: rate}} for fast lookup."""
        raw = self._read(self._commercial_path)
        index = {}
        for city, city_data in raw["cities"].items():
            city_key = city.strip().lower()
            index[city_key] = {
                t.strip().lower(): rate
                for t, rate in city_data["types"].items()
            }
        return index

    def load_commercial_sources(self) -> dict:
        """Returns {city_lower: source_string} from the commercial rates file.

        The per-city ``source`` field is prefixed ``Src:`` (sourced from a broker
        report) or ``Est:`` (estimate); used to grade rate confidence.
        """
        raw = self._read(self._commercial_path)
        return {
            city.strip().lower(): (city_data.get("source") or "")
            for city, city_data in raw["cities"].items()
        }

    def save_commercial_rates(self, city: str, province: str, rates: dict):
        data = self._read(self._commercial_path)
        data["cities"][city] = {"province": province, "types": rates}
        self._write(self._commercial_path, data)

    # ------------------------------------------------------------------
    # Residential rates
    # ------------------------------------------------------------------

    def load_residential_rates(self) -> dict:
        """Returns {city_lower: {unit_type: monthly_rent_or_None}} for fast lookup."""
        raw = self._read(self._residential_path)
        index = {}
        for city, city_data in raw["cities"].items():
            city_key = city.strip().lower()
            index[city_key] = {
                k: (float(v) if v is not None else None)
                for k, v in city_data["units"].items()
            }
        return index

    def save_residential_rates(self, city: str, province: str, units: dict):
        data = self._read(self._residential_path)
        data["cities"][city] = {"province": province, "units": units}
        self._write(self._residential_path, data)

    # ------------------------------------------------------------------
    # Property analyses
    # ------------------------------------------------------------------

    def load_properties(self) -> list:
        if not os.path.exists(self._properties_path):
            return []
        return self._read(self._properties_path).get("properties", [])

    def save_property(self, record: dict):
        """Appends or replaces a property record (matched on address + listing_date)."""
        if os.path.exists(self._properties_path):
            data = self._read(self._properties_path)
        else:
            data = {"properties": []}

        key = (record.get("address", ""), record.get("listing_date", ""))
        data["properties"] = [
            p for p in data["properties"]
            if (p.get("address", ""), p.get("listing_date", "")) != key
        ]
        data["properties"].append(record)
        self._write(self._properties_path, data)

    def delete_property(self, index: int) -> bool:
        data = self._read(self._properties_path) if os.path.exists(self._properties_path) else {"properties": []}
        props = data.get("properties", [])
        if index < 0 or index >= len(props):
            return False
        del props[index]
        data["properties"] = props
        self._write(self._properties_path, data)
        return True

    def update_property(self, index: int, fields: dict) -> bool:
        data = self._read(self._properties_path) if os.path.exists(self._properties_path) else {"properties": []}
        props = data.get("properties", [])
        if index < 0 or index >= len(props):
            return False
        props[index].update(fields)
        data["properties"] = props
        self._write(self._properties_path, data)
        return True

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

    def ensure_city_in_rates(self, city: str, province: str):
        """Adds None-filled stubs for missing cities; migrates old zero stubs to None."""
        city     = city.strip().title()
        province = province.strip().upper()
        key      = f"{city}, {province}"

        comm_data = self._read(self._commercial_path)
        res_data  = self._read(self._residential_path)

        comm_cities = {k.strip().lower() for k in comm_data.get("cities", {})}
        res_cities  = {k.strip().lower() for k in res_data.get("cities", {})}
        city_lower  = city.lower()

        needs_update = False
        comm_changed = False
        res_changed  = False

        # Migrate any legacy zero-filled stubs → None so the resolver's None
        # guards fire correctly instead of treating $0/sqft as a valid rate.
        for c_data in comm_data.get("cities", {}).values():
            for t, v in list(c_data.get("types", {}).items()):
                if v == 0:
                    c_data["types"][t] = None
                    comm_changed = True

        for c_data in res_data.get("cities", {}).values():
            for u, v in list(c_data.get("units", {}).items()):
                if v == 0:
                    c_data["units"][u] = None
                    res_changed = True

        if city_lower not in comm_cities:
            comm_data.setdefault("cities", {})[city] = {
                "province": province,
                "types": {"Office": None, "Retail": None, "Industrial": None, "Mixed-Use": None}
            }
            comm_changed = True
            needs_update = True

        if city_lower not in res_cities:
            res_data.setdefault("cities", {})[city] = {
                "province": province,
                "units": {"bachelor": None, "one_br": None, "two_br": None,
                          "three_br": None, "four_br": None, "unknown": None}
            }
            res_changed = True
            needs_update = True

        if comm_changed:
            self._write(self._commercial_path, comm_data)
        if res_changed:
            self._write(self._residential_path, res_data)

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
