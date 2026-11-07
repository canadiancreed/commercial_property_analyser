"""
Unit tests for history_logic.py (4.12.0) — the pure helpers that record a property's
price / status changes and build the timeline shown in the property report.

Covered:
  * record_price_change — append on a real move, skip within $1, skip on missing data,
    never mutate the input list
  * record_status_change — append on a real change, case-insensitive, skip same/blank
  * build_timeline — seeded "Listed" baseline, price direction, status events, ordering,
    and tolerance of records with no history keys
"""
import history_logic as hl


# ── record_price_change ───────────────────────────────────────────────────────

def test_price_change_appends_on_move():
    out = hl.record_price_change([], 1_000_000, 950_000, "2026-11-07")
    assert out == [{"date": "2026-11-07", "price": 950_000.0}]


def test_price_change_skips_within_tolerance():
    # A sub-$1 move is rounding noise, not a change.
    assert hl.record_price_change([], 1_000_000, 1_000_000.5, "2026-11-07") == []


def test_price_change_skips_on_missing_price():
    assert hl.record_price_change([], None, 950_000, "2026-11-07") == []
    assert hl.record_price_change([], 1_000_000, None, "2026-11-07") == []
    assert hl.record_price_change([], 1_000_000, "oops", "2026-11-07") == []


def test_price_change_does_not_mutate_input():
    original = [{"date": "2026-01-01", "price": 1_000_000.0}]
    out = hl.record_price_change(original, 1_000_000, 900_000, "2026-11-07")
    assert original == [{"date": "2026-01-01", "price": 1_000_000.0}]   # untouched
    assert len(out) == 2


def test_price_change_tolerates_none_history():
    assert hl.record_price_change(None, 1_000_000, 900_000, "2026-11-07") == \
        [{"date": "2026-11-07", "price": 900_000.0}]


# ── record_status_change ──────────────────────────────────────────────────────

def test_status_change_appends_on_change():
    assert hl.record_status_change([], "active", "inactive", "2026-11-07") == \
        [{"date": "2026-11-07", "status": "inactive"}]


def test_status_change_case_insensitive_same():
    assert hl.record_status_change([], "Active", "active", "2026-11-07") == []


def test_status_change_skips_blank():
    assert hl.record_status_change([], "", "active", "2026-11-07") == []
    assert hl.record_status_change([], "active", "", "2026-11-07") == []


def test_status_change_reactivation():
    assert hl.record_status_change([], "inactive", "active", "2026-11-07") == \
        [{"date": "2026-11-07", "status": "active"}]


# ── build_timeline ────────────────────────────────────────────────────────────

def test_timeline_seeds_listed_baseline():
    # A record that predates tracking shows only the Listed baseline.
    rec = {"listing_date": "2024-03-01", "original_price": 1_080_000}
    assert hl.build_timeline(rec) == [
        {"date": "2024-03-01", "kind": "listed", "price": 1_080_000.0},
    ]


def test_timeline_omits_baseline_without_original_price():
    assert hl.build_timeline({"listing_date": "2024-03-01"}) == []
    assert hl.build_timeline({"listing_date": "2024-03-01", "original_price": 0}) == []


def test_timeline_price_direction_relative_to_previous():
    rec = {
        "listing_date": "2024-03-01", "original_price": 1_000_000,
        "price_history": [
            {"date": "2025-01-01", "price": 900_000},   # down vs 1,000,000
            {"date": "2025-06-01", "price": 950_000},   # up vs 900,000
        ],
    }
    tl = hl.build_timeline(rec)
    assert [e["kind"] for e in tl] == ["listed", "price", "price"]
    assert tl[1]["dir"] == "down"
    assert tl[2]["dir"] == "up"


def test_timeline_includes_status_and_sorts_by_date():
    rec = {
        "listing_date": "2024-03-01", "original_price": 1_000_000,
        "price_history":  [{"date": "2025-06-01", "price": 900_000}],
        "status_history": [{"date": "2025-02-01", "status": "inactive"}],
    }
    tl = hl.build_timeline(rec)
    assert [(e["date"], e["kind"]) for e in tl] == [
        ("2024-03-01", "listed"),
        ("2025-02-01", "status"),
        ("2025-06-01", "price"),
    ]
    assert tl[1]["status"] == "inactive"


def test_timeline_tolerates_missing_keys():
    assert hl.build_timeline({}) == []
