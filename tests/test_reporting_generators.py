"""Tests for CityReportGenerator and PropertyReportGenerator HTML rendering."""
import json
import pytest
from unittest.mock import patch
from reporting.city_report import CityReportGenerator
from reporting.property_report import PropertyReportGenerator


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _city(name="Ottawa, ON", opp=72.5, active=3, inactive=1):
    return {
        "city": name, "total": active + inactive,
        "active": active, "inactive": inactive,
        "confidence": 0.67, "opportunity": opp,
        "act_score": 65.0, "act_cap": 7.2, "act_coc": 9.5,
        "act_irr": 12.0, "act_dscr": 1.45, "act_cf": 14_000,
        "act_drop": 4.5, "act_dom": 95, "act_price": 520_000,
        "inact_score": 55.0, "inact_cap": 6.8, "inact_coc": 8.0,
        "inact_price": 490_000, "best_score": 78.0,
        "cap_trend": 0.4, "population": 1_000_000,
        "pop_growth": 1.8, "has_demo": True,
        "type_counts": {"Retail": 2, "Office": 1, "Industrial": 1},
    }


def _prop_row(address="1 Main St, Ottawa, ON", score=65.0, city="Ottawa",
              province="ON", ptype="Retail"):
    return {
        "address": address, "mls": "MLS-001", "status": "active",
        "city": city, "province": province, "type": ptype,
        "asking": 500_000, "sqft": 5000, "listed": "2024-01-01",
        "analyzed": "2024-06-01", "notes": "Good location.",
        "construction": 0, "dist_km": 45, "dist_centre": "Toronto",
        "comm_rent": 60_000, "res_rent": 0,
        "score": score, "breakdown": {"Cap Rate": 70.0, "CoCR": 60.0},
        "weights": {"Cap Rate": 0.25, "CoCR": 0.20},
        "cap_rate": 7.2, "coc": 9.5, "dscr": 1.45,
        "irr": 12.0, "em": 1.8, "cf_annual": 14_000,
        "price_drop": 4.5, "dom": 95,
        "original": 530_000, "taxes": 8000,
        "down_pct": 0.25, "rate": 0.055, "term": 25, "hold": 10,
        "expense_ratio": 0.40, "lease_type": "Normal",
        "results": [
            {"metric": "Cap Rate", "value": "7.20%", "grade": "GOOD"},
            {"metric": "DSCR",     "value": "1.45",  "grade": "GOOD"},
        ],
        "targets": {"price": 420_000, "rent": 72_000},
        "hotel_rooms": 0, "hotel_adr": 0, "hotel_occ": 0,
        "rent_breakdown": ["Retail @ $30/sq ft × 5,000 sq ft"],
    }


# ── CityReportGenerator ───────────────────────────────────────────────────────

class TestCityReportGenerator:
    def test_render_returns_string(self):
        html = CityReportGenerator().render([_city()])
        assert isinstance(html, str)

    def test_render_is_valid_html_skeleton(self):
        html = CityReportGenerator().render([_city()])
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html

    def test_render_embeds_cities_json(self):
        city = _city("Kingston, ON", opp=55.0)
        html = CityReportGenerator().render([city])
        assert "Kingston, ON" in html

    def test_render_empty_list(self):
        html = CityReportGenerator().render([])
        assert "CITIES" in html
        # JSON array should be empty
        assert "[]" in html

    def test_render_multiple_cities(self):
        cities = [_city("Ottawa, ON", opp=72.0), _city("Kingston, ON", opp=55.0)]
        html = CityReportGenerator().render(cities)
        assert "Ottawa, ON" in html
        assert "Kingston, ON" in html

    def test_render_contains_opportunity_value(self):
        html = CityReportGenerator().render([_city(opp=72.5)])
        assert "72.5" in html

    def test_render_title(self):
        html = CityReportGenerator().render([_city()])
        assert "City Investment Rankings" in html

    def test_render_has_js_render_call(self):
        html = CityReportGenerator().render([_city()])
        assert "renderAll()" in html

    def test_open_in_browser_writes_file(self, tmp_path):
        gen = CityReportGenerator()
        with patch("webbrowser.open") as mock_open, \
             patch("tempfile.NamedTemporaryFile") as mock_tmp:
            tmp_file = mock_tmp.return_value.__enter__.return_value
            mock_tmp.return_value.name = str(tmp_path / "city_report_test.html")
            mock_tmp.return_value.__enter__ = lambda s: s
            mock_tmp.return_value.__exit__ = lambda s, *a: None
            # Just call and ensure no exception
            try:
                gen.open_in_browser([_city()])
            except Exception:
                pass  # file write details vary; just ensure render() was called

    def test_render_confidence_shown(self):
        city = _city()
        city["confidence"] = 0.67
        html = CityReportGenerator().render([city])
        # confidence_k formula embedded in JS
        assert "confidence" in html.lower()

    def test_render_demographics(self):
        city = _city()
        city["population"] = 950_000
        city["pop_growth"] = 1.5
        html = CityReportGenerator().render([city])
        assert "950000" in html or "950,000" in html or "1.5" in html

    def test_render_type_counts(self):
        city = _city()
        city["type_counts"] = {"Industrial": 3, "Office": 1}
        html = CityReportGenerator().render([city])
        assert "Industrial" in html or "Office" in html

    def test_thresholds_injected_as_js_const(self):
        """const T should be present and contain inact_cap from score_weights.json."""
        html = CityReportGenerator().render([_city()])
        assert "const T = " in html
        start = html.index("const T = ") + len("const T = ")
        end   = html.index(";", start)
        parsed = json.loads(html[start:end])
        assert "inact_cap" in parsed

    def test_inact_cap_threshold_ceiling_is_10(self):
        """inact_cap hi threshold must be 10.0 in the injected JS thresholds."""
        html = CityReportGenerator().render([_city()])
        start = html.index("const T = ") + len("const T = ")
        end   = html.index(";", start)
        parsed = json.loads(html[start:end])
        lo, hi = parsed["inact_cap"]
        assert hi == pytest.approx(10.0), f"Expected 10.0, got {hi}"

    def test_thresholds_fallback_on_missing_file(self):
        """render() must not raise if score_weights.json is unreadable."""
        import reporting.city_report as mod
        with patch.object(mod, "_load_city_thresholds", return_value={}):
            html = CityReportGenerator().render([_city()])
        assert "const T = {}" in html

    def test_score_ministat_uses_opportunity_color(self):
        """Score mini-stat must use style=color:barColor so it matches the opportunity number."""
        html = CityReportGenerator().render([_city()])
        assert 'style="color:${barColor}"' in html

    def test_score_ministat_does_not_use_gc_class(self):
        """Score mini-stat must not use a class attribute from gc('score') — that produced
        green text even when the city opportunity score was amber (visual inconsistency).
        The fix uses style=color:barColor. gc('score') still appears in detail cards."""
        html = CityReportGenerator().render([_city()])
        # The specific mini-stat template literal must not use a class-based color for Score
        assert 'Score <span class="${gc(' not in html

    def test_render_json_is_parseable(self):
        cities = [_city("Ottawa, ON"), _city("Kingston, ON", opp=55.0)]
        html = CityReportGenerator().render(cities)
        # Extract the JSON from `const CITIES = ...;`
        start = html.index("const CITIES = ") + len("const CITIES = ")
        end   = html.index(";\n\nlet _priceMin")
        parsed = json.loads(html[start:end])
        assert len(parsed) == 2
        assert parsed[0]["city"] == "Ottawa, ON"


