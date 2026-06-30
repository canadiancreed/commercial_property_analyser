"""Tests for the interactive PriceDropReportGenerator.

Reduced listings are picked server-side (asking below original list) and
embedded as JSON; filtering by drop % / status and column sorting happen in the
browser.
"""
import json
import re
from unittest.mock import patch

from reporting.price_drop_report import PriceDropReportGenerator


def _row(address="1 Main St, Ottawa, ON", original=550_000, asking=500_000,
         score=65.0, status="active", city="Ottawa", ptype="Retail"):
    return {
        "address": address, "city": city, "type": ptype, "status": status,
        "original": original, "asking": asking, "score": score,
        "cap_rate": 7.2, "dom": 95,
    }


def _embedded_data(html):
    m = re.search(r"const DATA = (\[.*?\]);", html, re.DOTALL)
    assert m, "embedded DATA array not found"
    return json.loads(m.group(1))


class TestPriceDropReportGenerator:
    def test_render_html_skeleton(self):
        html = PriceDropReportGenerator().render([_row()])
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html
        assert "Price" in html and "Drop" in html

    def test_embeds_reduced_listing(self):
        data = _embedded_data(PriceDropReportGenerator().render([_row(address="Cut Price Plaza")]))
        assert any(d["address"] == "Cut Price Plaza" for d in data)

    def test_excludes_listing_at_or_above_original(self):
        data = _embedded_data(PriceDropReportGenerator().render(
            [_row(address="Full Price St", original=500_000, asking=500_000)]))
        assert "Full Price St" not in [d["address"] for d in data]

    def test_excludes_listing_above_original(self):
        data = _embedded_data(PriceDropReportGenerator().render(
            [_row(address="Risen St", original=500_000, asking=550_000)]))
        assert "Risen St" not in [d["address"] for d in data]

    def test_excludes_when_no_original(self):
        data = _embedded_data(PriceDropReportGenerator().render(
            [_row(address="No Orig St", original=0, asking=500_000)]))
        assert "No Orig St" not in [d["address"] for d in data]

    def test_drop_amount_and_percent_computed(self):
        # 550k -> 500k : $50,000, 9.1%
        data = _embedded_data(PriceDropReportGenerator().render(
            [_row(original=550_000, asking=500_000)]))
        d = data[0]
        assert d["drop_amt"] == 50_000
        assert abs(d["drop_pct"] - 9.1) < 0.05

    def test_tiny_drop_below_epsilon_excluded(self):
        data = _embedded_data(PriceDropReportGenerator().render(
            [_row(address="Noise St", original=500_250, asking=500_000)]))
        assert "Noise St" not in [d["address"] for d in data]

    def test_inactive_listing_included(self):
        data = _embedded_data(PriceDropReportGenerator().render(
            [_row(address="Sold Cut St", status="inactive")]))
        assert any(d["address"] == "Sold Cut St" for d in data)

    def test_has_drop_and_status_filters(self):
        html = PriceDropReportGenerator().render([_row()])
        assert 'id="f-drop"' in html
        assert 'id="f-status"' in html

    def test_columns_are_click_sortable(self):
        html = PriceDropReportGenerator().render([_row()])
        assert "function sortBy(" in html
        for col in ("drop_pct", "drop_amt", "original", "asking", "score"):
            assert f"sortBy('{col}'" in html

    def test_default_sort_is_drop_pct_descending(self):
        html = PriceDropReportGenerator().render([_row()])
        assert "let sortCol = 'drop_pct';" in html
        assert "let sortDir = -1;" in html

    def test_empty_input(self):
        data = _embedded_data(PriceDropReportGenerator().render([]))
        assert data == []

    def test_address_escaped_in_browser(self):
        html = PriceDropReportGenerator().render([_row(address="<x>")])
        assert "function esc(" in html

    def test_open_in_browser_writes_and_opens(self):
        gen = PriceDropReportGenerator()
        with patch("webbrowser.open") as mock_open:
            gen.open_in_browser([_row()])
            assert mock_open.called
