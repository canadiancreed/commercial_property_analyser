import json
import os
import pytest
from data.store import DataStore, CommercialRentLoader, ResidentialRentLoader


# ── Helpers ─────────────────────────────────────────────────────────────────

def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _comm_json(cities=None):
    return {"cities": cities or {}}


def _res_json(cities=None):
    return {"cities": cities or {}}


# ── DataStore fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def tmp_store(tmp_path):
    comm   = str(tmp_path / "comm.json")
    res    = str(tmp_path / "res.json")
    props  = str(tmp_path / "props.json")
    miss   = str(tmp_path / "miss.json")
    _write_json(comm,  _comm_json())
    _write_json(res,   _res_json())
    return DataStore(
        commercial_path=comm, residential_path=res,
        properties_path=props, missing_path=miss,
    )


@pytest.fixture
def store_with_rates(tmp_path):
    comm_data = {
        "cities": {
            "Ottawa": {
                "province": "ON",
                "types": {"Office": 20.0, "Retail": 30.0, "Industrial": 12.0, "Mixed-Use": 18.0}
            }
        }
    }
    res_data = {
        "cities": {
            "Ottawa": {
                "province": "ON",
                "units": {"bachelor": 900, "one_br": 1200, "two_br": 1600,
                          "three_br": 1900, "four_br": 2200, "unknown": 1360}
            }
        }
    }
    comm  = str(tmp_path / "comm.json")
    res   = str(tmp_path / "res.json")
    props = str(tmp_path / "props.json")
    miss  = str(tmp_path / "miss.json")
    _write_json(comm,  comm_data)
    _write_json(res,   res_data)
    return DataStore(
        commercial_path=comm, residential_path=res,
        properties_path=props, missing_path=miss,
    )


# ── Tests: _read / _write ────────────────────────────────────────────────────

class TestReadWrite:
    def test_read_missing_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            DataStore._read(str(tmp_path / "missing.json"))

    def test_write_and_read(self, tmp_path):
        path = str(tmp_path / "data.json")
        DataStore._write(path, {"key": "value"})
        data = DataStore._read(path)
        assert data == {"key": "value"}


# ── Tests: commercial rates ───────────────────────────────────────────────────

class TestCommercialRates:
    def test_load_empty(self, tmp_store):
        assert tmp_store.load_commercial_rates() == {}

    def test_load_rates(self, store_with_rates):
        idx = store_with_rates.load_commercial_rates()
        assert "ottawa" in idx
        assert idx["ottawa"]["office"] == 20.0
        assert idx["ottawa"]["retail"] == 30.0

    def test_save_and_reload(self, tmp_store):
        tmp_store.save_commercial_rates("Guelph", "ON", {"Office": 18.0})
        idx = tmp_store.load_commercial_rates()
        assert "guelph" in idx
        assert idx["guelph"]["office"] == 18.0

    def test_save_commercial_city(self, store_with_rates, tmp_path):
        miss_path = str(tmp_path / "miss.json")
        # Add a missing-cities entry first
        _write_json(miss_path, {
            "Ottawa, ON": {
                "city": "Ottawa", "province": "ON",
                "missing": ["commercial"], "property_types": ["Office"],
                "first_seen": "2025-01-01", "last_seen": "2025-01-01",
            }
        })
        store = DataStore(
            commercial_path=store_with_rates._commercial_path,
            residential_path=store_with_rates._residential_path,
            properties_path=store_with_rates._properties_path,
            missing_path=miss_path,
        )
        store.save_commercial_city("Ottawa", "ON", {"Office": 22.0})
        idx = store.load_commercial_rates()
        assert idx["ottawa"]["office"] == 22.0


# ── Tests: residential rates ─────────────────────────────────────────────────

class TestResidentialRates:
    def test_load_empty(self, tmp_store):
        assert tmp_store.load_residential_rates() == {}

    def test_load_rates(self, store_with_rates):
        idx = store_with_rates.load_residential_rates()
        assert "ottawa" in idx
        assert idx["ottawa"]["one_br"] == 1200.0

    def test_save_and_reload(self, tmp_store):
        units = {"bachelor": 800, "one_br": 1100, "two_br": 1500,
                 "three_br": 1800, "four_br": 2100, "unknown": 1260}
        tmp_store.save_residential_rates("Kingston", "ON", units)
        idx = tmp_store.load_residential_rates()
        assert "kingston" in idx
        assert idx["kingston"]["two_br"] == 1500.0

    def test_save_residential_city_removes_missing(self, tmp_path):
        comm = str(tmp_path / "comm.json")
        res  = str(tmp_path / "res.json")
        props = str(tmp_path / "props.json")
        miss = str(tmp_path / "miss.json")
        _write_json(comm, _comm_json())
        _write_json(res,  _res_json())
        _write_json(miss, {
            "Hamilton, ON": {
                "city": "Hamilton", "province": "ON",
                "missing": ["residential"], "property_types": [],
                "first_seen": "2025-01-01", "last_seen": "2025-01-01",
            }
        })
        store = DataStore(commercial_path=comm, residential_path=res,
                          properties_path=props, missing_path=miss)
        store.save_residential_city("Hamilton", "ON", {"one_br": 1000})
        remaining = store.load_missing_cities()
        assert "Hamilton, ON" not in remaining


