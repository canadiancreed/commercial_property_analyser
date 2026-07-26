import json
import os
import pytest

_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture(autouse=True)
def _pin_vacancy_data(monkeypatch):
    """Point the regional vacancy resolver at committed TEST FIXTURES for every test, so
    analyzer/mixed-use golden values stay deterministic and independent of the real,
    annually-refreshed json/vacancy_rates.json + json/geographic_crosswalk.json. Tests
    that need specific tiers (test_vacancy_resolver, the demotion integration test) point
    the resolver at their own temp files afterwards, which overrides this."""
    import analysis.vacancy_resolver as vr
    monkeypatch.setattr(vr, "_VACANCY_PATH", os.path.join(_FIXTURE_DIR, "vacancy_rates.json"))
    monkeypatch.setattr(vr, "_CROSSWALK_PATH", os.path.join(_FIXTURE_DIR, "geographic_crosswalk.json"))
    vr.reset_cache()
    yield
    vr.reset_cache()


@pytest.fixture
def make_store(tmp_path):
    """Return a factory that creates a minimal DataStore backed by tmp files."""
    def _factory():
        from data.store import DataStore
        comm  = str(tmp_path / "comm.json")
        res   = str(tmp_path / "res.json")
        props = str(tmp_path / "props.json")
        miss  = str(tmp_path / "miss.json")
        for p, d in [(comm, {"cities": {}}), (res, {"cities": {}})]:
            with open(p, "w") as f:
                json.dump(d, f)
        return DataStore(commercial_path=comm, residential_path=res,
                         properties_path=props, missing_path=miss)
    return _factory
