"""Tests for the rent x exit-cap IRR sensitivity grid (analysis/metrics/sensitivity.py).

The grid must reuse the real ReturnMetrics engine (no hand-rolled IRR) and move
monotonically: lower rent lowers IRR, and a wider exit cap (lower sale price)
lowers IRR.
"""

from types import SimpleNamespace
from analysis.metrics.returns import ReturnMetrics
from analysis.metrics.sensitivity import irr_rent_exit_grid

# A deal with a clear, positive return so every grid cell has a meaningful IRR.
_PROP = SimpleNamespace(hold_years=5)
_BASE = dict(year1_noi=100_000.0, annual_mortgage=40_000.0, cash_invested=250_000.0,
             loan_balance=600_000.0, g=0.02, hold_years=5, price=1_250_000.0)


def _grid():
    return irr_rent_exit_grid(
        _PROP, _BASE["year1_noi"], _BASE["annual_mortgage"], _BASE["cash_invested"],
        # exit price chosen so the base exit cap is a round 7.0 %:
        exit_price=_BASE["year1_noi"] * (1 + _BASE["g"]) ** (_BASE["hold_years"] - 1) / 0.07,
        loan_balance=_BASE["loan_balance"], g=_BASE["g"],
        hold_years=_BASE["hold_years"], price=_BASE["price"])


def test_base_exit_cap_is_recovered():
    g = _grid()
    assert round(g["base_exit_cap"], 2) == 7.00


def test_base_cell_matches_returnmetrics_directly():
    g = _grid()
    # Base case = rent factor 1.0 (index 3) at the deal's own exit cap (7.0 %).
    exit_price = _BASE["year1_noi"] * (1 + _BASE["g"]) ** (_BASE["hold_years"] - 1) / 0.07
    rm = ReturnMetrics(_PROP, _BASE["year1_noi"], _BASE["annual_mortgage"],
                       _BASE["cash_invested"], exit_price, _BASE["loan_balance"],
                       noi_growth_rate=_BASE["g"])
    # Column whose exit cap is 7.0 %:
    ci = g["exit_caps"].index(min(g["exit_caps"], key=lambda c: abs(c - 7.0)))
    cell = g["cells"][3][ci]
    assert cell["irr"] == rm.irr
    assert cell["em"] == rm.equity_multiple


def test_irr_rises_with_rent():
    g = _grid()
    col = 2  # any fixed exit-cap column
    irrs = [g["cells"][r][col]["irr"] for r in range(len(g["rent_factors"]))]
    assert all(a <= b for a, b in zip(irrs, irrs[1:])), irrs  # non-decreasing with rent


def test_irr_falls_as_exit_cap_widens():
    g = _grid()
    row = 3  # rent factor 1.0
    irrs = [g["cells"][row][c]["irr"] for c in range(len(g["exit_caps"]))]
    # exit_caps are ascending (wider to the right) -> IRR should be non-increasing.
    assert all(a >= b for a, b in zip(irrs, irrs[1:])), irrs


def test_entry_cap_scales_with_rent():
    g = _grid()
    col = 0
    low = g["cells"][0][col]["entry_cap"]    # rent 0.85
    high = g["cells"][-1][col]["entry_cap"]  # rent 1.10
    assert low < high
