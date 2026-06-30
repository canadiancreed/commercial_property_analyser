"""Tests for NegotiationReportGenerator HTML rendering."""
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


class TestNegotiationReportGenerator:
    def test_render_html_skeleton(self):
        html = NegotiationReportGenerator().render([_row()])
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html
        assert "Negotiation" in html and "Targets" in html

    def test_includes_active_scored_deal(self):
        html = NegotiationReportGenerator().render([_row(address="42 Bid St")])
        assert "42 Bid St" in html

    def test_excludes_inactive(self):
        html = NegotiationReportGenerator().render([_row("Sold St", status="inactive")])
        assert "Sold St" not in html
        assert "No active, scored properties" in html

    def test_excludes_unscored(self):
        html = NegotiationReportGenerator().render([_row("NoScore St", score=None)])
        assert "NoScore St" not in html

    def test_renders_target_price_and_rent(self):
        html = NegotiationReportGenerator().render([_row()])
        assert "$420,000" in html
        assert "$72,000/yr" in html

    def test_renders_rate_and_down_as_percent(self):
        html = NegotiationReportGenerator().render([_row()])
        assert "5.25%" in html   # rate 0.0525
        assert "30.0%" in html   # down_pct 0.30

    def test_price_delta_shown_negative_when_below_asking(self):
        # target 420k vs asking 500k -> -16.0%
        html = NegotiationReportGenerator().render([_row(asking=500_000)])
        assert "-16.0%" in html

    def test_all_optimal_when_no_targets(self):
        html = NegotiationReportGenerator().render([_row(targets={})])
        assert "All negotiable levers already optimal" in html

    def test_sorted_best_score_first(self):
        rows = [_row("Lower St", score=60.0), _row("Top St", score=90.0)]
        html = NegotiationReportGenerator().render(rows)
        assert html.index("Top St") < html.index("Lower St")

    def test_partial_targets_render_dash_for_missing(self):
        html = NegotiationReportGenerator().render([_row(targets={"price": 400_000})])
        assert "$400,000" in html

    def test_empty_input(self):
        html = NegotiationReportGenerator().render([])
        assert "No active, scored properties" in html

    def test_html_escapes_address(self):
        html = NegotiationReportGenerator().render(
            [_row(address="<b>x</b> St")])
        assert "<b>x</b> St" not in html
        assert "&lt;b&gt;" in html

    def test_open_in_browser_writes_and_opens(self):
        gen = NegotiationReportGenerator()
        with patch("webbrowser.open") as mock_open:
            gen.open_in_browser([_row()])
            assert mock_open.called
