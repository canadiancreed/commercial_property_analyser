"""
v4.10.1: reanalyze_properties returns a per-property `issues` list (address + reason) for
every skipped/errored property, so the desktop "Re-analyze all" can show exactly which
properties didn't update and why.
"""
from analysis.report_builder import reanalyze_properties


def _rec(addr, city="Testville"):
    return {"address": addr, "listing_date": "2025-01-01", "city": city, "province": "ON",
            "status": "active", "property_type": "Office", "asking_price": 500_000,
            "mls_number": "MLS-" + addr}


class _FakeAnalyzer:
    """to_record() raises ValueError for SKIP*, a RuntimeError for ERR*, else echoes."""
    def __init__(self, prop, resolver):
        self._rec = prop

    def to_record(self, existing=None):
        a = (existing or {}).get("address", "")
        if a.startswith("SKIP"):
            raise ValueError("No market rate for Testville yet")
        if a.startswith("ERR"):
            raise RuntimeError("boom")
        return dict(existing)


def _seed(store, addrs):
    for a in addrs:
        store.save_property(_rec(a))


def test_issues_capture_skips_and_errors(make_store, monkeypatch):
    # Isolate the issue-collection logic from record_to_prop's mapping.
    monkeypatch.setattr("analysis.report_builder.record_to_prop", lambda p: p)
    store = make_store()
    _seed(store, ["OK 1", "SKIP 1", "ERR 1"])

    res = reanalyze_properties(store, object(), _FakeAnalyzer)

    assert res["updated"] == 1
    assert res["skipped"] == 1
    assert res["errors"] == 1
    assert res["considered"] == 3 and res["total"] == 3
    assert len(res["issues"]) == 2

    by_addr = {x["address"]: x for x in res["issues"]}
    assert "OK 1" not in by_addr                     # updated → no issue

    skip = by_addr["SKIP 1"]
    assert skip["kind"] == "skipped"
    assert "market rate" in skip["reason"].lower()
    assert skip["city"] == "Testville" and skip["mls"] == "MLS-SKIP 1"
    assert skip["property_type"] == "Office"

    err = by_addr["ERR 1"]
    assert err["kind"] == "error"
    assert "RuntimeError" in err["reason"] and "boom" in err["reason"]


def test_no_issues_when_all_update(make_store, monkeypatch):
    monkeypatch.setattr("analysis.report_builder.record_to_prop", lambda p: p)
    store = make_store()
    _seed(store, ["OK 1", "OK 2"])
    res = reanalyze_properties(store, object(), _FakeAnalyzer)
    assert res["updated"] == 2 and res["issues"] == []


def test_skip_reason_defaults_when_message_blank(make_store, monkeypatch):
    monkeypatch.setattr("analysis.report_builder.record_to_prop", lambda p: p)

    class _BlankValueError:
        def __init__(self, prop, resolver):
            pass

        def to_record(self, existing=None):
            raise ValueError()   # no message

    store = make_store()
    _seed(store, ["SKIP blank"])
    res = reanalyze_properties(store, object(), _BlankValueError)
    assert res["issues"][0]["kind"] == "skipped"
    assert res["issues"][0]["reason"] == "No market rent rate for this city yet."
