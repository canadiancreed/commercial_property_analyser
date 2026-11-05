"""
v4.9.0 — Settings config lives in the SQLite `config` table.

Covers the generic config store (seed-on-read, upsert), financing-config routed
through a store (set_store / save_financing_config / save_raw), and the scorer
config routed through the same table. Store-less financing access still uses the
file (tested elsewhere / by the broader suite).
"""
import json

import pytest

import analysis.financing_config as fc


@pytest.fixture(autouse=True)
def _reset_financing_store():
    """Financing config keeps module-level store/cache globals — reset after each
    test so one test's injected store never leaks into the next."""
    yield
    fc.set_store(None)
    fc._cache = None


# ── Generic config table ─────────────────────────────────────────────────────

def test_read_config_seeds_from_file_once(make_store, tmp_path):
    store = make_store()
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert store.read_config("thing", str(seed)) == {"a": 1}
    # Row now exists; a later read ignores a changed seed file (DB is the source).
    seed.write_text(json.dumps({"a": 2}), encoding="utf-8")
    assert store.read_config("thing", str(seed)) == {"a": 1}


def test_read_config_missing_returns_empty(make_store, tmp_path):
    store = make_store()
    assert store.read_config("none", str(tmp_path / "nope.json")) == {}
    assert store.read_config("none") == {}


def test_write_config_upserts(make_store):
    store = make_store()
    store.write_config("k", {"x": 1})
    assert store.read_config("k") == {"x": 1}
    store.write_config("k", {"x": 2, "y": 3})
    assert store.read_config("k") == {"x": 2, "y": 3}


# ── Financing config routed through the store ────────────────────────────────

def test_financing_resolves_via_store(make_store):
    store = make_store()
    fc.set_store(store)
    r = fc.resolve_financing(1_200_000, "office")   # seeds the DB from config/financing.json
    assert r["interest_rate"] == pytest.approx(0.065)   # authored midpoint, delta 0 at anchor
    # The config now lives in the DB table.
    assert "office" in store.read_config("financing")["property_types"]


def test_save_financing_config_persists_to_db(make_store):
    store = make_store()
    fc.set_store(store)
    fc.resolve_financing(1_200_000, "office")       # seed first
    fc.save_financing_config(0.25, 0.05, 30, 12)
    saved = store.read_config("financing")
    assert saved["defaults"] == {"down_payment_pct": 0.25, "interest_rate": 0.05,
                                 "term_years": 30, "hold_years": 12}
    # Per-type rules + anchor survive the defaults-only save.
    assert "office" in saved["property_types"]
    assert "rate_base" in saved


def test_save_raw_roundtrips_via_store(make_store):
    store = make_store()
    fc.set_store(store)
    raw = fc.get_raw_config()
    raw["property_types"]["office"]["rate_high"] = 0.08
    fc.save_raw(raw)
    r = fc.resolve_financing(1_200_000, "office")
    assert r["rate_high"] == pytest.approx(0.08)
    assert store.read_config("financing")["property_types"]["office"]["rate_high"] == pytest.approx(0.08)


def test_save_raw_rejects_bad_config(make_store):
    store = make_store()
    fc.set_store(store)
    with pytest.raises(fc.FinancingConfigError):
        fc.save_raw({"property_types": {}})          # no defaults block
    with pytest.raises(fc.FinancingConfigError):
        fc.save_raw("not a dict")


def test_set_store_none_reverts_to_file(make_store):
    store = make_store()
    fc.set_store(store)
    fc.resolve_financing(1_200_000, "office")
    fc.set_store(None)                               # back to the repo file
    assert fc.load_financing_config()["down_payment_pct"] == pytest.approx(0.2)


# ── Scorer config routed through the same table ──────────────────────────────

def test_scorer_config_via_store(make_store):
    from scoring.scorer import PropertyScorer
    store = make_store()
    cfg = PropertyScorer(store).load_config()        # seeds from json/score_weights.json
    assert "weights" in cfg
    cfg["weights"]["Cap Rate"] = 0.42
    PropertyScorer(store).save_config(cfg)
    assert store.read_config("score_weights")["weights"]["Cap Rate"] == pytest.approx(0.42)
