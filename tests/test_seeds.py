"""Embedded seed package (data/seeds) integrity + ensure_seeded coverage (v5.0.0).

The seed is the shipped-defaults source that replaced the json/ + config/ files, so a
regression here would silently ship a broken fresh install.
"""
import os
import tempfile

from data import seeds
from data.store import DataStore


def test_config_defaults_has_all_names_and_shapes():
    assert set(seeds.CONFIG_DEFAULTS) >= {
        "financing", "score_weights", "screener", "underwriting",
        "industrial_size_bands", "industrial_premiums", "vacancy_rates",
        "geographic_crosswalk"}
    assert "defaults" in seeds.CONFIG_DEFAULTS["financing"]
    assert "weights" in seeds.CONFIG_DEFAULTS["score_weights"]
    assert "regions" in seeds.CONFIG_DEFAULTS["vacancy_rates"]


def test_app_data_defaults_runtime_docs_empty_but_rate_cache_present():
    assert set(seeds.APP_DATA_DEFAULTS) == {
        "interest_rates", "missing_cities", "missing_rent_data", "price_check_progress"}
    # Runtime state accumulates per install → ships empty.
    assert seeds.APP_DATA_DEFAULTS["missing_cities"] == {}
    assert seeds.APP_DATA_DEFAULTS["missing_rent_data"] == {}
    assert seeds.APP_DATA_DEFAULTS["price_check_progress"] == {}
    # The fetched base-rate cache ships so the engine works offline.
    assert seeds.APP_DATA_DEFAULTS["interest_rates"].get("base_rate")


def test_rate_and_city_seeds_present_and_shaped():
    assert len(seeds.COMMERCIAL_RATES.get("cities", {})) > 50
    assert len(seeds.RESIDENTIAL_RATES.get("cities", {})) > 50
    assert len(seeds.CITY_DEMOGRAPHICS) > 50
    assert len(seeds.CITY_DISTANCES) > 50
    assert "population" in next(iter(seeds.CITY_DEMOGRAPHICS.values()))
    assert "distance_km" in next(iter(seeds.CITY_DISTANCES.values()))


def _fresh(seed=True):
    return DataStore(properties_path=os.path.join(tempfile.mkdtemp(), "seeded.db"), seed=seed)


def test_ensure_seeded_populates_a_fresh_db():
    s = _fresh()
    s.ensure_seeded()
    assert "defaults" in s.read_config("financing")
    assert s.read_config("vacancy_rates") and s.read_config("geographic_crosswalk")
    assert s.read_app_data("missing_cities") == {}            # runtime state empty
    assert s.read_app_data("interest_rates").get("base_rate")  # shipped cache
    assert len(s.load_city_demographics()) > 50
    assert len(s.load_city_distances()) > 50
    assert len(s.load_commercial_rates()) > 50


def test_ensure_seeded_is_meta_guarded_and_preserves_edits():
    path = os.path.join(tempfile.mkdtemp(), "s.db")
    DataStore(properties_path=path, seed=True).ensure_seeded()
    DataStore(properties_path=path, seed=True).write_config("financing", {"defaults": {"x": 1}})
    DataStore(properties_path=path, seed=True).ensure_seeded()   # re-seed must NOT clobber
    assert DataStore(properties_path=path).read_config("financing") == {"defaults": {"x": 1}}
