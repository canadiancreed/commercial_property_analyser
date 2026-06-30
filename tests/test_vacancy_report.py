"""Tests for VacancyReportGenerator HTML rendering and the vacancy computation."""
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
        # Cap rate must fall monotonically as occupancy drops.
        assert caps == sorted(caps, reverse=True)

    def test_cap_at_full_occupancy(self):
        # NOI = 60000 * 1.0 * (1-0.40) = 36000; cap = 36000/500000 = 7.2%
        grid = vacancy_grid(_row())
        cap_100 = grid[0][1]
        assert abs(cap_100 - 7.2) < 1e-6

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

    def test_includes_income_property(self):
        html = VacancyReportGenerator().render([_row(address="Income Plaza")])
        assert "Income Plaza" in html

    def test_excludes_property_without_rent(self):
        html = VacancyReportGenerator().render(
            [_row(address="No Rent St", comm_rent=0, res_rent=0)])
        assert "No Rent St" not in html
        assert "No properties with rent data" in html

    def test_shows_all_four_occupancy_columns(self):
        html = VacancyReportGenerator().render([_row()])
        for label in ("@100%", "@85%", "@75%", "@60%"):
            assert label in html

    def test_sorted_best_score_first(self):
        rows = [_row("Lower St", score=40.0), _row("Top St", score=90.0)]
        html = VacancyReportGenerator().render(rows)
        assert html.index("Top St") < html.index("Lower St")

    def test_empty_input(self):
        html = VacancyReportGenerator().render([])
        assert "No properties with rent data" in html

    def test_html_escapes_address(self):
        html = VacancyReportGenerator().render([_row(address="<i>x</i> St")])
        assert "<i>x</i> St" not in html
        assert "&lt;i&gt;" in html

    def test_handles_missing_financing_fields(self):
        # A sparse record should still model via defaults rather than raising.
        sparse = {
            "address": "Sparse St", "city": "X", "type": "Retail",
            "status": "active", "asking": 400_000, "score": 50.0,
            "comm_rent": 30_000, "res_rent": 0,
        }
        html = VacancyReportGenerator().render([sparse])
        assert "Sparse St" in html

    def test_open_in_browser_writes_and_opens(self):
        gen = VacancyReportGenerator()
        with patch("webbrowser.open") as mock_open:
            gen.open_in_browser([_row()])
            assert mock_open.called
