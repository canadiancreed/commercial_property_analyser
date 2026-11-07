"""
Pure, UI-free helpers for a property's price & status history timeline (4.12.0).

The data model never snapshotted a dated history of price or status changes — a
record carries only its CURRENT ``asking_price`` / ``status`` plus the original
list price and the listing date. These helpers:

  * record a dated entry when a save changes the asking price or the status
    (``record_price_change`` / ``record_status_change``), appending to the two
    arrays carried on the record (``price_history`` / ``status_history``), and
  * build a display-ready timeline for the report (``build_timeline``): a seeded
    "Listed" baseline (listing date + original list price) followed by the
    recorded changes, in chronological order.

Kept top-level (like ``form_logic``) and free of any ``nicegui`` / DB import so it
can be unit-tested on plain dicts and so the PyInstaller build resolves it from the
root copy. History is captured only when a property is edited/saved in the app;
re-analysis re-reads the same stored values, so it never adds a spurious entry.
"""
from __future__ import annotations

# Prices are whole dollars; treat a move within $1 as "no change" so rounding or
# formatting jitter never registers as a price change (matches the price-check and
# price-drop reports' tolerance).
PRICE_TOLERANCE = 1.0


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def record_price_change(history, old_price, new_price, today):
    """Return ``history`` with a dated entry appended when the asking price moved.

    A change is recorded only when both prices are known and they differ by more
    than ``PRICE_TOLERANCE``. The input list is never mutated.
    """
    hist = list(history or [])
    old = _to_float(old_price)
    new = _to_float(new_price)
    if old is None or new is None:
        return hist
    if abs(new - old) > PRICE_TOLERANCE:
        hist.append({"date": today, "price": new})
    return hist


def record_status_change(history, old_status, new_status, today):
    """Return ``history`` with a dated entry appended when the status changed.

    Status is normalized (trimmed, lower-cased) before comparison; an entry is
    recorded only when both are known and differ. The input list is never mutated.
    """
    hist = list(history or [])
    old = (old_status or "").strip().lower()
    new = (new_status or "").strip().lower()
    if old and new and old != new:
        hist.append({"date": today, "status": new})
    return hist


def build_timeline(record):
    """Build a chronological, display-ready timeline for one property record.

    Returns a list of event dicts, each with a ``kind`` of:
      * ``"listed"`` — the seeded baseline: ``{date, price}`` from the record's
        ``listing_date`` + ``original_price`` (omitted when no original price).
      * ``"price"``  — a recorded asking-price change: ``{date, price, dir}`` where
        ``dir`` is ``"down"`` / ``"up"`` relative to the previous price in the
        sequence (``""`` when the direction is unknown).
      * ``"status"`` — a recorded status change: ``{date, status}``.

    Events are sorted by date ascending (the baseline, with the earliest/blank
    date, sorts first). Records that predate history tracking show only the
    baseline until their next edited change is recorded.
    """
    events = []

    listed_date = record.get("listing_date") or ""
    original = _to_float(record.get("original_price"))
    if original is not None and original > 0:
        events.append({"date": listed_date, "kind": "listed", "price": original})

    # Price changes, with a direction relative to the previous known price (the
    # baseline original price, then each recorded change in turn).
    prev = original
    for entry in record.get("price_history") or []:
        price = _to_float(entry.get("price"))
        if price is None:
            continue
        direction = ""
        if prev is not None:
            if price < prev - PRICE_TOLERANCE:
                direction = "down"
            elif price > prev + PRICE_TOLERANCE:
                direction = "up"
        events.append({"date": entry.get("date") or "", "kind": "price",
                       "price": price, "dir": direction})
        prev = price

    for entry in record.get("status_history") or []:
        status = (entry.get("status") or "").strip().lower()
        if not status:
            continue
        events.append({"date": entry.get("date") or "", "kind": "status",
                       "status": status})

    events.sort(key=lambda e: e.get("date") or "")
    return events
