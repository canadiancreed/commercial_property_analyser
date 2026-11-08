import json
import os
import pytest

_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _fixture(name):
    with open(os.path.join(_FIXTURE_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def seed_vacancy_store(store):
    """Load the committed vacancy/crosswalk TEST FIXTURES into a store's config table and
    point the resolver at it. Returns the store. (v5.0.0: the resolver reads the DB, not
    json files.)"""
    import analysis.vacancy_resolver as vr
    store.write_config("vacancy_rates", _fixture("vacancy_rates.json"))
    store.write_config("geographic_crosswalk", _fixture("geographic_crosswalk.json"))
    vr.set_store(store)
    vr.reset_cache()
    return store


@pytest.fixture(autouse=True)
def _pin_vacancy_data(tmp_path_factory):
    """Pin the regional vacancy resolver to the committed TEST FIXTURES for every test, so
    analyzer/mixed-use golden values stay deterministic and independent of the real,
    annually-refreshed vacancy data. Tests that need specific tiers (test_vacancy_resolver,
    the demotion integration test) call seed_vacancy_store() with their own data, which
    overrides this."""
    import analysis.vacancy_resolver as vr
    from data.store import DataStore
    d = tmp_path_factory.mktemp("vac")
    seed_vacancy_store(DataStore(properties_path=str(d / "vac.db")))
    yield
    vr.set_store(None)
    vr.reset_cache()


@pytest.fixture
def make_store(tmp_path):
    """Return a factory that creates a minimal (empty, unseeded) DataStore in tmp."""
    def _factory():
        from data.store import DataStore
        return DataStore(properties_path=str(tmp_path / "props.db"))
    return _factory
