"""Tests for the pure realtor.ca price comparison logic."""
import pytest

from scraping.price_comparator import (
    compare, SAME_TOLERANCE,
    STATUS_SAME, STATUS_DROPPED, STATUS_RISEN, STATUS_NOT_FOUND, STATUS_ERROR,
)
from scraping.realtor_scraper import (
    FetchResult, OUTCOME_FOUND, OUTCOME_NOT_FOUND, OUTCOME_BLOCKED,
)


def _found(price, url="https://realtor.ca/x"):
    return FetchResult(price=price, outcome=OUTCOME_FOUND, listing_url=url)


def test_dropped():
    row = compare(500_000, _found(450_000))
    assert row["status"] == STATUS_DROPPED
    assert row["delta"] == -50_000
    assert row["delta_pct"] == pytest.approx(-10.0)
    assert row["listing_url"] == "https://realtor.ca/x"


def test_risen():
    row = compare(500_000, _found(550_000))
    assert row["status"] == STATUS_RISEN
    assert row["delta"] == 50_000
    assert row["delta_pct"] == pytest.approx(10.0)


def test_same_exact():
    row = compare(500_000, _found(500_000))
    assert row["status"] == STATUS_SAME
    assert row["delta"] == 0


def test_same_within_tolerance():
    row = compare(500_000, _found(500_000 + SAME_TOLERANCE))
    assert row["status"] == STATUS_SAME


def test_change_just_past_tolerance():
    row = compare(500_000, _found(500_000 + SAME_TOLERANCE + 0.01))
    assert row["status"] == STATUS_RISEN


def test_not_found_outcome():
    row = compare(500_000, FetchResult(outcome=OUTCOME_NOT_FOUND))
    assert row["status"] == STATUS_NOT_FOUND
    assert row["fetched"] is None
    assert row["delta"] is None


def test_blocked_outcome_is_error():
    row = compare(500_000, FetchResult(outcome=OUTCOME_BLOCKED))
    assert row["status"] == STATUS_ERROR


def test_found_with_no_price_is_error():
    row = compare(500_000, FetchResult(price=None, outcome=OUTCOME_FOUND))
    assert row["status"] == STATUS_ERROR


def test_missing_stored_price_is_error_but_keeps_found_price():
    row = compare(None, _found(450_000))
    assert row["status"] == STATUS_ERROR
    assert row["fetched"] == 450_000
    assert row["delta"] is None
