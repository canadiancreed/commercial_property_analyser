"""Tests for the interactive NegotiationReportGenerator.

Renders client-side from embedded JSON: the server picks active, scored deals
and embeds them with their solved targets; filtering and column sorting happen
in the browser.
"""
import json
import re
from unittest.mock import patch

from reporting.negotiation_report import NegotiationReportGenerator


def _row(address="1 Main St, Ottawa, ON", score=65.0, status="active",
         city="Ottawa", ptype="Retail", asking=500_000, targets=None):
    return {
        "address": address, "city": city, "type": ptype, "status": status,
        "asking": asking, "score": score, "cap_rate": 7.2,
        "targets": {"price": 420_000, "rent": 72_000,
                    "rate": 0.0525, "down_pct": 0.30} if targets is None else targets,
    }


def _embedded_data(html):
    m = re.search(r"const DATA = (\[.*?\]);", html, re.DOTALL)
    assert m, "embedded DATA array not found"
    return json.loads(m.group(1))


class TestNegotiationReportGenerator:
    def test_render_html_skeleton(self):
        html = NegotiationReportGenerator().render([_row()])
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html
        assert "Negotiation" in html and "Targets" in html

    def test_embeds_active_scored_deal(self):
        data = _embedded_data(NegotiationReportGenerator().render([_row(address="42 Bid St")]))
        assert any(d["address"] == "42 Bid St" for d in data)

    def test_only_active(self):
        rows = [_row("Active St", status="active"), _row("Sold St", status="inactive")]
        data = _embedded_data(NegotiationReportGenerator().render(rows))
        addrs = [d["address"] for d in data]
        assert "Active St" in addrs
        assert "Sold St" not in addrs

    def test_excludes_unscored(self):
        data = _embedded_data(NegotiationReportGenerator().render([_row("NoScore St", score=None)]))
        assert "NoScore St" not in [d["address"] for d in data]

    def test_targets_carried_into_data(self):
        data = _embedded_data(NegotiationReportGenerator().render([_row()]))
        d = data[0]
        assert d["t_price"] == 420_000
        assert d["t_rent"] == 72_000
        assert abs(d["t_rate"] - 0.0525) < 1e-9
        assert abs(d["t_down"] - 0.30) < 1e-9

    def test_negotiation_room_computed(self):
        # target 420k vs asking 500k -> 16% room below asking.
        data = _embedded_data(NegotiationReportGenerator().render([_row(asking=500_000)]))
        assert abs(data[0]["room"] - 16.0) < 1e-9

    def test_room_none_when_no_price_target(self):
        data = _embedded_data(NegotiationReportGenerator().render(
            [_row(targets={"rent": 60_000})]))
        assert data[0]["room"] is None

    def test_has_three_filters(self):
        html = NegotiationReportGenerator().render([_row()])
        assert 'id="f-score"' in html
        assert 'id="f-cap"' in html
        assert 'id="f-room"' in html

    def test_columns_are_click_sortable(self):
        html = NegotiationReportGenerator().render([_row()])
        assert "function sortBy(" in html
        for col in ("score", "cap_rate", "t_price", "room", "asking"):
            assert f"sortBy('{col}'" in html

    def test_default_sort_is_score_descending(self):
        html = NegotiationReportGenerator().render([_row()])
        assert "let sortCol = 'score';" in html
        assert "let sortDir = -1;" in html

    def test_all_optimal_deal_has_null_targets(self):
        data = _embedded_data(NegotiationReportGenerator().render([_row(targets={})]))
        d = data[0]
        assert d["t_price"] is None and d["room"] is None

    def test_empty_input(self):
        data = _embedded_data(NegotiationReportGenerator().render([]))
        assert data == []

    def test_address_escaped_in_browser(self):
        html = NegotiationReportGenerator().render([_row(address="<b>x</b>")])
        assert "function esc(" in html

    def test_open_in_browser_writes_and_opens(self):
        gen = NegotiationReportGenerator()
        with patch("webbrowser.open") as mock_open:
            gen.open_in_browser([_row()])
            assert mock_open.called
