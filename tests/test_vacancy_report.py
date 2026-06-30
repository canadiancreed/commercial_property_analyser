"""Tests for VacancyReportGenerator and the vacancy computation.

The occupancy grid is computed server-side (vacancy_grid) and embedded as JSON;
filtering and column sorting happen in the browser.
"""
import json
import re
from unittest.mock import patch

from reporting.vacancy_report import (
    VacancyReportGenerator,
    vacancy_grid,
    OCCUPANCY_LEVELS,
)


def _row(address="1 Main St, Ottawa, ON", score=65.0, comm_rent=60_000,
         res_rent=0, asking=500_000, city="Ottawa", ptype="Retail"):
    return {
        "address": address, "city": city, "type": ptype, "status": "active",
        "asking": asking, "score": score,
        "comm_rent": comm_rent, "res_rent": res_rent,
        "expense_ratio": 0.40, "down_pct": 0.25, "rate": 0.055,
        "term": 25, "hold": 5, "construction": 0, "province": "ON",
    }


def _embedded_data(html):
    m = re.search(r"const DATA = (\[.*?\]);", html, re.DOTALL)
    assert m, "embedded DATA array not found"
    return json.loads(m.group(1))


class TestVacancyGrid:
    def test_returns_one_entry_per_occupancy_level(self):
        grid = vacancy_grid(_row())
        assert len(grid) == len(OCCUPANCY_LEVELS)
        assert [occ for occ, _, _ in grid] == OCCUPANCY_LEVELS

    def test_none_when_no_rent(self):
        assert vacancy_grid(_row(comm_rent=0, res_rent=0)) is None

    def test_none_when_no_price(self):
        assert vacancy_grid(_row(asking=0)) is None

    def test_cap_rate_scales_with_occupancy(self):
        grid = vacancy_grid(_row())
        caps = [cap for _, cap, _ in grid]
        assert caps == sorted(caps, reverse=True)

    def test_cap_at_full_occupancy(self):
        # NOI = 60000 * 1.0 * (1-0.40) = 36000; cap = 36000/500000 = 7.2%
        grid = vacancy_grid(_row())
        assert abs(grid[0][1] - 7.2) < 1e-6

    def test_cash_flow_falls_with_occupancy(self):
        grid = vacancy_grid(_row())
        cfs = [cf for _, _, cf in grid]
        assert cfs == sorted(cfs, reverse=True)

    def test_combines_commercial_and_residential_rent(self):
        grid_split = vacancy_grid(_row(comm_rent=30_000, res_rent=30_000))
        grid_all   = vacancy_grid(_row(comm_rent=60_000, res_rent=0))
        assert abs(grid_split[0][1] - grid_all[0][1]) < 1e-6


class TestVacancyReportGenerator:
    def test_render_html_skeleton(self):
        html = VacancyReportGenerator().render([_row()])
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html
        assert "Vacancy" in html and "Sensitivity" in html

    def test_embeds_income_property_with_grid(self):
        data = _embedded_data(VacancyReportGenerator().render([_row(address="Income Plaza")]))
        d = next(x for x in data if x["address"] == "Income Plaza")
        for key in ("cap100", "cf100", "cap85", "cf85", "cap75", "cf75", "cap60", "cf60"):
            assert key in d

    def test_excludes_property_without_rent(self):
        data = _embedded_data(VacancyReportGenerator().render(
            [_row(address="No Rent St", comm_rent=0, res_rent=0)]))
        assert "No Rent St" not in [d["address"] for d in data]

    def test_embedded_cap100_matches_grid(self):
        data = _embedded_data(VacancyReportGenerator().render([_row()]))
        assert abs(data[0]["cap100"] - 7.2) < 0.01

    def test_has_score_and_occupancy_filters(self):
        html = VacancyReportGenerator().render([_row()])
        assert 'id="f-score"' in html
        assert 'id="f-occ"' in html
        # The occupancy-survival filter keys off the matching cf column.
        assert "r['cf' + fOcc] >= 0" in html

    def test_columns_are_click_sortable(self):
        html = VacancyReportGenerator().render([_row()])
        assert "function sortBy(" in html
        for col in ("score", "cap100", "cf60", "cf75", "asking"):
            assert f"sortBy('{col}'" in html

    def test_default_sort_is_score_descending(self):
        html = VacancyReportGenerator().render([_row()])
        assert "let sortCol = 'score';" in html
        assert "let sortDir = -1;" in html

    def test_empty_input(self):
        data = _embedded_data(VacancyReportGenerator().render([]))
        assert data == []

    def test_handles_missing_financing_fields(self):
        sparse = {
            "address": "Sparse St", "city": "X", "type": "Retail",
            "status": "active", "asking": 400_000, "score": 50.0,
            "comm_rent": 30_000, "res_rent": 0,
        }
        data = _embedded_data(VacancyReportGenerator().render([sparse]))
        assert any(d["address"] == "Sparse St" for d in data)

    def test_address_escaped_in_browser(self):
        html = VacancyReportGenerator().render([_row(address="<i>x</i>")])
        assert "function esc(" in html

    def test_open_in_browser_writes_and_opens(self):
        gen = VacancyReportGenerator()
        with patch("webbrowser.open") as mock_open:
            gen.open_in_browser([_row()])
            assert mock_open.called
