from datetime import date
from ui.menu import _parse_listing_date


class TestParseListingDate:
    def test_empty_string_defaults_to_today(self):
        assert _parse_listing_date("") == date.today().isoformat()

    def test_whitespace_only_defaults_to_today(self):
        assert _parse_listing_date("   ") == date.today().isoformat()

    def test_valid_past_date_is_preserved(self):
        assert _parse_listing_date("2024-09-15") == "2024-09-15"

    def test_valid_date_with_surrounding_whitespace(self):
        assert _parse_listing_date("  2025-03-01  ") == "2025-03-01"

    def test_invalid_string_falls_back_to_today(self):
        assert _parse_listing_date("not-a-date") == date.today().isoformat()

    def test_wrong_format_falls_back_to_today(self):
        assert _parse_listing_date("15/09/2024") == date.today().isoformat()
