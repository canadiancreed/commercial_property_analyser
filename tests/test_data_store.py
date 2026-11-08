import os
import pytest
from data.store import DataStore, CommercialRentLoader, ResidentialRentLoader


# ── DataStore fixtures (v5.0.0: all data lives in the DB; no JSON files) ────────

@pytest.fixture
def tmp_store(tmp_path):
    return DataStore(properties_path=str(tmp_path / "props.db"))


def test_price_check_progress_roundtrip(tmp_store):
    assert tmp_store.load_price_check_progress() == {}

    tmp_store.save_price_check_result("1 Main St||2024-01-01",
                                      {"status": "dropped", "stored": 500_000})
    tmp_store.save_price_check_result("2 King St||2024-02-02",
                                      {"status": "error"})

    progress = tmp_store.load_price_check_progress()
    assert set(progress) == {"1 Main St||2024-01-01", "2 King St||2024-02-02"}
    assert progress["1 Main St||2024-01-01"]["status"] == "dropped"

    # Re-saving the same key overwrites rather than duplicates.
    tmp_store.save_price_check_result("2 King St||2024-02-02", {"status": "same"})
    assert tmp_store.load_price_check_progress()["2 King St||2024-02-02"]["status"] == "same"

    tmp_store.clear_price_check_progress()
    assert tmp_store.load_price_check_progress() == {}


@pytest.fixture
def store_with_rates(tmp_path):
    s = DataStore(properties_path=str(tmp_path / "props.db"))
    s.save_commercial_rates("Ottawa", "ON",
                            {"Office": 20.0, "Retail": 30.0, "Industrial": 12.0, "Mixed-Use": 18.0})
    s.save_residential_rates("Ottawa", "ON",
                             {"bachelor": 900, "one_br": 1200, "two_br": 1600,
                              "three_br": 1900, "four_br": 2200, "unknown": 1360})
    return s


# ── Tests: _read / _write (the JSON helpers remain for ad-hoc use) ─────────────

class TestReadWrite:
    def test_read_missing_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            DataStore._read(str(tmp_path / "missing.json"))

    def test_write_and_read(self, tmp_path):
        path = str(tmp_path / "data.json")
        DataStore._write(path, {"key": "value"})
        assert DataStore._read(path) == {"key": "value"}

    def test_write_no_tmp_file_left_behind(self, tmp_path):
        path = str(tmp_path / "data.json")
        DataStore._write(path, {"key": "value"})
        assert not os.path.exists(path + ".tmp")

    def test_write_replaces_atomically(self, tmp_path):
        path = str(tmp_path / "data.json")
        DataStore._write(path, {"version": 1})
        DataStore._write(path, {"version": 2})
        assert DataStore._read(path) == {"version": 2}

    def test_first_write_creates_no_bak(self, tmp_path):
        path = str(tmp_path / "data.json")
        DataStore._write(path, {"version": 1})
        assert not os.path.exists(path + ".bak")

    def test_rewrite_keeps_bak_of_previous_content(self, tmp_path):
        path = str(tmp_path / "data.json")
        DataStore._write(path, {"version": 1})
        DataStore._write(path, {"version": 2})
        assert DataStore._read(path + ".bak") == {"version": 1}


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

    def test_save_commercial_city(self, store_with_rates):
        store_with_rates.log_missing_city("Ottawa", "ON", "commercial", ["Office"])
        store_with_rates.save_commercial_city("Ottawa", "ON", {"Office": 22.0})
        idx = store_with_rates.load_commercial_rates()
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

    def test_save_residential_city_removes_missing(self, tmp_store):
        tmp_store.log_missing_city("Hamilton", "ON", "residential")
        tmp_store.save_residential_city("Hamilton", "ON", {"one_br": 1000})
        assert "Hamilton, ON" not in tmp_store.load_missing_cities()


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
        assert len(tmp_store.load_properties()) == 1

    def test_delete_out_of_range(self, tmp_store):
        assert tmp_store.delete_property(5) is False

    def test_update_property(self, tmp_store):
        tmp_store.save_property(self._record())
        tmp_store.update_property(0, {"asking_price": 400_000})
        assert tmp_store.load_properties()[0]["asking_price"] == 400_000

    def test_update_out_of_range(self, tmp_store):
        assert tmp_store.update_property(99, {"x": 1}) is False


# ── Tests: missing cities (app_data-backed) ───────────────────────────────────

