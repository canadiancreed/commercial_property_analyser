import pytest
from core.address import _display_address, _parse_address_sort


class TestDisplayAddress:
    def test_strips_comma_province(self):
        assert _display_address("123 Main St, Ottawa, ON") == "123 Main St, Ottawa"

    def test_strips_space_province(self):
        assert _display_address("123 Main St, Ottawa ON") == "123 Main St, Ottawa"

    def test_strips_trailing_whitespace_with_province(self):
        assert _display_address("456 King St, Toronto, ON  ") == "456 King St, Toronto"

    def test_no_province_unchanged(self):
        assert _display_address("123 Main St") == "123 Main St"

    def test_empty_string(self):
        assert _display_address("") == ""

    def test_none(self):
        assert _display_address(None) == ""

    def test_only_province(self):
        # Bare "ON" has no leading comma/space so regex doesn't strip it
        assert _display_address("ON") == "ON"

    def test_bc_province(self):
        assert _display_address("100 West Hastings, Vancouver, BC") == "100 West Hastings, Vancouver"

    def test_two_letter_city_not_stripped(self):
        # "St" at end of address is not a province code (lowercase)
        result = _display_address("1 Oak St")
        assert "Oak St" in result


class TestParseAddressSort:
    def test_numbered_street(self):
        name, num = _parse_address_sort("123 Main Street, Ottawa, ON")
        assert num == 123
        assert "main" in name

    def test_hyphenated_number(self):
        name, num = _parse_address_sort("123-45 King St")
        assert num == 123

    def test_no_number(self):
        name, num = _parse_address_sort("Main Street")
        assert num == 0
        assert "main" in name

    def test_street_abbreviation_normalized(self):
        _, _ = _parse_address_sort("100 Oak St.")
        name, _ = _parse_address_sort("100 Oak St.")
        assert "street" in name

    def test_avenue_abbreviation(self):
        name, _ = _parse_address_sort("200 Elm Ave")
        assert "avenue" in name

    def test_drive_abbreviation(self):
        name, _ = _parse_address_sort("50 Park Dr")
        assert "drive" in name

    def test_road_abbreviation(self):
        name, _ = _parse_address_sort("77 County Rd")
        assert "road" in name

    def test_boulevard_abbreviation(self):
        name, _ = _parse_address_sort("10 Sunset Blvd")
        assert "boulevard" in name

    def test_empty_string(self):
        name, num = _parse_address_sort("")
        assert num == 0
        assert name == ""

    def test_none(self):
        name, num = _parse_address_sort(None)
        assert num == 0

    def test_city_suffix_ignored(self):
        # Only the first comma-separated part (street) matters
        name1, num1 = _parse_address_sort("1 Main St, Toronto, ON")
        name2, num2 = _parse_address_sort("1 Main St")
        assert name1 == name2
        assert num1 == num2

    def test_case_insensitive(self):
        name1, _ = _parse_address_sort("1 QUEEN STREET")
        name2, _ = _parse_address_sort("1 Queen Street")
        assert name1 == name2

    def test_parkway(self):
        name, _ = _parse_address_sort("5 Commerce Pkwy")
        assert "parkway" in name

    def test_highway(self):
        name, _ = _parse_address_sort("1 Trans-Canada Hwy")
        assert "highway" in name

    def test_lane(self):
        name, _ = _parse_address_sort("3 Cedar Ln")
        assert "lane" in name

    def test_court(self):
        name, _ = _parse_address_sort("8 Oak Ct")
        assert "court" in name

    def test_place(self):
        name, _ = _parse_address_sort("22 Victoria Pl")
        assert "place" in name