# ── Tests: properties ─────────────────────────────────────────────────────────

class TestProperties:
    def _record(self, addr="1 Main St", listing="2025-01-01", **extra):
        rec = {"address": addr, "listing_date": listing, "asking_price": 500_000}
        rec.update(extra)
        return rec

    def test_load_empty_when_no_file(self, tmp_store):
        assert tmp_store.load_properties() == []

    def test_save_and_load(self, tmp_store):
        tmp_store.save_property(self._record())
        props = tmp_store.load_properties()
        assert len(props) == 1
        assert props[0]["address"] == "1 Main St"

    def test_save_replaces_by_key(self, tmp_store):
        tmp_store.save_property(self._record(asking_price=500_000))
        tmp_store.save_property(self._record(asking_price=450_000))
        props = tmp_store.load_properties()
        assert len(props) == 1
        assert props[0]["asking_price"] == 450_000

    def test_save_two_different_records(self, tmp_store):
        tmp_store.save_property(self._record("1 Main St", "2025-01-01"))
        tmp_store.save_property(self._record("2 King St", "2025-01-01"))
        assert len(tmp_store.load_properties()) == 2

    def test_delete_property(self, tmp_store):
        tmp_store.save_property(self._record("1 Main St"))
        tmp_store.save_property(self._record("2 King St"))
        tmp_store.delete_property(0)
        props = tmp_store.load_properties()
        assert len(props) == 1

    def test_delete_out_of_range(self, tmp_store):
        assert tmp_store.delete_property(5) is False

    def test_update_property(self, tmp_store):
        tmp_store.save_property(self._record())
        tmp_store.update_property(0, {"asking_price": 400_000})
        assert tmp_store.load_properties()[0]["asking_price"] == 400_000

    def test_update_out_of_range(self, tmp_store):
        assert tmp_store.update_property(99, {"x": 1}) is False


# ── Tests: missing cities ─────────────────────────────────────────────────────

class TestMissingCities:
    def test_load_when_no_file(self, tmp_store):
        assert tmp_store.load_missing_cities() == {}

    def test_log_creates_entry(self, tmp_store):
        tmp_store.log_missing_city("Barrie", "ON", "commercial", ["Office"])
        data = tmp_store.load_missing_cities()
        assert any("Barrie" in k for k in data)

    def test_log_no_duplicates(self, tmp_store):
        tmp_store.log_missing_city("Barrie", "ON", "commercial")
        tmp_store.log_missing_city("Barrie", "ON", "commercial")
        data = tmp_store.load_missing_cities()
        entry = next(v for k, v in data.items() if "Barrie" in k)
        assert entry["missing"].count("commercial") == 1

    def test_clear_missing_city(self, tmp_store):
        tmp_store.log_missing_city("Barrie", "ON", "commercial")
        data = tmp_store.load_missing_cities()
        key = next(k for k in data if "Barrie" in k)
        tmp_store.clear_missing_city(key)
        assert tmp_store.load_missing_cities() == {}

    def test_ensure_city_adds_entries(self, tmp_store):
        tmp_store.ensure_city_in_rates("Oshawa", "ON")
        comm_idx = tmp_store.load_commercial_rates()
        res_idx  = tmp_store.load_residential_rates()
        assert "oshawa" in comm_idx
        assert "oshawa" in res_idx

    def test_ensure_city_idempotent(self, store_with_rates):
        store_with_rates.ensure_city_in_rates("Ottawa", "ON")
        idx = store_with_rates.load_commercial_rates()
        # Existing rates should not be overwritten with zeros
        assert idx["ottawa"]["office"] == 20.0


# ── Tests: missing cities branch gaps ────────────────────────────────────────