class TestMissingCities:
    def test_load_when_empty(self, tmp_store):
        assert tmp_store.load_missing_cities() == {}

    def test_log_creates_entry(self, tmp_store):
        tmp_store.log_missing_city("Barrie", "ON", "commercial", ["Office"])
        assert any("Barrie" in k for k in tmp_store.load_missing_cities())

    def test_log_no_duplicates(self, tmp_store):
        tmp_store.log_missing_city("Barrie", "ON", "commercial")
        tmp_store.log_missing_city("Barrie", "ON", "commercial")
        entry = next(v for k, v in tmp_store.load_missing_cities().items() if "Barrie" in k)
        assert entry["missing"].count("commercial") == 1

    def test_clear_missing_city(self, tmp_store):
        tmp_store.log_missing_city("Barrie", "ON", "commercial")
        key = next(k for k in tmp_store.load_missing_cities() if "Barrie" in k)
        tmp_store.clear_missing_city(key)
        assert tmp_store.load_missing_cities() == {}

    def test_ensure_city_adds_entries(self, tmp_store):
        tmp_store.ensure_city_in_rates("Oshawa", "ON")
        assert "oshawa" in tmp_store.load_commercial_rates()
        assert "oshawa" in tmp_store.load_residential_rates()

    def test_ensure_city_idempotent(self, store_with_rates):
        store_with_rates.ensure_city_in_rates("Ottawa", "ON")
        idx = store_with_rates.load_commercial_rates()
        assert idx["ottawa"]["office"] == 20.0   # existing rates not overwritten


