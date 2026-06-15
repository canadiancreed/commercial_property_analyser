"""Entry point for the commercial property analyser."""

import os
from data.store import DataStore, CommercialRentLoader, ResidentialRentLoader
from analysis.rent_resolver import RentResolver
from ui.menu import PropertyMenu

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    store = DataStore()
    store.migrate_vacancy_rate_to_null()
    resolver = RentResolver(
        commercial_loader  = CommercialRentLoader(store),
        residential_loader = ResidentialRentLoader(store),
        data_store         = store,
    )
    PropertyMenu(store, resolver).run()
