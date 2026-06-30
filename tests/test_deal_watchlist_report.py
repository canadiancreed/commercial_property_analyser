"""Tests for DealWatchlistReportGenerator HTML rendering."""
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


class TestDealWatchlistReportGenerator:
    def test_render_returns_html_skeleton(self):
        html = DealWatchlistReportGenerator().render([_row()])
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html
        assert "Deal" in html and "Watchlist" in html

    def test_includes_qualifying_deal(self):
        html = DealWatchlistReportGenerator().render([_row(score=80.0)])
        assert "1 Main St, Ottawa, ON" in html

    def test_excludes_below_threshold(self):
        rows = [_row("Low St", score=40.0), _row("High St", score=70.0)]
        html = DealWatchlistReportGenerator().render(rows, min_score=55)
        assert "High St" in html
        assert "Low St" not in html

    def test_excludes_unscored(self):
        row = _row("No Score St")
        row["score"] = None
        html = DealWatchlistReportGenerator().render([row])
        assert "No Score St" not in html
        assert "No scored properties" in html

    def test_threshold_boundary_is_inclusive(self):
        html = DealWatchlistReportGenerator().render([_row("Edge St", score=55.0)],
                                                     min_score=55)
        assert "Edge St" in html

    def test_sorted_best_score_first(self):
        rows = [_row("Lower St", score=60.0), _row("Top St", score=90.0)]
        html = DealWatchlistReportGenerator().render(rows)
        assert html.index("Top St") < html.index("Lower St")

    def test_custom_min_score_in_header(self):
        html = DealWatchlistReportGenerator().render([_row(score=80.0)], min_score=70)
        assert "70" in html

    def test_empty_input(self):
        html = DealWatchlistReportGenerator().render([])
        assert "No scored properties" in html

    def test_metric_grade_classes_present(self):
        # A strong cap rate (7.2 >= 7.5? no -> fair) and CoCR 9.5 -> fair, etc.
        html = DealWatchlistReportGenerator().render([_row(score=80.0)])
        assert "good" in html or "fair" in html or "poor" in html

    def test_html_escapes_address(self):
        html = DealWatchlistReportGenerator().render(
            [_row(address="<script>x</script> St", score=80.0)])
        assert "<script>x</script> St" not in html
        assert "&lt;script&gt;" in html

    def test_default_min_score_constant(self):
        assert DEFAULT_MIN_SCORE == 55

    def test_open_in_browser_writes_and_opens(self, tmp_path):
        gen = DealWatchlistReportGenerator()
        with patch("webbrowser.open") as mock_open:
            gen.open_in_browser([_row(score=80.0)])
            assert mock_open.called