class TestMissingCitiesBranchGaps:

    def test_load_missing_cities_deduplicates(self, tmp_path):
        """Two entries for same city with different case → merged into one."""
        comm  = str(tmp_path / "comm.json")
        res   = str(tmp_path / "res.json")
        props = str(tmp_path / "props.json")
        miss  = str(tmp_path / "miss.json")
        _write_json(comm, _comm_json())
        _write_json(res,  _res_json())
        # Write two keys that normalise to the same city
        dup_data = {
            "Ottawa, ON": {
                "city": "Ottawa", "province": "ON",
                "missing": ["commercial"], "property_types": ["Office"],
                "first_seen": "2024-01-01",
            },
            "OTTAWA, ON": {
                "city": "Ottawa", "province": "ON",
                "missing": ["residential"], "property_types": ["Retail"],
                "first_seen": "2024-01-01",
            },
        }
        _write_json(miss, dup_data)
        store = DataStore(commercial_path=comm, residential_path=res,
                          properties_path=props, missing_path=miss)
        result = store.load_missing_cities()
        # Should be merged into a single entry
        assert len(result) == 1
        entry = next(iter(result.values()))
        # Both missing types should be present
        assert "commercial" in entry["missing"]
        assert "residential" in entry["missing"]

    def test_load_missing_cities_dedup_merges_property_types(self, tmp_path):
        """Dedup merges property_types lists from both duplicate entries."""
        comm  = str(tmp_path / "comm.json")
        res   = str(tmp_path / "res.json")
        props = str(tmp_path / "props.json")
        miss  = str(tmp_path / "miss.json")
        _write_json(comm, _comm_json())
        _write_json(res,  _res_json())
        dup_data = {
            "Kingston, ON": {
                "city": "Kingston", "province": "ON",
                "missing": ["commercial"], "property_types": ["Office"],
                "first_seen": "2024-01-01",
            },
            "kingston, on": {
                "city": "Kingston", "province": "ON",
                "missing": ["commercial"], "property_types": ["Retail"],
                "first_seen": "2024-01-01",
            },
        }
        _write_json(miss, dup_data)
        store = DataStore(commercial_path=comm, residential_path=res,
                          properties_path=props, missing_path=miss)
        result = store.load_missing_cities()
        assert len(result) == 1
        entry = next(iter(result.values()))
        assert "Office" in entry["property_types"]
        assert "Retail" in entry["property_types"]

    def test_log_missing_city_renames_different_case_key(self, tmp_path):
        """log_missing_city normalises an existing key with different casing."""
        comm  = str(tmp_path / "comm.json")
        res   = str(tmp_path / "res.json")
        props = str(tmp_path / "props.json")
        miss  = str(tmp_path / "miss.json")
        _write_json(comm, _comm_json())
        _write_json(res,  _res_json())
        # Pre-populate with a differently-cased key
        existing = {
            "OSHAWA, ON": {
                "city": "Oshawa", "province": "ON",
                "missing": ["commercial"], "property_types": [],
                "first_seen": "2024-01-01",
            }
        }
        _write_json(miss, existing)
        store = DataStore(commercial_path=comm, residential_path=res,
                          properties_path=props, missing_path=miss)
        store.log_missing_city("Oshawa", "ON", "residential")
        data = store.load_missing_cities()
        # Key should now be normalised to "Oshawa, ON"
        assert "Oshawa, ON" in data
        assert "OSHAWA, ON" not in data

    def test_clear_missing_city_key_not_in_data(self, tmp_store):
        """clear_missing_city with a non-existent key is a no-op (no error)."""
        tmp_store.log_missing_city("Barrie", "ON", "commercial")
        tmp_store.clear_missing_city("Nonexistent, ON")  # should not raise
        data = tmp_store.load_missing_cities()
        assert any("Barrie" in k for k in data)  # existing entry untouched

    def test_ensure_city_with_existing_missing_rent_path(self, tmp_path):
        """ensure_city_in_rates reads existing MISSING_RENT_PATH and updates it."""
        from unittest.mock import patch
        comm  = str(tmp_path / "comm.json")
        res   = str(tmp_path / "res.json")
        props = str(tmp_path / "props.json")
        miss  = str(tmp_path / "miss.json")
        _write_json(comm, _comm_json())
        _write_json(res,  _res_json())
        store = DataStore(commercial_path=comm, residential_path=res,
                          properties_path=props, missing_path=miss)

        missing_rent_path = str(tmp_path / "json" / "missing_rent_data.json")
        os.makedirs(str(tmp_path / "json"), exist_ok=True)
        _write_json(missing_rent_path, {"Existing, ON": {"city": "Existing", "province": "ON",
                                                          "first_seen": "2024-01-01"}})
        with patch.object(type(store), "MISSING_RENT_PATH", missing_rent_path):
            store.ensure_city_in_rates("Newcity", "ON")

        with open(missing_rent_path) as f:
            data = json.load(f)
        assert any("Newcity" in k for k in data)

    def test_ensure_city_corrupted_missing_rent_file(self, tmp_path):
        """ensure_city_in_rates handles a corrupted MISSING_RENT_PATH gracefully."""
        from unittest.mock import patch
        comm  = str(tmp_path / "comm.json")
        res   = str(tmp_path / "res.json")
        props = str(tmp_path / "props.json")
        miss  = str(tmp_path / "miss.json")
        _write_json(comm, _comm_json())
        _write_json(res,  _res_json())
        store = DataStore(commercial_path=comm, residential_path=res,
                          properties_path=props, missing_path=miss)

        missing_rent_path = str(tmp_path / "json" / "missing_rent_data.json")
        os.makedirs(str(tmp_path / "json"), exist_ok=True)
        with open(missing_rent_path, "w") as f:
            f.write("NOT JSON {{{")
        with patch.object(type(store), "MISSING_RENT_PATH", missing_rent_path):
            store.ensure_city_in_rates("Testcity", "ON")  # should not raise

    def test_save_commercial_city_key_not_in_missing(self, tmp_store):
        """save_commercial_city when city not in missing report → early return, no error."""
        tmp_store.save_commercial_city("Barrie", "ON", {"Office": 25.0})
        # No entry in missing → nothing to remove; just verifies no crash
        rates = tmp_store.load_commercial_rates()
        assert "barrie" in rates

    def test_save_commercial_city_still_missing_types(self, tmp_store):
        """save_commercial_city when only SOME property_types are provided → keep remaining."""
        tmp_store.log_missing_city("Barrie", "ON", "commercial", ["Office", "Retail"])
        # Only supply Office rate
        tmp_store.save_commercial_city("Barrie", "ON", {"Office": 25.0})
        data = tmp_store.load_missing_cities()
        entry = next((v for k, v in data.items() if "Barrie" in k), None)
        assert entry is not None
        assert "Retail" in entry["property_types"]

    def test_save_commercial_city_all_types_provided_removes_entry(self, tmp_store):
        """save_commercial_city providing all needed types → entry removed from missing."""
        tmp_store.log_missing_city("Barrie", "ON", "commercial", ["Office"])
        tmp_store.save_commercial_city("Barrie", "ON", {"Office": 25.0})
        data = tmp_store.load_missing_cities()
        assert not any("Barrie" in k for k in data)

    def test_save_commercial_city_commercial_not_in_missing_types(self, tmp_store):
        """save_commercial_city when entry exists but 'commercial' NOT in missing list."""
        tmp_store.log_missing_city("Barrie", "ON", "residential")  # only residential missing
        tmp_store.save_commercial_city("Barrie", "ON", {"Office": 25.0})
        data = tmp_store.load_missing_cities()
        # Entry should still exist (residential still missing)
        entry = next((v for k, v in data.items() if "Barrie" in k), None)
        assert entry is not None
        assert "residential" in entry["missing"]

    def test_save_commercial_city_entry_has_remaining_missing(self, tmp_store):
        """save_commercial_city: commercial removed but other types remain → entry kept."""
        tmp_store.log_missing_city("Barrie", "ON", "commercial")
        tmp_store.log_missing_city("Barrie", "ON", "residential")
        tmp_store.save_commercial_city("Barrie", "ON", {})  # no needed_types
        data = tmp_store.load_missing_cities()
        entry = next((v for k, v in data.items() if "Barrie" in k), None)
        assert entry is not None
        assert "residential" in entry["missing"]

    def test_save_residential_city_key_not_in_missing(self, tmp_store):
        """save_residential_city when city not in missing → early return, no error."""
        tmp_store.save_residential_city("Barrie", "ON", {"one_br": 1200})
        rates = tmp_store.load_residential_rates()
        assert "barrie" in rates

    def test_save_residential_city_residential_not_in_missing(self, tmp_store):
        """save_residential_city when 'residential' NOT in entry's missing list."""
        tmp_store.log_missing_city("Barrie", "ON", "commercial")  # only commercial missing
        tmp_store.save_residential_city("Barrie", "ON", {"one_br": 1200})
        data = tmp_store.load_missing_cities()
        entry = next((v for k, v in data.items() if "Barrie" in k), None)
        assert entry is not None
        assert "commercial" in entry["missing"]

    def test_save_residential_city_entry_has_remaining_missing(self, tmp_store):
        """save_residential_city: residential removed but commercial remains → entry kept."""
        tmp_store.log_missing_city("Barrie", "ON", "commercial")
        tmp_store.log_missing_city("Barrie", "ON", "residential")
        tmp_store.save_residential_city("Barrie", "ON", {"one_br": 1200})
        data = tmp_store.load_missing_cities()
        entry = next((v for k, v in data.items() if "Barrie" in k), None)
        assert entry is not None
        assert "commercial" in entry["missing"]

    def test_load_missing_cities_dedup_skips_already_present_property_type(self, tmp_path):
        """140->139: duplicate entry has a type already in the first entry → if False → loop continues."""
        comm  = str(tmp_path / "comm.json")
        res   = str(tmp_path / "res.json")
        props = str(tmp_path / "props.json")
        miss  = str(tmp_path / "miss.json")
        _write_json(comm, _comm_json())
        _write_json(res,  _res_json())
        # Second entry's property_types contains "Office" which is already in the first
        dup_data = {
            "Ottawa, ON": {
                "city": "Ottawa", "province": "ON",
                "missing": ["commercial"],
                "property_types": ["Office", "Retail"],
                "first_seen": "2024-01-01",
            },
            "OTTAWA, ON": {
                "city": "Ottawa", "province": "ON",
                "missing": ["residential"],
                "property_types": ["Office"],   # "Office" already present → if False → 140->139
                "first_seen": "2024-01-01",
            },
        }
        _write_json(miss, dup_data)
        store = DataStore(commercial_path=comm, residential_path=res,
                          properties_path=props, missing_path=miss)
        result = store.load_missing_cities()
        assert len(result) == 1
        entry = next(iter(result.values()))
        # "Office" should not be duplicated
        assert entry["property_types"].count("Office") == 1

    def test_log_missing_city_duplicate_property_type_not_re_added(self, tmp_store):
        """169->168: log same property_type twice → if pt not in [...] is False → loop continues."""
        tmp_store.log_missing_city("Barrie", "ON", "commercial", ["Office"])
        tmp_store.log_missing_city("Barrie", "ON", "commercial", ["Office"])  # second call, same type
        data = tmp_store.load_missing_cities()
        entry = next(v for k, v in data.items() if "Barrie" in k)
        assert entry["property_types"].count("Office") == 1  # not duplicated

    def test_ensure_city_missing_rent_path_does_not_exist(self, tmp_path):
        """210->215: MISSING_RENT_PATH doesn't exist → os.path.exists is False → 210->215 branch."""
        from unittest.mock import patch as _patch
        comm  = str(tmp_path / "comm.json")
        res   = str(tmp_path / "res.json")
        props = str(tmp_path / "props.json")
        miss  = str(tmp_path / "miss.json")
        _write_json(comm, _comm_json())
        _write_json(res,  _res_json())
        store = DataStore(commercial_path=comm, residential_path=res,
                          properties_path=props, missing_path=miss)
        # Point MISSING_RENT_PATH at a path that definitely does NOT exist
        nonexistent = str(tmp_path / "no_such_dir" / "missing_rent.json")
        with _patch.object(type(store), "MISSING_RENT_PATH", nonexistent):
            store.ensure_city_in_rates("Brandnew", "ON")   # needs_update=True, file absent
        # File should now be created by ensure_city_in_rates
        assert os.path.exists(nonexistent)


