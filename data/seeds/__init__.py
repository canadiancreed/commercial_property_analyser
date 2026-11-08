"""Embedded seed data (data-as-code) that populates the SQLite DB on first run.
Replaces the former config/ + json/ shipped files; the DB is the live source at runtime.
Regenerate from external feeds via scripts/fetch_*.py (which now write the DB)."""
from data.seeds.config_defaults import CONFIG_DEFAULTS as _CONFIG_DEFAULTS
from data.seeds.crosswalk import GEOGRAPHIC_CROSSWALK
from data.seeds.app_data_defaults import APP_DATA_DEFAULTS
from data.seeds.rates import COMMERCIAL_RATES, RESIDENTIAL_RATES
from data.seeds.cities import CITY_DEMOGRAPHICS, CITY_DISTANCES

# config-table documents, by read_config name.
CONFIG_DEFAULTS = dict(_CONFIG_DEFAULTS)
CONFIG_DEFAULTS["geographic_crosswalk"] = GEOGRAPHIC_CROSSWALK

__all__ = ["CONFIG_DEFAULTS", "APP_DATA_DEFAULTS", "GEOGRAPHIC_CROSSWALK",
           "COMMERCIAL_RATES", "RESIDENTIAL_RATES", "CITY_DEMOGRAPHICS", "CITY_DISTANCES"]
