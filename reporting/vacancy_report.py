"""HTML report: Vacancy Sensitivity.

Stress-tests each income property by recomputing its cap rate and annual cash
flow at 100%, 85%, 75%, and 60% occupancy. Debt service is held constant (it
doesn't move with occupancy); only NOI — and therefore cash flow and cap rate —
falls as vacancy rises. This surfaces how much vacancy a deal can absorb before
it bleeds.

The grid is computed server-side (with the project's province-aware
MortgageCalculator for debt service) and embedded as JSON; the page renders
client-side so every column is click-to-sort and the list can be filtered to a
minimum score and to deals that stay cash-flow positive at a chosen occupancy.
"""

import json as _json
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
    """Renders the vacancy-sensitivity report as a standalone, interactive file."""

    def render(self, rows: list) -> str:
        deals = []
        for r in rows:
            grid = vacancy_grid(r)
            if grid is None:
                continue
            deal = {
                "address": r.get("address"), "city": r.get("city"),
                "type": r.get("type"), "asking": r.get("asking"),
                "score": r.get("score"),
            }
            for (occ, cap, cf) in grid:
                tag = f"{int(round(occ * 100))}"
                deal[f"cap{tag}"] = round(cap, 2)
                deal[f"cf{tag}"]  = round(cf)
            deals.append(deal)

        data_json = _json.dumps(deals)
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
  body {{ background: var(--paper); color: var(--ink); font-family: 'DM Sans', sans-serif; font-size: 14px; line-height: 1.5; }}
  header {{ background: var(--cream); border-bottom: 3px double var(--rule); padding: 2rem 2.5rem 1.5rem; }}
  header h1 {{ font-family: 'DM Serif Display', serif; font-size: 2.4rem; letter-spacing: -0.02em; line-height: 1; }}
  header h1 em {{ font-style: italic; color: var(--gold); }}
  .header-meta {{ font-family: var(--mono); font-size: 11px; color: var(--muted); margin-top: 0.4rem; letter-spacing: 0.08em; text-transform: uppercase; }}
  .note {{ font-family: var(--mono); font-size: 11.5px; color: var(--muted); margin-top: 0.8rem; line-height: 1.6; max-width: 82ch; border-left: 3px solid var(--gold); padding-left: 0.7rem; }}
  .filters {{ display: flex; flex-wrap: wrap; gap: 1rem; align-items: flex-end; margin-top: 1rem; }}
  .filter-group {{ display: flex; flex-direction: column; gap: 0.25rem; }}
  .filter-group label {{ font-family: var(--mono); font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }}
  .filter-group input, .filter-group select {{ font-family: var(--mono); font-size: 13px; width: 150px; padding: 0.35rem 0.55rem; border: 1px solid var(--rule); border-radius: 2px; background: var(--paper); color: var(--ink); }}
  .filter-group input:focus, .filter-group select:focus {{ outline: none; border-color: var(--gold); }}
  .filters button {{ font-family: var(--mono); font-size: 11px; text-transform: uppercase; letter-spacing: 0.07em; padding: 0.4rem 1rem; cursor: pointer; border: none; border-radius: 2px; background: var(--ink); color: var(--paper); }}
  .filters button:hover {{ background: #333; }}
  .filters button.reset-btn {{ background: transparent; color: var(--muted); border: 1px solid var(--rule); }}
  .filters button.reset-btn:hover {{ color: var(--ink); border-color: var(--ink); }}
  .page-wrap {{ max-width: 1300px; margin: 0 auto; padding: 2rem 2.5rem; }}
  .count {{ font-family: var(--mono); font-size: 11px; color: var(--muted); margin-bottom: 0.8rem; letter-spacing: 0.04em; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--cream); font-size: 13px; }}
  th, td {{ padding: 0.55rem 0.6rem; border-bottom: 1px solid var(--rule); text-align: right; white-space: nowrap; vertical-align: middle; }}
  th {{ font-family: var(--mono); font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); cursor: pointer; user-select: none; }}
  th:hover {{ color: var(--ink); }}
  th.grp {{ color: var(--ink); border-bottom: 2px solid var(--gold); }}
  th.sort-asc::after  {{ content: ' \\25B2'; font-size: 9px; }}
  th.sort-desc::after {{ content: ' \\25BC'; font-size: 9px; }}
  th:first-child, td:first-child {{ text-align: left; white-space: normal; }}
  td.num {{ font-family: var(--mono); }}
  td.addr {{ font-weight: 500; }}
  td.good {{ color: var(--green); }}
  td.fair {{ color: var(--amber); }}
  td.poor {{ color: var(--red); }}
  td.occ-sep {{ border-left: 1px solid var(--rule); }}
  tr:hover td {{ background: #fffdf5; }}
  .empty {{ text-align: center; color: var(--muted); padding: 2rem; }}
</style>
</head>
<body>
<header>
  <h1>Vacancy <em>Sensitivity</em></h1>
  <div class="header-meta">Income properties · {len(deals)} modelled · {stamp}</div>
  <div class="note">Cap rate and annual cash flow at 100%, 85%, 75%, and 60% occupancy. Debt
  service is held constant — only NOI falls with vacancy. Red cash flow = the deal bleeds at that
  occupancy; amber cap rate = below the 7% target.</div>
  <div class="filters">
    <div class="filter-group">
      <label>Min Score</label>
      <input type="number" id="f-score" min="0" max="100" placeholder="any">
    </div>
    <div class="filter-group">
      <label>Cash-flow positive at</label>
      <select id="f-occ">
        <option value="">Any occupancy</option>
        <option value="100">100% occupancy</option>
        <option value="85">85% occupancy</option>
        <option value="75">75% occupancy</option>
        <option value="60">60% occupancy</option>
      </select>
    </div>
    <button onclick="applyFilters()">Apply</button>
    <button class="reset-btn" onclick="resetFilters()">Reset</button>
  </div>
</header>
<div class="page-wrap">
  <div class="count" id="count"></div>
  <table id="tbl">
    <thead>
      <tr>
        <th data-col="address" onclick="sortBy('address',this)">Address</th>
        <th data-col="city"    onclick="sortBy('city',this)">City</th>
        <th data-col="type"    onclick="sortBy('type',this)">Type</th>
        <th data-col="asking"  onclick="sortBy('asking',this)">Price</th>
        <th data-col="score"   onclick="sortBy('score',this)" class="sort-desc">Score</th>
        <th class="grp" data-col="cap100" onclick="sortBy('cap100',this)">Cap @100%</th>
        <th class="grp" data-col="cf100"  onclick="sortBy('cf100',this)">CF @100%</th>
        <th class="grp" data-col="cap85"  onclick="sortBy('cap85',this)">Cap @85%</th>
        <th class="grp" data-col="cf85"   onclick="sortBy('cf85',this)">CF @85%</th>
        <th class="grp" data-col="cap75"  onclick="sortBy('cap75',this)">Cap @75%</th>
        <th class="grp" data-col="cf75"   onclick="sortBy('cf75',this)">CF @75%</th>
        <th class="grp" data-col="cap60"  onclick="sortBy('cap60',this)">Cap @60%</th>
        <th class="grp" data-col="cf60"   onclick="sortBy('cf60',this)">CF @60%</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
</div>

<script>
const DATA = {data_json};
let sortCol = 'score';
let sortDir = -1;
let fScore = null, fOcc = null;

function esc(s) {{
  return String(s == null ? '' : s).replace(/[&<>"]/g, c =>
    ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}})[c]);
}}
function fmtMoney(n) {{ return (n == null || isNaN(n)) ? '\\u2014' : '$' + Math.round(n).toLocaleString('en-CA'); }}
function fmtCf(n) {{ return (n == null || isNaN(n)) ? '\\u2014' : (n < 0 ? '-' : '') + '$' + Math.abs(Math.round(n)).toLocaleString('en-CA'); }}
function capCls(v) {{ return v == null ? '' : v >= 7 ? 'good' : v >= 5 ? 'fair' : 'poor'; }}
function scoreCls(v) {{ return v == null ? '' : v >= 55 ? 'good' : v >= 35 ? 'fair' : 'poor'; }}

