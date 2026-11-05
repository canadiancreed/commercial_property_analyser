"""Entry point for the commercial property analyser."""

import os
from version import __version__
from data.store import DataStore, CommercialRentLoader, ResidentialRentLoader
from analysis.rent_resolver import RentResolver
from analysis import financing_config
from ui.menu import PropertyMenu

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print(f"Commercial Property Analyser v{__version__}")
    store = DataStore()
    store.ensure_properties_migrated()   # one-time import of legacy properties.json
    store.ensure_rates_migrated()        # one-time import of legacy rent JSON files
    store.migrate_vacancy_rate_to_null()
    financing_config.set_store(store)    # financing config lives in the DB config table
                                         # (seeded once from config/financing.json)
    resolver = RentResolver(
        commercial_loader  = CommercialRentLoader(store),
        residential_loader = ResidentialRentLoader(store),
        data_store         = store,
    )
    PropertyMenu(store, resolver).run()
