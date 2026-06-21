"""Tests for realtor.ca URL building, address matching, and price parsing.

All pure helpers — no network.
"""
from scraping.realtor_scraper import (
    city_url, address_matches, _slug_address, _parse_price,
)


# ── city_url ────────────────────────────────────────────────────────────────

def test_city_url_basic():
    assert city_url("ON", "The Nation") == \
        "https://www.realtor.ca/on/the-nation/commercial-real-estate"


def test_city_url_lowercases_and_hyphenates():
    assert city_url("on", "Greater Hamilton") == \
        "https://www.realtor.ca/on/greater-hamilton/commercial-real-estate"


def test_city_url_strips_punctuation():
    # St. Catharines -> st-catharines (no trailing/leading hyphens, no dots).
    assert city_url("ON", "St. Catharines") == \
        "https://www.realtor.ca/on/st-catharines/commercial-real-estate"


# ── _slug_address ─────────────────────────────────────────────────────────────

def test_slug_address_parses_number_and_name():
    name, num = _slug_address(
        "/real-estate/29920973/129-principale-street-the-nation-605-the-nation-municipality")
    assert num == 129
    assert "principale" in name.split()


def test_slug_address_empty_for_bad_href():
    assert _slug_address("/realtors/somebody") == ("", 0)


# ── address_matches ───────────────────────────────────────────────────────────

HREF = "/real-estate/29920973/129-principale-street-the-nation-605-the-nation-municipality"


def test_match_on_number_and_street_word():
    assert address_matches("129 Principale Street, The Nation", HREF)


def test_match_normalizes_street_abbreviation():
    # 'St' normalizes to 'street'; the first street word 'principale' still matches.
    assert address_matches("129 Principale St", HREF)


def test_no_match_on_wrong_number():
    assert not address_matches("131 Principale Street", HREF)


def test_no_match_on_wrong_street():
    assert not address_matches("129 Main Street", HREF)


def test_no_match_on_empty_address():
    assert not address_matches("", HREF)


# ── _parse_price ──────────────────────────────────────────────────────────────

def test_parse_price_basic():
    assert _parse_price("$1,269,999") == 1_269_999.0


def test_parse_price_with_text():
    assert _parse_price("Asking $ 324,900 CAD") == 324_900.0


def test_parse_price_none_when_absent():
    assert _parse_price("Contact for price") is None
    assert _parse_price("") is None
    assert _parse_price(None) is None