# ── Tests: CommercialRentLoader ───────────────────────────────────────────────

class TestCommercialRentLoader:
    def test_found(self, store_with_rates):
        loader = CommercialRentLoader(store_with_rates)
        assert loader.get_rent_per_sqft("Ottawa", "ON", "Office") == 20.0

    def test_case_insensitive(self, store_with_rates):
        loader = CommercialRentLoader(store_with_rates)
        assert loader.get_rent_per_sqft("ottawa", "ON", "retail") == 30.0

    def test_missing_city(self, store_with_rates):
        loader = CommercialRentLoader(store_with_rates)
        assert loader.get_rent_per_sqft("Timbuktu", "ON", "Office") is None

    def test_missing_type(self, store_with_rates):
        loader = CommercialRentLoader(store_with_rates)
        assert loader.get_rent_per_sqft("Ottawa", "ON", "Hotel") is None


# ── Tests: ResidentialRentLoader ──────────────────────────────────────────────

class TestResidentialRentLoader:
    def test_found(self, store_with_rates):
        loader = ResidentialRentLoader(store_with_rates)
        rates = loader.get_rates("Ottawa", "ON")
        assert rates is not None
        assert rates["one_br"] == 1200.0

    def test_case_insensitive(self, store_with_rates):
        loader = ResidentialRentLoader(store_with_rates)
        assert loader.get_rates("OTTAWA", "ON") is not None

    def test_missing_city(self, store_with_rates):
        loader = ResidentialRentLoader(store_with_rates)
        assert loader.get_rates("Timbuktu", "ON") is None