class TestMissingCitiesBranchGaps:
    def test_load_missing_cities_deduplicates(self, tmp_store):
        """Two entries for same city with different case → merged into one."""
        tmp_store.write_app_data("missing_cities", {
            "Ottawa, ON": {"city": "Ottawa", "province": "ON", "missing": ["commercial"],
                           "property_types": ["Office"], "first_seen": "2024-01-01"},
            "OTTAWA, ON": {"city": "Ottawa", "province": "ON", "missing": ["residential"],
                           "property_types": ["Retail"], "first_seen": "2024-01-01"},
        })
        result = tmp_store.load_missing_cities()
        assert len(result) == 1
        entry = next(iter(result.values()))
        assert "commercial" in entry["missing"] and "residential" in entry["missing"]

    def test_load_missing_cities_dedup_merges_property_types(self, tmp_store):
        tmp_store.write_app_data("missing_cities", {
            "Kingston, ON": {"city": "Kingston", "province": "ON", "missing": ["commercial"],
                             "property_types": ["Office"], "first_seen": "2024-01-01"},
            "kingston, on": {"city": "Kingston", "province": "ON", "missing": ["commercial"],
                             "property_types": ["Retail"], "first_seen": "2024-01-01"},
        })
        result = tmp_store.load_missing_cities()
        assert len(result) == 1
        entry = next(iter(result.values()))
        assert "Office" in entry["property_types"] and "Retail" in entry["property_types"]

    def test_log_missing_city_renames_different_case_key(self, tmp_store):
        tmp_store.write_app_data("missing_cities", {
            "OSHAWA, ON": {"city": "Oshawa", "province": "ON", "missing": ["commercial"],
                           "property_types": [], "first_seen": "2024-01-01"},
        })
        tmp_store.log_missing_city("Oshawa", "ON", "residential")
        data = tmp_store.load_missing_cities()
        assert "Oshawa, ON" in data and "OSHAWA, ON" not in data

    def test_clear_missing_city_key_not_in_data(self, tmp_store):
        tmp_store.log_missing_city("Barrie", "ON", "commercial")
        tmp_store.clear_missing_city("Nonexistent, ON")  # no-op
        assert any("Barrie" in k for k in tmp_store.load_missing_cities())

    def test_ensure_city_records_missing_rent_entry(self, tmp_store):
        """ensure_city_in_rates records a new city in the missing_rent_data report."""
        tmp_store.write_app_data("missing_rent_data",
                                 {"Existing, ON": {"city": "Existing", "province": "ON",
                                                   "first_seen": "2024-01-01"}})
        tmp_store.ensure_city_in_rates("Newcity", "ON")
        data = tmp_store.read_app_data("missing_rent_data")
        assert any("Newcity" in k for k in data)
        assert "Existing, ON" in data   # existing entry preserved

    def test_save_commercial_city_key_not_in_missing(self, tmp_store):
        tmp_store.save_commercial_city("Barrie", "ON", {"Office": 25.0})
        assert "barrie" in tmp_store.load_commercial_rates()

    def test_save_commercial_city_still_missing_types(self, tmp_store):
        tmp_store.log_missing_city("Barrie", "ON", "commercial", ["Office", "Retail"])
        tmp_store.save_commercial_city("Barrie", "ON", {"Office": 25.0})
        entry = next((v for k, v in tmp_store.load_missing_cities().items() if "Barrie" in k), None)
        assert entry is not None and "Retail" in entry["property_types"]

    def test_save_commercial_city_all_types_provided_removes_entry(self, tmp_store):
        tmp_store.log_missing_city("Barrie", "ON", "commercial", ["Office"])
        tmp_store.save_commercial_city("Barrie", "ON", {"Office": 25.0})
        assert not any("Barrie" in k for k in tmp_store.load_missing_cities())

    def test_save_commercial_city_commercial_not_in_missing_types(self, tmp_store):
        tmp_store.log_missing_city("Barrie", "ON", "residential")
        tmp_store.save_commercial_city("Barrie", "ON", {"Office": 25.0})
        entry = next((v for k, v in tmp_store.load_missing_cities().items() if "Barrie" in k), None)
        assert entry is not None and "residential" in entry["missing"]

    def test_save_commercial_city_entry_has_remaining_missing(self, tmp_store):
        tmp_store.log_missing_city("Barrie", "ON", "commercial")
        tmp_store.log_missing_city("Barrie", "ON", "residential")
        tmp_store.save_commercial_city("Barrie", "ON", {})
        entry = next((v for k, v in tmp_store.load_missing_cities().items() if "Barrie" in k), None)
        assert entry is not None and "residential" in entry["missing"]

    def test_save_residential_city_key_not_in_missing(self, tmp_store):
        tmp_store.save_residential_city("Barrie", "ON", {"one_br": 1200})
        assert "barrie" in tmp_store.load_residential_rates()

    def test_save_residential_city_residential_not_in_missing(self, tmp_store):
        tmp_store.log_missing_city("Barrie", "ON", "commercial")
        tmp_store.save_residential_city("Barrie", "ON", {"one_br": 1200})
        entry = next((v for k, v in tmp_store.load_missing_cities().items() if "Barrie" in k), None)
        assert entry is not None and "commercial" in entry["missing"]

    def test_save_residential_city_entry_has_remaining_missing(self, tmp_store):
        tmp_store.log_missing_city("Barrie", "ON", "commercial")
        tmp_store.log_missing_city("Barrie", "ON", "residential")
        tmp_store.save_residential_city("Barrie", "ON", {"one_br": 1200})
        entry = next((v for k, v in tmp_store.load_missing_cities().items() if "Barrie" in k), None)
        assert entry is not None and "commercial" in entry["missing"]

    def test_load_missing_cities_dedup_skips_already_present_property_type(self, tmp_store):
        tmp_store.write_app_data("missing_cities", {
            "Ottawa, ON": {"city": "Ottawa", "province": "ON", "missing": ["commercial"],
                           "property_types": ["Office", "Retail"], "first_seen": "2024-01-01"},
            "OTTAWA, ON": {"city": "Ottawa", "province": "ON", "missing": ["residential"],
                           "property_types": ["Office"], "first_seen": "2024-01-01"},
        })
        result = tmp_store.load_missing_cities()
        assert len(result) == 1
        entry = next(iter(result.values()))
        assert entry["property_types"].count("Office") == 1

    def test_log_missing_city_duplicate_property_type_not_re_added(self, tmp_store):
        tmp_store.log_missing_city("Barrie", "ON", "commercial", ["Office"])
        tmp_store.log_missing_city("Barrie", "ON", "commercial", ["Office"])
        entry = next(v for k, v in tmp_store.load_missing_cities().items() if "Barrie" in k)
        assert entry["property_types"].count("Office") == 1

    def test_ensure_city_creates_missing_rent_entry_when_absent(self, tmp_store):
        """A brand-new city records a fresh missing_rent_data entry."""
        tmp_store.ensure_city_in_rates("Brandnew", "ON")
        data = tmp_store.read_app_data("missing_rent_data")
        assert any("Brandnew" in k for k in data)


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
