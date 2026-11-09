"""Tests for the cash-flow proforma (analysis/metrics/proforma.py).

The proforma must decompose the SAME cash-flow array the returns engine uses —
its net_cf column has to equal ReturnMetrics' array term for term, or the table
would tell a different story from the IRR it claims to explain.
"""

from types import SimpleNamespace
import pytest
from analysis.metrics.returns import ReturnMetrics
from analysis.metrics.proforma import annual_schedule, net_cash_flows

_PROP = SimpleNamespace(hold_years=7)
_ARGS = dict(year1_noi=90_000.0, annual_mortgage=48_000.0, cash_invested=300_000.0,
             g=0.02, hold_years=7, exit_price=1_400_000.0, loan_balance=820_000.0)


def test_net_cf_matches_returnmetrics_array():
    sched = annual_schedule(**_ARGS)
    rm = ReturnMetrics(_PROP, _ARGS["year1_noi"], _ARGS["annual_mortgage"],
                       _ARGS["cash_invested"], _ARGS["exit_price"],
                       _ARGS["loan_balance"], noi_growth_rate=_ARGS["g"])
    assert net_cash_flows(sched) == pytest.approx(rm._cash_flows)


def test_schedule_shape_and_reversion_placement():
    sched = annual_schedule(**_ARGS)
    rows = sched["rows"]
    assert rows[0]["year"] == 0 and rows[0]["net_cf"] == -_ARGS["cash_invested"]
    assert len(rows) == _ARGS["hold_years"] + 1
    # Reversion only in the final year.
    assert all(r["reversion"] is None for r in rows[1:-1])
    assert rows[-1]["reversion"] == pytest.approx(
        _ARGS["exit_price"] - _ARGS["loan_balance"])


def test_noi_escalates_and_debt_is_flat():
    sched = annual_schedule(**_ARGS)
    yrs = sched["rows"][1:]
    assert yrs[0]["noi"] == pytest.approx(_ARGS["year1_noi"])
    assert yrs[1]["noi"] == pytest.approx(_ARGS["year1_noi"] * (1 + _ARGS["g"]))
    assert all(r["debt_service"] == _ARGS["annual_mortgage"] for r in yrs)


def test_cumulative_is_running_sum():
    sched = annual_schedule(**_ARGS)
    running = 0.0
    for r in sched["rows"]:
        running += r["net_cf"]
        assert r["cumulative"] == pytest.approx(running)
