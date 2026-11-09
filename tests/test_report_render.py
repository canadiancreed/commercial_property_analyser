"""Render-smoke tests for the report generators added in 5.2.0–5.5.0.

The engine helpers (sensitivity, proforma) and the pipeline summariser are covered
by their own tests; these exercise the HTML render() and open_in_browser() paths so
the report generators aren't dark in coverage. Each check builds a realistic row,
renders it, and asserts the page carries its title and the deal's data — plus the
empty-input branch, and open_in_browser with webbrowser stubbed so no browser opens.
"""

from types import SimpleNamespace
import pytest

from analysis.metrics.sensitivity import irr_rent_exit_grid
from analysis.metrics.proforma import annual_schedule
from reporting.sensitivity_report import SensitivityReportGenerator
from reporting.proforma_report import ProformaReportGenerator
from reporting.pipeline_report import PipelineReportGenerator
from reporting.comparison_report import ComparisonReportGenerator


def _sens_row():
    grid = irr_rent_exit_grid(SimpleNamespace(hold_years=5),
                              year1_noi=100_000, annual_mortgage=40_000,
                              cash_invested=250_000, exit_price=1_400_000,
                              loan_balance=600_000, g=0.02, hold_years=5,
                              price=1_250_000)
    return {"address": "1 Test St", "city": "Testville", "type": "Office",
            "asking": 1_250_000, "score": 72, "base_irr": 12.3, "base_em": 1.8,
            "grid": grid}


def _pf_row():
    sched = annual_schedule(90_000, 48_000, 300_000, 0.02, 7, 1_400_000, 820_000)
    return {"address": "2 Test Ave", "city": "Testville", "type": "Retail",
            "asking": 1_000_000, "score": 65, "irr": 11.0, "em": 1.7,
            "equity": 300_000, "exit_price": 1_400_000, "net_sale": 580_000,
            "growth": 0.02, "hold": 7, "schedule": sched}


def _pipe_rows():
    base = dict(status="active", asking=1_000_000, type="Office", province="ON",
                city="Ottawa", cap_rate=7.0, irr=12.0, cf_annual=5_000)
    return [dict(base, score=90), dict(base, score=60, type="Retail"),
            dict(base, score=30, city="Kingston")]


def _cmp_rows():
    base = dict(status="active", score=70, asking=1_000_000, sqft=10_000,
                type="Office", city="Ottawa", cap_rate=7.0, coc=8.0, irr=12.0,
                em=1.8, dscr=1.3, cf_annual=20_000, dom=60, price_drop=0,
                verified_income_pct=0.0)
    return [dict(base, address="A St"), dict(base, address="B St", score=80)]


# ── Deal Sensitivity ──────────────────────────────────────────────────────────
def test_sensitivity_render_embeds_deal():
    html = SensitivityReportGenerator().render([_sens_row()])
    assert "<title>Deal Sensitivity</title>" in html
    assert "1 Test St" in html and "const DATA" in html


def test_sensitivity_render_empty():
    html = SensitivityReportGenerator().render([{"address": "no grid"}])
    assert "<title>Deal Sensitivity</title>" in html
    assert "0 scored deals" in html


def test_sensitivity_open_in_browser(monkeypatch):
    seen = {}
    monkeypatch.setattr("reporting.sensitivity_report.webbrowser.open",
                        lambda u: seen.setdefault("u", u))
    SensitivityReportGenerator().open_in_browser([_sens_row()])
    assert seen["u"].startswith("file://")


# ── Cash-Flow Proforma ────────────────────────────────────────────────────────
def test_proforma_render_embeds_deal():
    html = ProformaReportGenerator().render([_pf_row()])
    assert "<title>Cash-Flow Proforma</title>" in html
    assert "2 Test Ave" in html and "const DATA" in html


def test_proforma_render_empty():
    html = ProformaReportGenerator().render([{"address": "no schedule"}])
    assert "<title>Cash-Flow Proforma</title>" in html


def test_proforma_open_in_browser(monkeypatch):
    seen = {}
    monkeypatch.setattr("reporting.proforma_report.webbrowser.open",
                        lambda u: seen.setdefault("u", u))
    ProformaReportGenerator().open_in_browser([_pf_row()])
    assert seen["u"].startswith("file://")


# ── Pipeline Summary ──────────────────────────────────────────────────────────
def test_pipeline_render_has_kpis_and_concentration():
    html = PipelineReportGenerator().render(_pipe_rows())
    assert "<title>Pipeline Summary</title>" in html
    assert "Pipeline value" in html
    assert "Concentration by asset type" in html
    assert "Ottawa" in html


def test_pipeline_render_empty():
    html = PipelineReportGenerator().render([])
    assert "<title>Pipeline Summary</title>" in html


def test_pipeline_open_in_browser(monkeypatch):
    seen = {}
    monkeypatch.setattr("reporting.pipeline_report.webbrowser.open",
                        lambda u: seen.setdefault("u", u))
    PipelineReportGenerator().open_in_browser(_pipe_rows())
    assert seen["u"].startswith("file://")


# ── Shortlist Comparison ──────────────────────────────────────────────────────
def test_comparison_open_in_browser(monkeypatch):
    seen = {}
    monkeypatch.setattr("reporting.comparison_report.webbrowser.open",
                        lambda u: seen.setdefault("u", u))
    ComparisonReportGenerator().open_in_browser(_cmp_rows())
    assert seen["u"].startswith("file://")
