"""Entry point for the commercial property analyser."""

import os
from version import __version__
from data.store import DataStore, CommercialRentLoader, ResidentialRentLoader
from analysis.rent_resolver import RentResolver
from analysis import (financing_config, screener_config, underwriting_config,
                      industrial_config, vacancy_resolver)
from form_logic import clean_address
from ui.menu import PropertyMenu

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print(f"Commercial Property Analyser v{__version__}")
    store = DataStore(seed=True)
    # v5.0.0: the DB is the single source of truth. Seed config/reference/rate/city data
    # from data/seeds on first run, then route every loader through the store.
    store.ensure_seeded()
    store.migrate_vacancy_rate_to_null()
    store.normalize_addresses(clean_address)  # one-time: strip city/province from legacy addresses
    financing_config.set_store(store)
    screener_config.set_store(store)
    underwriting_config.set_store(store)
    industrial_config.set_store(store)
    vacancy_resolver.set_store(store)
    resolver = RentResolver(
        commercial_loader  = CommercialRentLoader(store),
        residential_loader = ResidentialRentLoader(store),
        data_store         = store,
    )
    PropertyMenu(store, resolver).run()
