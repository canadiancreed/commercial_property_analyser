"""Two-way IRR / equity-multiple sensitivity for a single deal.

The tool underwrites on an *estimated* market rent and an *assumed* exit cap
rate — the two inputs a buyer is least sure of. A deal that scores well at the
base case but collapses when the exit cap drifts 50 bps or the rent comes in
10 % light is a different deal from one that holds up, and the single headline
IRR hides that.

This module recomputes IRR and equity multiple across a grid of (rent factor x
exit cap) by calling the real ``ReturnMetrics`` engine with perturbed scalars —
it never re-derives a return by hand. Only the two levers under test move:

  * rent factor ``f`` scales year-one NOI (the standard sensitivity convention —
    expenses are held as a ratio, so NOI moves with income). The terminal NOI
    used for the reversion scales with the same ``f``.
  * exit cap ``c`` sets the reversion: exit price = terminal NOI / c.

The loan, the equity invested and the amortized balance at sale are properties
of the *entry* and do not move with rent or exit cap, so they are held fixed —
exactly as the base underwrite computed them.
"""

from typing import Optional
from analysis.metrics.returns import ReturnMetrics

# Default axes. Rent: -15 % to +10 % of the estimated market rent. Exit cap:
# -100 bps to +150 bps around the deal's own base exit cap (tighter cap = higher
# price = better; wider = worse), so the base case sits inside the grid.
DEFAULT_RENT_FACTORS = (0.85, 0.90, 0.95, 1.00, 1.05, 1.10)
DEFAULT_CAP_DELTAS   = (-0.010, -0.005, 0.0, 0.005, 0.010, 0.015)


def _implied_base_exit_cap(year1_noi: float, g: float, hold_years: int,
                           exit_price: float) -> Optional[float]:
    """The cap rate the base underwrite implicitly used: terminal NOI / exit price."""
    if not exit_price or hold_years < 1:
        return None
    terminal_noi = year1_noi * (1 + g) ** (hold_years - 1)
    return terminal_noi / exit_price if terminal_noi else None


def irr_rent_exit_grid(prop, year1_noi: float, annual_mortgage: float,
                       cash_invested: float, exit_price: float,
                       loan_balance: float, g: float, hold_years: int,
                       price: float,
                       rent_factors=DEFAULT_RENT_FACTORS,
                       cap_deltas=DEFAULT_CAP_DELTAS) -> dict:
    """Build the (rent x exit-cap) grid of IRR / EM / entry-cap for one deal.

    Returns a dict with the axis labels and a ``cells`` matrix (rent factor rows,
    exit-cap columns). Each cell is {irr, em, entry_cap, exit_cap} with irr/em None
    where the perturbed cash-flow stream has no meaningful rate (e.g. an underwater
    exit). Reuses ``ReturnMetrics`` so every number matches the main engine.
    """
    base_cap = _implied_base_exit_cap(year1_noi, g, hold_years, exit_price)
    # Absolute exit caps to test. When the base cap is unknown (no exit price),
    # fall back to a plausible spread so the grid still renders something.
    anchor = base_cap if base_cap else 0.075
    exit_caps = [round(anchor + d, 6) for d in cap_deltas]

    cells = []
    for f in rent_factors:
        noi1 = year1_noi * f
        terminal_noi = noi1 * (1 + g) ** (hold_years - 1)
        row = []
        for c in exit_caps:
            exit_p = terminal_noi / c if c and c > 0 else 0.0
            try:
                rm = ReturnMetrics(prop, noi1, annual_mortgage, cash_invested,
                                   exit_p, loan_balance, noi_growth_rate=g)
                irr, em = rm.irr, rm.equity_multiple
            except Exception:
                irr, em = None, None
            row.append({
                "irr": irr,
                "em": em,
                "entry_cap": (noi1 / price * 100.0) if price else None,
                "exit_cap": c * 100.0,
            })
        cells.append(row)

    return {
        "rent_factors": [round(f, 4) for f in rent_factors],
        "exit_caps":    [round(c * 100.0, 4) for c in exit_caps],
        "base_exit_cap": round(base_cap * 100.0, 4) if base_cap else None,
        "cells": cells,
    }
