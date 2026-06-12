import json
import pytest


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