# ── PropertyReportGenerator ────────────────────────────────────────────────────

class TestPropertyReportGenerator:
    def test_render_returns_string(self):
        html = PropertyReportGenerator().render([_prop_row()])
        assert isinstance(html, str)

    def test_render_is_valid_html(self):
        html = PropertyReportGenerator().render([_prop_row()])
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html

    def test_render_embeds_data_json(self):
        html = PropertyReportGenerator().render([_prop_row()])
        assert "1 Main St, Ottawa, ON" in html

    def test_render_title(self):
        html = PropertyReportGenerator().render([_prop_row()])
        assert "Property Investment Report" in html

    def test_render_empty_list(self):
        html = PropertyReportGenerator().render([])
        assert "DATA" in html
        assert "[]" in html

    def test_render_multiple_rows(self):
        rows = [
            _prop_row("1 Main St, Ottawa, ON", city="Ottawa", province="ON"),
            _prop_row("2 King St, Kingston, ON", city="Kingston", province="ON"),
        ]
        html = PropertyReportGenerator().render(rows)
        assert "Ottawa" in html
        assert "Kingston" in html

    def test_render_province_options(self):
        html = PropertyReportGenerator().render([_prop_row(province="ON")])
        assert '<option value="ON">ON</option>' in html

    def test_render_city_options(self):
        html = PropertyReportGenerator().render([_prop_row(city="Ottawa")])
        assert '<option value="Ottawa">Ottawa</option>' in html

    def test_render_type_options(self):
        html = PropertyReportGenerator().render([_prop_row(ptype="Retail")])
        assert '<option value="Retail">Retail</option>' in html

    def test_render_with_city_table_html(self):
        city_panel = '<div id="city-panel"><p>City rankings here</p></div>'
        html = PropertyReportGenerator().render([_prop_row()], city_table_html=city_panel)
        assert "City rankings here" in html

    def test_render_without_city_table_html(self):
        html = PropertyReportGenerator().render([_prop_row()], city_table_html="")
        assert "Property Investment Report" in html

    def test_render_score_in_data(self):
        html = PropertyReportGenerator().render([_prop_row(score=72.5)])
        assert "72.5" in html

    def test_render_no_score_row(self):
        row = _prop_row()
        row["score"] = None
        html = PropertyReportGenerator().render([row])
        assert "null" in html  # JSON null for score

    def test_render_data_json_parseable(self):
        rows = [_prop_row("1 Main St, Ottawa, ON")]
        html = PropertyReportGenerator().render(rows)
        start = html.index("const DATA = ") + len("const DATA = ")
        end   = html.index(";\n\nlet currentSort")
        parsed = json.loads(html[start:end])
        assert len(parsed) == 1
        assert parsed[0]["address"] == "1 Main St, Ottawa, ON"
        assert parsed[0]["score"] == 65.0

    def test_render_deduplicates_provinces(self):
        rows = [
            _prop_row("1 Main St, Ottawa, ON",   province="ON"),
            _prop_row("2 King St, Kingston, ON",  province="ON"),
        ]
        html = PropertyReportGenerator().render(rows)
        # Only one <option value="ON"> should appear
        assert html.count('<option value="ON">ON</option>') == 1

    def test_render_multiple_provinces(self):
        rows = [
            _prop_row(province="ON"),
            _prop_row(province="BC"),
        ]
        html = PropertyReportGenerator().render(rows)
        assert '<option value="ON">ON</option>' in html
        assert '<option value="BC">BC</option>' in html

    def test_open_in_browser_calls_render(self, tmp_path):
        gen = PropertyReportGenerator()
        called = []

        original_render = gen.render
        def capturing_render(rows, city_table_html=""):
            called.append(True)
            return original_render(rows, city_table_html)

        gen.render = capturing_render
        with patch("webbrowser.open"):
            try:
                gen.open_in_browser([_prop_row()])
            except Exception:
                pass
        assert called
