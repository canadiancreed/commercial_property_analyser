"""HTML report: Vacancy Sensitivity.

Stress-tests each income property by recomputing its cap rate and annual cash
flow at 100%, 85%, 75%, and 60% occupancy. Debt service is held constant (it
doesn't move with occupancy); only NOI — and therefore cash flow and cap rate —
falls as vacancy rises. This surfaces how much vacancy a deal can absorb before
it bleeds.

Uses the project's province-aware MortgageCalculator for debt service, and
renders server-side, sorted best-score first.
"""

import html
import tempfile
import webbrowser
from datetime import datetime

from analysis.mortgage import MortgageCalculator

# Occupancy scenarios, best case first.
OCCUPANCY_LEVELS = [1.00, 0.85, 0.75, 0.60]

# Fallbacks mirror the analyzer's defaults so a sparsely-filled record still
# produces a usable stress test rather than dropping out.
_DEF_EXPENSE_RATIO = 0.40
_DEF_DOWN_PCT      = 0.20
_DEF_RATE          = 0.065
_DEF_TERM          = 25


def _money(v):
    if not v and v != 0:
        return "—"
    return f"${v:,.0f}"


def _money_signed(v):
    if v is None:
        return "—"
    return f"{'-' if v < 0 else ''}${abs(v):,.0f}"


def _cap_grade(v) -> str:
    if v is None:
        return "info"
    return "good" if v >= 7 else "fair" if v >= 5 else "poor"


def _score_grade(v) -> str:
    if v is None:
        return "info"
    return "good" if v >= 55 else "fair" if v >= 35 else "poor"


def vacancy_grid(row: dict):
    """Return [(occ, cap_pct, annual_cf), ...] across OCCUPANCY_LEVELS, or None
    when the property has no rent to model."""
    rent = (row.get("comm_rent") or 0) + (row.get("res_rent") or 0)
    asking = row.get("asking") or 0
    if not rent or not asking:
        return None

    expr = row.get("expense_ratio") or _DEF_EXPENSE_RATIO
    calc = MortgageCalculator(
        asking_price=asking,
        down_payment_pct=row.get("down_pct") or _DEF_DOWN_PCT,
        interest_rate=row.get("rate") or _DEF_RATE,
        term_years=int(row.get("term") or _DEF_TERM),
        hold_years=int(row.get("hold") or 0),
        construction_cost=row.get("construction") or 0,
        province=row.get("province") or "ON",
    )
    annual_debt = calc.annual_mortgage

    grid = []
    for occ in OCCUPANCY_LEVELS:
        noi = rent * occ * (1 - expr)
        cap = noi / asking * 100
        cf  = noi - annual_debt
        grid.append((occ, cap, cf))
    return grid


