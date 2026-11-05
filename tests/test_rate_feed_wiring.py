"""
Interest-rate base feed (v4.8): the Bank of Canada GoC 5yr yield becomes the
sourced anchor under every per-type rate, which is priced as base + spread.

Covers:
  * rate_feed parsing of the Valet payload (network stubbed) + offline-safe refresh.
  * financing_config applying the live (fetched - anchor) delta as a parallel shift,
    and falling back to the authored bands when the feed or anchor is absent.
  * save_financing_config preserving every top-level key (the latent drop bug).
"""
import json

import pytest

import analysis.rate_feed as rf
import analysis.financing_config as fc


# ── A self-contained financing config (independent of the real repo file) ────

_CONFIG = {
    "_comment": "test",
    "defaults": {"down_payment_pct": 0.2, "interest_rate": 0.045, "term_years": 25, "hold_years": 10},
    "stress_test_bump": 0.02,
    "verified_date": "2026-07",
    "residential_covenant_dscr": 1.1,
    "rate_base": {"series": "BD.CDN.5YR.DQ.YLD", "label": "GoC 5yr",
                  "value": 0.035, "as_of": "2026-11-03", "source": "Bank of Canada, Valet API"},
    "property_types": {
        "office": {"max_ltv": 0.65, "rate_low": 0.06, "rate_high": 0.07,
                   "amort_years": 20, "dscr_floor": 1.3, "cmhc_eligible": False},
    },
}


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Point financing_config at a temp config + temp feed path and reset caches.
    Returns (config_path, feed_path)."""
    cfg = tmp_path / "financing.json"
    cfg.write_text(json.dumps(_CONFIG), encoding="utf-8")
    feed = tmp_path / "interest_rates.json"
    monkeypatch.setattr(fc, "_CONFIG_PATH", str(cfg))
    monkeypatch.setattr(fc, "_INTEREST_RATES_PATH", str(feed))
    fc._cache = None
    fc.reload_rate_feed()
    yield cfg, feed
    fc._cache = None
    fc.reload_rate_feed()


def _write_feed(path, base_rate, as_of="2026-11-03"):
    path.write_text(json.dumps({"base_rate": base_rate, "as_of": as_of,
                                "status": "fetched", "fetched_at": "2026-11-05T00:00:00+00:00",
                                "_meta": {"source": "Bank of Canada, Valet API"}}), encoding="utf-8")
    fc.reload_rate_feed()


# ── financing_config: the parallel shift ─────────────────────────────────────

def test_no_feed_falls_back_to_authored_bands(wired):
    cfg, feed = wired
    assert not feed.exists()
    r = fc.resolve_financing(1_200_000, "office")
    assert r["rate_adjustment"] == 0.0
    assert r["interest_rate"] == pytest.approx(0.065)      # (0.06+0.07)/2, no shift
    assert r["rate_low"] == pytest.approx(0.06)
    assert r["rate_high"] == pytest.approx(0.07)


def test_feed_equal_to_anchor_is_zero_delta(wired):
    cfg, feed = wired
    _write_feed(feed, 0.035)                                # == anchor
    r = fc.resolve_financing(1_200_000, "office")
    assert r["rate_adjustment"] == 0.0
    assert r["interest_rate"] == pytest.approx(0.065)


def test_feed_above_anchor_shifts_every_rate_in_parallel(wired):
    cfg, feed = wired
    _write_feed(feed, 0.045)                                # anchor 0.035 -> +0.010
    r = fc.resolve_financing(1_200_000, "office")
    assert r["rate_adjustment"] == pytest.approx(0.010)
    assert r["interest_rate"] == pytest.approx(0.075)       # 0.065 + 0.010
    assert r["rate_low"] == pytest.approx(0.07)
    assert r["rate_high"] == pytest.approx(0.08)
    # Unknown type uses defaults.interest_rate, also shifted.
    d = fc.resolve_financing(1_200_000, "banana")
    assert d["source"] == "defaults"
    assert d["interest_rate"] == pytest.approx(0.055)       # 0.045 + 0.010


def test_feed_below_anchor_shifts_down(wired):
    cfg, feed = wired
    _write_feed(feed, 0.030)                                # anchor 0.035 -> -0.005
    r = fc.resolve_financing(1_200_000, "office")
    assert r["interest_rate"] == pytest.approx(0.060)
    assert r["base_rate_value"] == pytest.approx(0.030)
    assert r["base_rate_source"] == "Bank of Canada, Valet API"


def test_base_rate_info_reports_live_state(wired):
    cfg, feed = wired
    _write_feed(feed, 0.040)
    info = fc.base_rate_info()
    assert info["live"] is True
    assert info["anchor"] == pytest.approx(0.035)
    assert info["fetched"] == pytest.approx(0.040)
    assert info["adjustment"] == pytest.approx(0.005)


# ── save_financing_config preserves everything (the latent drop bug) ─────────

def test_save_preserves_rate_base_and_types(wired):
    cfg, feed = wired
    fc.save_financing_config(0.25, 0.05, 30, 12)
    saved = json.loads(cfg.read_text(encoding="utf-8"))
    assert saved["defaults"] == {"down_payment_pct": 0.25, "interest_rate": 0.05,
                                 "term_years": 30, "hold_years": 12}
    # Everything else survives the save.
    assert saved["rate_base"]["value"] == 0.035
    assert "office" in saved["property_types"]
    assert saved["residential_covenant_dscr"] == 1.1
    assert saved["stress_test_bump"] == 0.02


# ── rate_feed: parsing + refresh (network stubbed) ───────────────────────────

_GROUP = {"observations": [{
    "d": "2026-11-03",
    "BD.CDN.2YR.DQ.YLD": {"v": "3.26"}, "BD.CDN.3YR.DQ.YLD": {"v": "3.36"},
    "BD.CDN.5YR.DQ.YLD": {"v": "3.49"}, "BD.CDN.7YR.DQ.YLD": {"v": "3.58"},
    "BD.CDN.10YR.DQ.YLD": {"v": "3.77"},
}]}
_POLICY = {"observations": [{"d": "2026-11-03", "V39079": {"v": "2.50"}}]}


def _fake_get(url, timeout):
    return _POLICY if "V39079" in url else _GROUP


def test_fetch_base_rate_parses_valet(monkeypatch):
    monkeypatch.setattr(rf, "_get_json", _fake_get)
    p = rf.fetch_base_rate(timeout=1)
    assert p["base_rate"] == pytest.approx(0.0349)
    assert p["as_of"] == "2026-11-03"
    assert p["status"] == "fetched"
    assert p["context"]["yield_curve"]["5yr"] == pytest.approx(0.0349)
    assert p["context"]["policy_rate"] == pytest.approx(0.025)


def test_fetch_missing_5yr_raises(monkeypatch):
    monkeypatch.setattr(rf, "_get_json", lambda url, timeout: {"observations": [{"d": "x"}]})
    with pytest.raises(ValueError):
        rf.fetch_base_rate(timeout=1)


def test_refresh_writes_when_forced(tmp_path, monkeypatch):
    monkeypatch.setattr(rf, "_get_json", _fake_get)
    out = tmp_path / "interest_rates.json"
    changed, reason = rf.refresh_interest_rates(str(out), force=True, timeout=1)
    assert changed is True and "3.49" in reason
    assert json.loads(out.read_text(encoding="utf-8"))["base_rate"] == pytest.approx(0.0349)


def test_refresh_skips_when_fresh(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    out = tmp_path / "interest_rates.json"
    now = datetime.now(timezone.utc).isoformat()
    rf.write_interest_rates({"base_rate": 0.03, "fetched_at": now}, str(out))
    # Should NOT call the network (fail loudly if it does).
    monkeypatch.setattr(rf, "_get_json", lambda *a, **k: pytest.fail("network called"))
    changed, reason = rf.refresh_interest_rates(str(out), max_age_hours=24, timeout=1)
    assert changed is False and "fresh" in reason


def test_refresh_offline_safe_keeps_existing(tmp_path, monkeypatch):
    out = tmp_path / "interest_rates.json"
    rf.write_interest_rates({"base_rate": 0.031, "fetched_at": "2000-01-01T00:00:00+00:00"}, str(out))

    def boom(url, timeout):
        raise OSError("no network")

    monkeypatch.setattr(rf, "_get_json", boom)
    changed, reason = rf.refresh_interest_rates(str(out), force=True, timeout=1)
    assert changed is False and "fetch failed" in reason
    assert json.loads(out.read_text(encoding="utf-8"))["base_rate"] == 0.031   # untouched
