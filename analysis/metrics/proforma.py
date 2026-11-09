"""Year-by-year cash-flow proforma backing a deal's IRR / equity multiple.

The returns engine (analysis/metrics/returns.py) builds one cash-flow array —
equity out at t0, operating cash flow each year (NOI escalated at the growth
rate, debt service held flat), and the net sale proceeds added in the final
year — then reports only the headline IRR and EM. This module decomposes that
same array back into a readable schedule (NOI, debt service, operating CF,
reversion, net CF, cumulative) so the single IRR number becomes auditable.

The per-year formula here is deliberately identical to ReturnMetrics'; the
`net_cf` column equals that engine's cash-flow array term for term, and a test
asserts the two stay in lock-step so this can never silently drift from the
numbers the rest of the app reports.
"""


def annual_schedule(year1_noi: float, annual_mortgage: float, cash_invested: float,
                    g: float, hold_years: int, exit_price: float,
                    loan_balance: float = 0.0, selling_costs: float = 0.0) -> dict:
    """Decompose the hold into a per-year proforma. Mirrors ReturnMetrics exactly:
    operating CF = NOI*(1+g)^(yr-1) - debt service; the final year also receives
    net sale proceeds = exit price - loan payoff - selling costs."""
    net_sale_proceeds = exit_price - loan_balance - selling_costs
    cumulative = -cash_invested
    rows = [{
        "year": 0, "noi": None, "debt_service": None, "operating_cf": None,
        "reversion": None, "net_cf": -cash_invested, "cumulative": cumulative,
    }]
    for yr in range(1, hold_years + 1):
        noi = year1_noi * (1 + g) ** (yr - 1)
        op  = noi - annual_mortgage
        rev = net_sale_proceeds if yr == hold_years else 0.0
        net = op + rev
        cumulative += net
        rows.append({
            "year": yr, "noi": noi, "debt_service": annual_mortgage,
            "operating_cf": op, "reversion": (rev or None),
            "net_cf": net, "cumulative": cumulative,
        })
    return {
        "rows": rows,
        "net_sale_proceeds": net_sale_proceeds,
        "exit_price": exit_price,
        "loan_balance": loan_balance,
        "cash_invested": cash_invested,
        "noi_growth_rate": g,
    }


def net_cash_flows(schedule: dict) -> list:
    """The net_cf column as a flat array — the same shape ReturnMetrics builds,
    used to assert parity with the returns engine."""
    return [r["net_cf"] for r in schedule["rows"]]