class VacancyReportGenerator:
    """Renders the vacancy-sensitivity report as a standalone HTML file."""

    def render(self, rows: list) -> str:
        modelled = []
        for r in rows:
            grid = vacancy_grid(r)
            if grid is not None:
                modelled.append((r, grid))

        # Best score first; unscored sink to the bottom.
        modelled.sort(key=lambda rg: rg[0].get("score") if rg[0].get("score") is not None else -1,
                      reverse=True)

        body_rows = "".join(self._row_html(r, grid) for r, grid in modelled) or (
            '<tr><td colspan="13" class="empty">'
            'No properties with rent data to model.</td></tr>'
        )

        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Vacancy Sensitivity</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --ink:   #0f0f0f;
    --paper: #f5f0e8;
    --cream: #ede8dc;
    --rule:  #c8bfaa;
    --gold:  #b8960c;
    --green: #2d6a4f;
    --red:   #8b1a1a;
    --amber: #c17f24;
    --muted: #6b6355;
    --mono:  'DM Mono', monospace;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--paper);
    color: var(--ink);
    font-family: 'DM Sans', sans-serif;
    font-size: 14px;
    line-height: 1.5;
  }}
  header {{
    background: var(--cream);
    border-bottom: 3px double var(--rule);
    padding: 2rem 2.5rem 1.5rem;
  }}
  header h1 {{
    font-family: 'DM Serif Display', serif;
    font-size: 2.4rem;
    letter-spacing: -0.02em;
    line-height: 1;
  }}
  header h1 em {{ font-style: italic; color: var(--gold); }}
  .header-meta {{
    font-family: var(--mono);
    font-size: 11px;
    color: var(--muted);
    margin-top: 0.4rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }}
  .note {{
    font-family: var(--mono);
    font-size: 11.5px;
    color: var(--muted);
    margin-top: 0.8rem;
    line-height: 1.6;
    max-width: 80ch;
    border-left: 3px solid var(--gold);
    padding-left: 0.7rem;
  }}
  .page-wrap {{ max-width: 1300px; margin: 0 auto; padding: 2rem 2.5rem; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--cream); font-size: 13px; }}
  th, td {{
    padding: 0.55rem 0.6rem;
    border-bottom: 1px solid var(--rule);
    text-align: right;
    white-space: nowrap;
    vertical-align: middle;
  }}
  th {{
    font-family: var(--mono);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted);
  }}
  th.grp {{ border-bottom: 2px solid var(--gold); color: var(--ink); }}
  th:first-child, td:first-child {{ text-align: left; white-space: normal; }}
  td.num {{ font-family: var(--mono); }}
  td.addr {{ font-weight: 500; }}
  td.good {{ color: var(--green); }}
  td.fair {{ color: var(--amber); }}
  td.poor {{ color: var(--red); }}
  td.occ-sep {{ border-left: 1px solid var(--rule); }}
  .empty {{ text-align: center; color: var(--muted); padding: 2rem; }}
</style>
</head>
<body>
<header>
  <h1>Vacancy <em>Sensitivity</em></h1>
  <div class="header-meta">{len(modelled)} income properties · {stamp}</div>
  <div class="note">Cap rate and annual cash flow at 100%, 85%, 75%, and 60% occupancy. Debt
  service is held constant — only NOI falls with vacancy. Red cash flow = the deal bleeds at that
  occupancy; amber cap rate = below the 7% target.</div>
</header>
<div class="page-wrap">
  <table>
    <thead>
      <tr>
        <th>Address</th>
        <th>City</th>
        <th>Type</th>
        <th>Price</th>
        <th>Score</th>
        <th class="grp">Cap @100%</th>
        <th class="grp">CF @100%</th>
        <th class="grp">Cap @85%</th>
        <th class="grp">CF @85%</th>
        <th class="grp">Cap @75%</th>
        <th class="grp">CF @75%</th>
        <th class="grp">Cap @60%</th>
        <th class="grp">CF @60%</th>
      </tr>
    </thead>
    <tbody>
{body_rows}
    </tbody>
  </table>
</div>
</body>
</html>"""

    def _row_html(self, r: dict, grid) -> str:
        addr  = html.escape(r.get("address") or "—")
        city  = html.escape(r.get("city") or "—")
        ptype = html.escape(r.get("type") or "—")
        score = r.get("score")

        cells = ""
        for i, (_occ, cap, cf) in enumerate(grid):
            sep = " occ-sep" if i > 0 else ""
            cf_cls = "good" if cf >= 0 else "poor"
            cells += (
                f'<td class="num {_cap_grade(cap)}{sep}">{cap:.1f}%</td>'
                f'<td class="num {cf_cls}">{_money_signed(round(cf))}</td>'
            )

        return f"""      <tr>
        <td class="addr">{addr}</td>
        <td>{city}</td>
        <td>{ptype}</td>
        <td class="num">{_money(r.get('asking'))}</td>
        <td class="num {_score_grade(score)}">{f'{score:.0f}/100' if score is not None else '—'}</td>
        {cells}
      </tr>"""

    def open_in_browser(self, rows: list):
        """Build the report and open it in the default browser."""
        html_str = self.render(rows)
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False,
            prefix="vacancy_sensitivity_", encoding="utf-8"
        )
        tmp.write(html_str)
        tmp.close()
        webbrowser.open(f"file://{tmp.name}")
        print(f"\n  Vacancy sensitivity opened in browser.")
        print(f"  File saved to: {tmp.name}")
