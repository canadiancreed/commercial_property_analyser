"""Tests for realtor.ca query building, address matching, and price parsing.

All pure helpers — no network.
"""
from scraping.realtor_scraper import (
    build_query, _parse_price, address_matches, _slug_address, listing_candidates,
)

HREF = "/real-estate/29920973/129-principale-street-the-nation-605-the-nation-municipality"


def test_slug_address_parses_number_and_name():
    name, num = _slug_address(HREF)
    assert num == 129
    assert "principale" in name.split()


def test_match_on_number_and_street_word():
    assert address_matches("129 Principale Street, The Nation", HREF)


def test_match_normalizes_street_abbreviation():
    assert address_matches("129 Principale St", HREF)


def test_no_match_on_wrong_number():
    assert not address_matches("131 Principale Street", HREF)


def test_no_match_on_wrong_street():
    assert not address_matches("129 Main Street", HREF)


def test_no_match_on_empty_address():
    assert not address_matches("", HREF)


# ── listing_candidates ────────────────────────────────────────────────────────

def test_candidates_put_address_match_first():
    links = [
        "https://www.realtor.ca/on/belleville/commercial-real-estate",  # not a listing
        "https://www.realtor.ca/real-estate/999/9-other-rd-belleville",  # listing, no match
        "https://www.realtor.ca/real-estate/111/249-253-front-street-belleville",  # match
    ]
    got = listing_candidates(links, "249-253 Front Street, Belleville")
    assert got[0] == "https://www.realtor.ca/real-estate/111/249-253-front-street-belleville"
    # both /real-estate/ links are kept, the city page is dropped
    assert len(got) == 2


def test_candidates_empty_when_no_listing_links():
    assert listing_candidates(
        ["https://www.realtor.ca/on/belleville/commercial-real-estate"], "1 Main St") == []


def test_candidates_dedupe_preserves_order():
    dup = "https://www.realtor.ca/real-estate/111/249-253-front-street-belleville"
    assert listing_candidates([dup, dup], "249-253 Front Street") == [dup]


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
