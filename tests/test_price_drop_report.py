"""Tests for PriceDropReportGenerator HTML rendering."""
from unittest.mock import patch

from reporting.price_drop_report import PriceDropReportGenerator


def _row(address="1 Main St, Ottawa, ON", original=550_000, asking=500_000,
         score=65.0, status="active", city="Ottawa", ptype="Retail"):
    return {
        "address": address, "city": city, "type": ptype, "status": status,
        "original": original, "asking": asking, "score": score,
        "cap_rate": 7.2, "dom": 95,
    }


class TestPriceDropReportGenerator:
    def test_render_html_skeleton(self):
        html = PriceDropReportGenerator().render([_row()])
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html
        assert "Price" in html and "Drop" in html

    def test_includes_reduced_listing(self):
        html = PriceDropReportGenerator().render([_row(address="Cut Price Plaza")])
        assert "Cut Price Plaza" in html

    def test_excludes_listing_at_or_above_original(self):
        html = PriceDropReportGenerator().render(
            [_row(address="Full Price St", original=500_000, asking=500_000)])
        assert "Full Price St" not in html
        assert "No listings priced below" in html

    def test_excludes_listing_above_original(self):
        html = PriceDropReportGenerator().render(
            [_row(address="Risen St", original=500_000, asking=550_000)])
        assert "Risen St" not in html

    def test_excludes_when_no_original(self):
        html = PriceDropReportGenerator().render(
            [_row(address="No Orig St", original=0, asking=500_000)])
        assert "No Orig St" not in html

    def test_drop_amount_and_percent(self):
        # 550k -> 500k : -$50,000, 9.1%
        html = PriceDropReportGenerator().render([_row(original=550_000, asking=500_000)])
        assert "-$50,000" in html
        assert "9.1%" in html

    def test_sorted_largest_drop_first(self):
        rows = [
            _row("Small Drop St", original=510_000, asking=500_000),   # ~2%
            _row("Big Drop St",   original=800_000, asking=500_000),   # ~37.5%
        ]
        html = PriceDropReportGenerator().render(rows)
        assert html.index("Big Drop St") < html.index("Small Drop St")

    def test_tiny_drop_below_epsilon_excluded(self):
        # 0.05% drop is noise and should not register.
        html = PriceDropReportGenerator().render(
            [_row(address="Noise St", original=500_250, asking=500_000)])
        assert "Noise St" not in html

    def test_inactive_listing_included(self):
        # Price-drop history is relevant regardless of active/inactive status.
        html = PriceDropReportGenerator().render(
            [_row(address="Sold Cut St", status="inactive")])
        assert "Sold Cut St" in html

    def test_empty_input(self):
        html = PriceDropReportGenerator().render([])
        assert "No listings priced below" in html

    def test_html_escapes_address(self):
        html = PriceDropReportGenerator().render([_row(address="<x> St")])
        assert "<x> St" not in html
        assert "&lt;x&gt;" in html

    def test_open_in_browser_writes_and_opens(self):
        gen = PriceDropReportGenerator()
        with patch("webbrowser.open") as mock_open:
            gen.open_in_browser([_row()])
            assert mock_open.called
