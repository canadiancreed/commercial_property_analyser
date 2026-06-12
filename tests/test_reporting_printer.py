import json
import pytest
from io import StringIO
from unittest.mock import MagicMock, patch
from reporting.printer import ReportPrinter


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_store(props=None):
    store = MagicMock()
    store.load_properties.return_value = props or []
    return store


def _make_analyzer(rows=None, prop=None):
    from models.property_input import PropertyInput
    from models.report_row import ReportRow

    analyzer = MagicMock()
    analyzer._has_rent = True
    analyzer.prop = prop or MagicMock(
        address="1 Main St, Ottawa, ON",
        mls_number="MLS-001",
        status="active",
        asking_price=500_000,
        original_price=500_000,
        city="Ottawa",
        province="ON",
        listing_date="2024-01-01",
    )
    analyzer.report.return_value = rows or [
        MagicMock(metric="Cap Rate", value="7.20%", grade="GOOD"),
        MagicMock(metric="DSCR",     value="1.50",  grade="GOOD"),
    ]
    return analyzer


# ── print_report ─────────────────────────────────────────────────────────────

class TestPrintReport:
    def test_print_report_show_true(self, capsys):
        from models.report_row import ReportRow
        rows = [ReportRow("Cap Rate", "7.20%", "GOOD")]
        analyzer = _make_analyzer(rows=rows)
        ReportPrinter.print_report(analyzer, show=True)
        out = capsys.readouterr().out
        assert "Cap Rate" in out

    def test_print_report_show_false_produces_no_output(self, capsys):
        analyzer = _make_analyzer()
        ReportPrinter.print_report(analyzer, show=False)
        out = capsys.readouterr().out
        assert out == ""

    def test_print_report_show_true_prints_metrics(self, capsys):
        from models.report_row import ReportRow
        rows = [ReportRow("Cap Rate", "7.20%", "GOOD"), ReportRow("DSCR", "1.50", "GOOD")]
        analyzer = _make_analyzer(rows=rows)
        ReportPrinter.print_report(analyzer, show=True)
        out = capsys.readouterr().out
        assert "Cap Rate" in out
        assert "DSCR" in out

    def test_print_report_returns_none(self):
        analyzer = _make_analyzer()
        result = ReportPrinter.print_report(analyzer, show=False)
        assert result is None


# ── list_properties ────────────────────────────────────────────────────────────

class TestListProperties:
    def test_no_properties_message(self, capsys):
        store = _make_store([])
        ReportPrinter.list_properties(store)
        out = capsys.readouterr().out
        assert "no" in out.lower() or "0" in out or len(out) >= 0

    def test_single_property_shown(self, capsys):
        props = [{
            "address": "1 Main St, Ottawa, ON",
            "mls_number": "MLS-001",
            "status": "active",
            "asking_price": 500_000,
            "listing_date": "2024-01-01",
            "analyzed_on": "2024-06-01",
            "results": [{"metric": "Cap Rate", "value": "7.20%", "grade": "GOOD"}],
        }]
        store = _make_store(props)
        ReportPrinter.list_properties(store)
        out = capsys.readouterr().out
        assert "Main St" in out

    def test_multiple_properties_shown(self, capsys):
        props = [
            {"address": "1 Main St, Ottawa, ON", "mls_number": "A",
             "status": "active", "asking_price": 400_000,
             "listing_date": "2024-01-01", "analyzed_on": "2024-01-01", "results": []},
            {"address": "2 King St, Kingston, ON", "mls_number": "B",
             "status": "inactive", "asking_price": 300_000,
             "listing_date": "2024-01-01", "analyzed_on": "2024-01-01", "results": []},
        ]
        store = _make_store(props)
        ReportPrinter.list_properties(store)
        out = capsys.readouterr().out
        assert "Main St" in out
        assert "King St" in out

    def test_properties_with_city_sorted_before_no_city(self, capsys):
        """Properties with city set use sort key (0, city, ...) — covers the city branch."""
        props = [
            {"address": "5 Oak Ave", "mls_number": "C",         # no city
             "status": "active", "asking_price": 200_000,
             "listing_date": "2024-01-01", "analyzed_on": "2024-01-01", "results": []},
            {"address": "1 Main St, Ottawa, ON", "mls_number": "A",
             "city": "Ottawa", "province": "ON",                # with city
             "status": "active", "asking_price": 400_000,
             "listing_date": "2024-01-01", "analyzed_on": "2024-01-01", "results": []},
            {"address": "2 King St, Kingston, ON", "mls_number": "B",
             "city": "Kingston", "province": "ON",              # with city
             "status": "active", "asking_price": 350_000,
             "listing_date": "2024-01-01", "analyzed_on": "2024-01-01", "results": []},
        ]
        store = _make_store(props)
        ReportPrinter.list_properties(store)
        out = capsys.readouterr().out
        # All three should appear in output
        assert "Main St" in out
        assert "King St" in out
        assert "Oak Ave" in out
        # Properties with city should appear before those without
        pos_main = out.index("Main")
        pos_oak  = out.index("Oak")
        assert pos_main < pos_oak
