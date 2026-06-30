"""Tests for the interactive DealWatchlistReportGenerator.

The report renders client-side from embedded JSON: the server picks the active,
scored deals and embeds them; filtering (score / cap rate / price drop) and
column sorting happen in the browser. Tests therefore assert on the embedded
data set and on the presence of the interactive machinery.
"""
import json
import re
from unittest.mock import patch

from reporting.deal_watchlist_report import (
    DealWatchlistReportGenerator,
    DEFAULT_MIN_SCORE,
)


def _row(address="1 Main St, Ottawa, ON", score=65.0, city="Ottawa",
         ptype="Retail", status="active"):
    return {
        "address": address, "city": city, "type": ptype, "status": status,
        "asking": 500_000, "score": score,
        "cap_rate": 7.2, "coc": 9.5, "irr": 12.0, "cf_annual": 14_000,
        "dscr": 1.45, "dom": 95, "price_drop": 4.5,
    }


def _embedded_data(html):
    """Pull the `const DATA = [...];` payload out of the rendered page."""
    m = re.search(r"const DATA = (\[.*?\]);", html, re.DOTALL)
    assert m, "embedded DATA array not found"
    return json.loads(m.group(1))


class TestDealWatchlistReportGenerator:
    def test_render_html_skeleton(self):
        html = DealWatchlistReportGenerator().render([_row()])
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html
        assert "Deal" in html and "Watchlist" in html

    def test_embeds_active_scored_deal(self):
        data = _embedded_data(DealWatchlistReportGenerator().render([_row(address="42 Bid St")]))
        assert any(d["address"] == "42 Bid St" for d in data)

    def test_only_active_listings_embedded(self):
        rows = [_row("Active St", status="active"),
                _row("Inactive St", status="inactive")]
        data = _embedded_data(DealWatchlistReportGenerator().render(rows))
        addrs = [d["address"] for d in data]
        assert "Active St" in addrs
        assert "Inactive St" not in addrs

    def test_unscored_excluded(self):
        rows = [_row("Scored St", score=65.0), _row("No Score St", score=None)]
        data = _embedded_data(DealWatchlistReportGenerator().render(rows))
        addrs = [d["address"] for d in data]
        assert "Scored St" in addrs
        assert "No Score St" not in addrs

    def test_low_score_deals_still_embedded(self):
        # Filtering by score is interactive, so a low score is NOT dropped at
        # render time (the user can lower the Min Score filter to see it).
        data = _embedded_data(DealWatchlistReportGenerator().render([_row("Low St", score=20.0)]))
        assert any(d["address"] == "Low St" for d in data)

    def test_default_min_score_seeded_into_filter(self):
        html = DealWatchlistReportGenerator().render([_row()])
        assert f"let fScore = {DEFAULT_MIN_SCORE};" in html

    def test_custom_min_score_seeded(self):
        html = DealWatchlistReportGenerator().render([_row()], min_score=70)
        assert "let fScore = 70;" in html

    def test_has_three_filters(self):
        html = DealWatchlistReportGenerator().render([_row()])
        assert 'id="f-score"' in html
        assert 'id="f-cap"' in html
        assert 'id="f-drop"' in html

    def test_columns_are_click_sortable(self):
        html = DealWatchlistReportGenerator().render([_row()])
        assert "function sortBy(" in html
        for col in ("score", "cap_rate", "price_drop", "asking", "dom"):
            assert f"sortBy('{col}'" in html

    def test_default_sort_is_score_descending(self):
        html = DealWatchlistReportGenerator().render([_row()])
        assert "let sortCol = 'score';" in html
        assert "let sortDir = -1;" in html

    def test_embedded_json_is_parseable(self):
        rows = [_row("1 Main St"), _row("2 King St", city="Kingston")]
        data = _embedded_data(DealWatchlistReportGenerator().render(rows))
        assert len(data) == 2
        assert {d["city"] for d in data} == {"Ottawa", "Kingston"}

    def test_empty_input(self):
        data = _embedded_data(DealWatchlistReportGenerator().render([]))
        assert data == []

    def test_address_escaped_in_browser(self):
        # Escaping happens client-side via esc(); the raw string round-trips in
        # the JSON, but the page must ship an esc() helper to neutralise it.
        html = DealWatchlistReportGenerator().render([_row(address="<script>x</script>")])
        assert "function esc(" in html

    def test_default_min_score_constant(self):
        assert DEFAULT_MIN_SCORE == 55

    def test_open_in_browser_writes_and_opens(self):
        gen = DealWatchlistReportGenerator()
        with patch("webbrowser.open") as mock_open:
            gen.open_in_browser([_row()])
            assert mock_open.called
