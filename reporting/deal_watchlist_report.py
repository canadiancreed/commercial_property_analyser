"""HTML report: the Deal Watchlist.

An interactive table of **active**, scored listings. The page embeds the deal
data as JSON and renders client-side so the user can:
  - filter live by minimum score, minimum cap rate, and minimum price drop, and
  - sort by any column by clicking its header (click again to reverse).

Only active listings are included — the watchlist is about deals you can still
act on. Mirrors the palette/fonts of the other reports.
"""

import json as _json
import tempfile
import webbrowser
from datetime import datetime

# Initial value for the Min Score filter; the user can change it in the page.
DEFAULT_MIN_SCORE = 55

# Fields carried into the page for each deal (keeps the embedded JSON lean).
_FIELDS = ("address", "city", "type", "asking", "score", "cap_rate",
           "coc", "irr", "cf_annual", "dscr", "dom", "price_drop")


class DealWatchlistReportGenerator:
    """Renders the deal watchlist as a standalone, interactive HTML file."""

    def render(self, rows: list, min_score: float = DEFAULT_MIN_SCORE) -> str:
        # Active, scored listings only — the data the page filters and sorts.
        deals = [
            {k: r.get(k) for k in _FIELDS}
            for r in rows
            if r.get("score") is not None
            and (r.get("status") or "").strip().lower() == "active"
        ]
        data_json = _json.dumps(deals)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Deal Watchlist</title>
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
  .filters {{
    display: flex; flex-wrap: wrap; gap: 1rem; align-items: flex-end;
    margin-top: 1rem;
  }}
  .filter-group {{ display: flex; flex-direction: column; gap: 0.25rem; }}
  .filter-group label {{
    font-family: var(--mono); font-size: 10px; text-transform: uppercase;
    letter-spacing: 0.08em; color: var(--muted);
  }}
  .filter-group input {{
    font-family: var(--mono); font-size: 13px; width: 120px;
    padding: 0.35rem 0.55rem; border: 1px solid var(--rule);
    border-radius: 2px; background: var(--paper); color: var(--ink);
  }}
  .filter-group input:focus {{ outline: none; border-color: var(--gold); }}
  .filters button {{
    font-family: var(--mono); font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.07em; padding: 0.4rem 1rem; cursor: pointer;
    border: none; border-radius: 2px; background: var(--ink); color: var(--paper);
  }}
  .filters button:hover {{ background: #333; }}
  .filters button.reset-btn {{
    background: transparent; color: var(--muted); border: 1px solid var(--rule);
  }}
  .filters button.reset-btn:hover {{ color: var(--ink); border-color: var(--ink); }}
  .page-wrap {{ max-width: 1250px; margin: 0 auto; padding: 2rem 2.5rem; }}
  .count {{
    font-family: var(--mono); font-size: 11px; color: var(--muted);
    margin-bottom: 0.8rem; letter-spacing: 0.04em;
  }}
  table {{ width: 100%; border-collapse: collapse; background: var(--cream); font-size: 13px; }}
  th, td {{
    padding: 0.55rem 0.7rem;
    border-bottom: 1px solid var(--rule);
    text-align: right;
    white-space: nowrap;
    vertical-align: middle;
  }}
  th {{
    font-family: var(--mono);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--muted);
    cursor: pointer;
    user-select: none;
  }}
  th:hover {{ color: var(--ink); }}
  th.sort-asc::after  {{ content: ' \\25B2'; font-size: 9px; }}
  th.sort-desc::after {{ content: ' \\25BC'; font-size: 9px; }}
  th:first-child, td:first-child {{ text-align: left; white-space: normal; }}
  td.num {{ font-family: var(--mono); }}
  td.addr {{ font-weight: 500; }}
  td.good {{ color: var(--green); }}
  td.fair {{ color: var(--amber); }}
  td.poor {{ color: var(--red); }}
  tr:hover td {{ background: #fffdf5; }}
  .empty {{ text-align: center; color: var(--muted); padding: 2rem; }}
</style>
</head>
<body>
<header>
  <h1>Deal <em>Watchlist</em></h1>
  <div class="header-meta">Active listings · {len(deals)} scored · {stamp}</div>
  <div class="filters">
    <div class="filter-group">
      <label>Min Score</label>
      <input type="number" id="f-score" min="0" max="100" placeholder="e.g. 55">
    </div>
    <div class="filter-group">
      <label>Min Cap Rate %</label>
      <input type="number" id="f-cap" step="0.5" placeholder="any">
    </div>
    <div class="filter-group">
      <label>Min Price Drop %</label>
      <input type="number" id="f-drop" step="1" placeholder="any">
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
        <th data-col="address"   onclick="sortBy('address',this)">Address</th>
        <th data-col="city"      onclick="sortBy('city',this)">City</th>
        <th data-col="type"      onclick="sortBy('type',this)">Type</th>
        <th data-col="asking"    onclick="sortBy('asking',this)">Price</th>
        <th data-col="score"     onclick="sortBy('score',this)" class="sort-desc">Score</th>
        <th data-col="cap_rate"  onclick="sortBy('cap_rate',this)">Cap Rate</th>
        <th data-col="coc"       onclick="sortBy('coc',this)">CoCR</th>
        <th data-col="irr"       onclick="sortBy('irr',this)">IRR</th>
        <th data-col="cf_annual" onclick="sortBy('cf_annual',this)">Annual CF</th>
        <th data-col="dscr"      onclick="sortBy('dscr',this)">DSCR</th>
        <th data-col="dom"       onclick="sortBy('dom',this)">DOM</th>
        <th data-col="price_drop" onclick="sortBy('price_drop',this)">Price Drop</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
</div>

<script>
const DATA = {data_json};
let sortCol = 'score';
let sortDir = -1;            // -1 = descending, 1 = ascending
let fScore = {min_score};    // initial Min Score filter
let fCap = null, fDrop = null;

function esc(s) {{
  return String(s == null ? '' : s).replace(/[&<>"]/g, c =>
    ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}})[c]);
}}
function fmtMoney(n) {{
  if (n == null || isNaN(n)) return '\\u2014';
  return '$' + Math.round(n).toLocaleString('en-CA');
}}
function fmtCf(n) {{
  if (n == null || isNaN(n)) return '\\u2014';
  return (n < 0 ? '-' : '') + '$' + Math.abs(Math.round(n)).toLocaleString('en-CA');
}}
function fp(n) {{ return (n == null || isNaN(n)) ? '\\u2014' : n.toFixed(2) + '%'; }}
function fp1(n) {{ return (n == null || isNaN(n)) ? '\\u2014' : n.toFixed(1) + '%'; }}

function capCls(v)  {{ return v == null ? '' : v >= 7.5 ? 'good' : v >= 5.5 ? 'fair' : 'poor'; }}
function cocCls(v)  {{ return v == null ? '' : v >= 10  ? 'good' : v >= 5   ? 'fair' : 'poor'; }}
function irrCls(v)  {{ return v == null ? '' : v >= 15  ? 'good' : v >= 10  ? 'fair' : 'poor'; }}
function dscrCls(v) {{ return v == null ? '' : v >= 1.5 ? 'good' : v >= 1.25? 'fair' : 'poor'; }}
function cfCls(v)   {{ return v == null ? '' : v > 0 ? (v >= 10000 ? 'good' : 'fair') : 'poor'; }}
function scoreCls(v){{ return v == null ? '' : v >= 55 ? 'good' : v >= 35 ? 'fair' : 'poor'; }}

function applyFilters() {{
  const s = document.getElementById('f-score').value.trim();
  const c = document.getElementById('f-cap').value.trim();
  const d = document.getElementById('f-drop').value.trim();
  fScore = s !== '' ? parseFloat(s) : null;
  fCap   = c !== '' ? parseFloat(c) : null;
  fDrop  = d !== '' ? parseFloat(d) : null;
  render();
}}
function resetFilters() {{
  fScore = null; fCap = null; fDrop = null;
  document.getElementById('f-score').value = '';
  document.getElementById('f-cap').value = '';
  document.getElementById('f-drop').value = '';
  render();
}}
function passes(r) {{
  if (fScore != null && (r.score == null || r.score < fScore)) return false;
  if (fCap   != null && (r.cap_rate == null || r.cap_rate < fCap)) return false;
  if (fDrop  != null && (r.price_drop == null || r.price_drop < fDrop)) return false;
  return true;
}}

function sortBy(col, th) {{
  if (sortCol === col) {{ sortDir *= -1; }}
  else {{ sortCol = col; sortDir = (col === 'asking') ? 1 : -1; }}
  document.querySelectorAll('#tbl th').forEach(h => h.classList.remove('sort-asc', 'sort-desc'));
  th.classList.add(sortDir === 1 ? 'sort-asc' : 'sort-desc');
  render();
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
      <td class="num ${{capCls(r.cap_rate)}}">${{fp(r.cap_rate)}}</td>
      <td class="num ${{cocCls(r.coc)}}">${{fp(r.coc)}}</td>
      <td class="num ${{irrCls(r.irr)}}">${{fp(r.irr)}}</td>
      <td class="num ${{cfCls(r.cf_annual)}}">${{fmtCf(r.cf_annual)}}</td>
      <td class="num ${{dscrCls(r.dscr)}}">${{r.dscr != null ? r.dscr.toFixed(2) : '\\u2014'}}</td>
      <td class="num">${{r.dom ? r.dom + 'd' : '\\u2014'}}</td>
      <td class="num ${{r.price_drop > 0 ? 'good' : ''}}">${{r.price_drop > 0 ? fp1(r.price_drop) : '\\u2014'}}</td>
    </tr>`).join('') : '<tr><td colspan="12" class="empty">No active deals match the filters.</td></tr>';

  document.getElementById('count').textContent =
    rows.length + ' of ' + DATA.length + ' active deals';
}}

// Seed the Min Score input with the initial filter and do the first render.
if (fScore != null) document.getElementById('f-score').value = fScore;
render();
</script>
</body>
</html>"""

    def open_in_browser(self, rows: list, min_score: float = DEFAULT_MIN_SCORE):
        """Build the report and open it in the default browser."""
        html_str = self.render(rows, min_score)
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False,
            prefix="deal_watchlist_", encoding="utf-8"
        )
        tmp.write(html_str)
        tmp.close()
        webbrowser.open(f"file://{tmp.name}")
        print(f"\n  Deal watchlist opened in browser.")
        print(f"  File saved to: {tmp.name}")
