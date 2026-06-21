"""Tests for realtor.ca search-query building and price parsing (no network)."""
from scraping.realtor_scraper import build_query, _parse_price


def test_query_appends_province_when_missing():
    q = build_query("24-26 Main St S, Alexandria", "Alexandria", "ON")
    assert q == "24-26 Main St S, Alexandria, ON"


def test_query_appends_city_and_province_when_both_missing():
    q = build_query("123 Queen St", "Ottawa", "ON")
    assert q == "123 Queen St, Ottawa, ON"


def test_query_strips_trailing_province_from_address_then_readds():
    q = build_query("123 Queen St, Ottawa, ON", "Ottawa", "ON")
    assert q == "123 Queen St, Ottawa, ON"
    assert q.upper().count("ON") == 1


def test_query_no_duplicate_city():
    q = build_query("5 King St, Toronto", "toronto", "ON")
    assert q.lower().count("toronto") == 1


def test_query_handles_empty_city_province():
    assert build_query("99 Bank St", "", "") == "99 Bank St"


def test_parse_price_basic():
    assert _parse_price("$1,250,000") == 1_250_000.0


def test_parse_price_with_spacing_and_text():
    assert _parse_price("Asking: $ 499,900 CAD") == 499_900.0


def test_parse_price_none_when_absent():
    assert _parse_price("Contact for price") is None
    assert _parse_price("") is None
    assert _parse_price(None) is None
