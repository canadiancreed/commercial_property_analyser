import pytest
from ui.menu import _parse_city_province
from models.constants import CANADIAN_PROVINCES, PROVINCE_CODES


class TestProvinceCodes:
    """PROVINCE_CODES is the ordered source for the Province dropdown (4.12.2)."""

    def test_thirteen_codes_in_alphabetical_order(self):
        assert len(PROVINCE_CODES) == 13                      # 10 provinces + 3 territories
        assert list(PROVINCE_CODES) == sorted(PROVINCE_CODES)
        assert len(set(PROVINCE_CODES)) == 13                 # no duplicates

    def test_matches_canadian_provinces_set(self):
        assert set(PROVINCE_CODES) == set(CANADIAN_PROVINCES)


class TestParseCityProvince:

    # ── happy path: comma-separated province ─────────────────────────────────

    def test_comma_separated_province(self):
        assert _parse_city_province("123 Main St, Ottawa, ON") == ("Ottawa", "ON")

    def test_comma_separated_province_normalises_case(self):
        city, prov = _parse_city_province("123 Main St, Vancouver, bc")
        assert prov == "BC"
        assert city == "Vancouver"

    def test_comma_separated_strips_whitespace(self):
        assert _parse_city_province("  123 Main St ,  Calgary ,  AB  ") == ("Calgary", "AB")

    # ── happy path: province appended to city token ───────────────────────────

    def test_inline_province(self):
        assert _parse_city_province("123 Main St, Ottawa ON") == ("Ottawa", "ON")

    def test_inline_province_multi_word_city(self):
        city, prov = _parse_city_province("100 King St W, Thunder Bay ON")
        assert city == "Thunder Bay"
        assert prov == "ON"

    def test_inline_province_normalises_case(self):
        city, prov = _parse_city_province("1 Rue Principale, Montréal qc")
        assert prov == "QC"

    # ── all 13 Canadian provinces/territories resolve correctly ───────────────

    @pytest.mark.parametrize("prov", sorted(CANADIAN_PROVINCES))
    def test_all_canadian_provinces_comma_separated(self, prov):
        city, p = _parse_city_province(f"1 Street, SomeCity, {prov}")
        assert p == prov
        assert city == "SomeCity"

    @pytest.mark.parametrize("prov", sorted(CANADIAN_PROVINCES))
    def test_all_canadian_provinces_inline(self, prov):
        city, p = _parse_city_province(f"1 Street, SomeCity {prov}")
        assert p == prov
        assert city == "SomeCity"

    # ── failure / edge cases ──────────────────────────────────────────────────

    def test_no_comma_returns_none_none(self):
        assert _parse_city_province("123 Main St Ottawa ON") == (None, None)

    def test_empty_string_returns_none_none(self):
        assert _parse_city_province("") == (None, None)

    def test_none_input_returns_none_none(self):
        assert _parse_city_province(None) == (None, None)

    def test_unknown_province_returns_none_none(self):
        # "TX" is a US state, not a Canadian province
        assert _parse_city_province("123 Main St, Austin, TX") == (None, None)

    def test_address_with_no_province_returns_none_none(self):
        assert _parse_city_province("123 Main St, Ottawa") == (None, None)

    def test_comma_only_returns_none_none(self):
        assert _parse_city_province(",") == (None, None)
