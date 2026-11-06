"""Entry point for the commercial property analyser."""

import os
from version import __version__
from data.store import DataStore, CommercialRentLoader, ResidentialRentLoader
from analysis.rent_resolver import RentResolver
from analysis import financing_config
from form_logic import clean_address
from ui.menu import PropertyMenu

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print(f"Commercial Property Analyser v{__version__}")
    store = DataStore()
    # The DB is the single source of truth for property records — no auto-import from
    # properties.json. (Rent/config reference still seed once from json/ + config/.)
    store.ensure_rates_migrated()        # one-time import of legacy rent JSON files
    store.migrate_vacancy_rate_to_null()
    store.normalize_addresses(clean_address)  # one-time: strip city/province from legacy addresses
    financing_config.set_store(store)    # financing config lives in the DB config table
                                         # (seeded once from config/financing.json)
    resolver = RentResolver(
        commercial_loader  = CommercialRentLoader(store),
        residential_loader = ResidentialRentLoader(store),
        data_store         = store,
    )
    PropertyMenu(store, resolver).run()