function applyFilters() {{
  const s = document.getElementById('f-score').value.trim();
  const o = document.getElementById('f-occ').value;
  fScore = s !== '' ? parseFloat(s) : null;
  fOcc   = o !== '' ? o : null;
  render();
}}
function resetFilters() {{
  fScore = null; fOcc = null;
  document.getElementById('f-score').value = '';
  document.getElementById('f-occ').value = '';
  render();
}}
function passes(r) {{
  if (fScore != null && (r.score == null || r.score < fScore)) return false;
  if (fOcc != null && !(r['cf' + fOcc] >= 0)) return false;
  return true;
}}

function sortBy(col, th) {{
  if (sortCol === col) {{ sortDir *= -1; }}
  else {{ sortCol = col; sortDir = (col === 'asking') ? 1 : -1; }}
  document.querySelectorAll('#tbl th').forEach(h => h.classList.remove('sort-asc', 'sort-desc'));
  th.classList.add(sortDir === 1 ? 'sort-asc' : 'sort-desc');
  render();
}}

function capTd(v, sep) {{
  return `<td class="num ${{capCls(v)}}${{sep ? ' occ-sep' : ''}}">${{v != null ? v.toFixed(1) + '%' : '\\u2014'}}</td>`;
}}
function cfTd(v) {{
  return `<td class="num ${{v != null ? (v >= 0 ? 'good' : 'poor') : ''}}">${{fmtCf(v)}}</td>`;
}}

function render() {{
  let rows = DATA.filter(passes);
  rows.sort((a, b) => {{
    let av = a[sortCol], bv = b[sortCol];
    if (av == null) av = sortDir < 0 ? -Infinity : Infinity;
    if (bv == null) bv = sortDir < 0 ? -Infinity : Infinity;
    if (typeof av === 'string' || typeof bv === 'string')
      return String(av).localeCompare(String(bv)) * sortDir;
    return (av - bv) * sortDir;
  }});

  document.getElementById('tbody').innerHTML = rows.length ? rows.map(r => `
    <tr>
      <td class="addr">${{esc(r.address)}}</td>
      <td>${{esc(r.city)}}</td>
      <td>${{esc(r.type)}}</td>
      <td class="num">${{fmtMoney(r.asking)}}</td>
      <td class="num ${{scoreCls(r.score)}}">${{r.score != null ? r.score.toFixed(0) + '/100' : '\\u2014'}}</td>
      ${{capTd(r.cap100, false)}}${{cfTd(r.cf100)}}
      ${{capTd(r.cap85, true)}}${{cfTd(r.cf85)}}
      ${{capTd(r.cap75, true)}}${{cfTd(r.cf75)}}
      ${{capTd(r.cap60, true)}}${{cfTd(r.cf60)}}
    </tr>`).join('') : '<tr><td colspan="13" class="empty">No properties match the filters.</td></tr>';

  document.getElementById('count').textContent =
    rows.length + ' of ' + DATA.length + ' income properties';
}}

render();
</script>
</body>
</html>"""

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
