"""HTML report: Price Drop Alerts.

Surfaces listings whose current asking price has fallen below their original
list price — both a signal of seller motivation and a marker of remaining
negotiation room. The drop is measured against original_price on file (the
project does not snapshot a first-analyzed price, so the original list is the
honest available baseline).

The reduced listings are picked server-side and embedded as JSON; the page
renders client-side so every column is click-to-sort and the list filters live
by minimum drop percentage and by status.
"""

import json as _json
import tempfile
import webbrowser
from datetime import datetime

# Ignore sub-0.1% noise so rounding/data jitter doesn't register as a "drop".
_DROP_EPSILON = 0.999


class PriceDropReportGenerator:
    """Renders the price-drop alerts report as a standalone, interactive file."""

    def render(self, rows: list) -> str:
        deals = []
        for r in rows:
            original = r.get("original") or 0
            asking   = r.get("asking") or 0
            if not (original and asking and asking < original * _DROP_EPSILON):
                continue
            amt = original - asking
            deals.append({
                "address": r.get("address"), "city": r.get("city"),
                "type": r.get("type"), "status": r.get("status"),
                "original": original, "asking": asking,
                "drop_amt": round(amt), "drop_pct": round(amt / original * 100, 1),
                "score": r.get("score"), "cap_rate": r.get("cap_rate"),
                "dom": r.get("dom"),
            })

        data_json = _json.dumps(deals)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Price Drop Alerts</title>
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
  .filter-group input, .filter-group select {{ font-family: var(--mono); font-size: 13px; width: 130px; padding: 0.35rem 0.55rem; border: 1px solid var(--rule); border-radius: 2px; background: var(--paper); color: var(--ink); }}
  .filter-group input:focus, .filter-group select:focus {{ outline: none; border-color: var(--gold); }}
  .filters button {{ font-family: var(--mono); font-size: 11px; text-transform: uppercase; letter-spacing: 0.07em; padding: 0.4rem 1rem; cursor: pointer; border: none; border-radius: 2px; background: var(--ink); color: var(--paper); }}
  .filters button:hover {{ background: #333; }}
  .filters button.reset-btn {{ background: transparent; color: var(--muted); border: 1px solid var(--rule); }}
  .filters button.reset-btn:hover {{ color: var(--ink); border-color: var(--ink); }}
  .page-wrap {{ max-width: 1200px; margin: 0 auto; padding: 2rem 2.5rem; }}
  .count {{ font-family: var(--mono); font-size: 11px; color: var(--muted); margin-bottom: 0.8rem; letter-spacing: 0.04em; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--cream); font-size: 13px; }}
  th, td {{ padding: 0.55rem 0.7rem; border-bottom: 1px solid var(--rule); text-align: right; white-space: nowrap; vertical-align: middle; }}
  th {{ font-family: var(--mono); font-size: 10px; text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); cursor: pointer; user-select: none; }}
  th:hover {{ color: var(--ink); }}
  th.sort-asc::after  {{ content: ' \\25B2'; font-size: 9px; }}
  th.sort-desc::after {{ content: ' \\25BC'; font-size: 9px; }}
  th:first-child, td:first-child {{ text-align: left; white-space: normal; }}
  td.num {{ font-family: var(--mono); }}
  td.addr {{ font-weight: 500; }}
  td.drop {{ color: var(--green); font-weight: 500; }}
  td.good {{ color: var(--green); }}
  td.fair {{ color: var(--amber); }}
  td.poor {{ color: var(--red); }}
  .st-active {{ color: var(--green); font-weight: 500; }}
  .st-inactive {{ color: var(--muted); }}
  tr:hover td {{ background: #fffdf5; }}
  .empty {{ text-align: center; color: var(--muted); padding: 2rem; }}
</style>
</head>
<body>
<header>
  <h1>Price <em>Drop</em> Alerts</h1>
  <div class="header-meta">{len(deals)} listings reduced · {stamp}</div>
  <div class="note">Listings whose current asking has fallen below their original list price. The
  drop is measured against the original list price on file — a price the seller has already
  conceded, and a marker of remaining negotiation room.</div>
  <div class="filters">
    <div class="filter-group">
      <label>Min Drop %</label>
      <input type="number" id="f-drop" step="1" placeholder="any">
    </div>
    <div class="filter-group">
      <label>Status</label>
      <select id="f-status">
        <option value="">All</option>
        <option value="active">Active</option>
        <option value="inactive">Inactive</option>
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
        <th data-col="address"  onclick="sortBy('address',this)">Address</th>
        <th data-col="city"     onclick="sortBy('city',this)">City</th>
        <th data-col="type"     onclick="sortBy('type',this)">Type</th>
        <th data-col="status"   onclick="sortBy('status',this)">Status</th>
        <th data-col="original" onclick="sortBy('original',this)">Original Price</th>
        <th data-col="asking"   onclick="sortBy('asking',this)">Current Price</th>
        <th data-col="drop_amt" onclick="sortBy('drop_amt',this)">Drop $</th>
        <th data-col="drop_pct" onclick="sortBy('drop_pct',this)" class="sort-desc">Drop %</th>
        <th data-col="score"    onclick="sortBy('score',this)">Score</th>
        <th data-col="cap_rate" onclick="sortBy('cap_rate',this)">Cap Rate</th>
        <th data-col="dom"      onclick="sortBy('dom',this)">DOM</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
</div>

<script>
const DATA = {data_json};
let sortCol = 'drop_pct';
let sortDir = -1;
let fDrop = null, fStatus = null;

function esc(s) {{
  return String(s == null ? '' : s).replace(/[&<>"]/g, c =>
    ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}})[c]);
}}
function fmtMoney(n) {{ return (n == null || isNaN(n)) ? '\\u2014' : '$' + Math.round(n).toLocaleString('en-CA'); }}
function fp(n) {{ return (n == null || isNaN(n)) ? '\\u2014' : n.toFixed(2) + '%'; }}
function capCls(v) {{ return v == null ? '' : v >= 7.5 ? 'good' : v >= 5.5 ? 'fair' : 'poor'; }}
function scoreCls(v) {{ return v == null ? '' : v >= 55 ? 'good' : v >= 35 ? 'fair' : 'poor'; }}
function statusCell(s) {{
  if (!s) return '\\u2014';
  const cls = s.toLowerCase() === 'active' ? 'st-active' : 'st-inactive';
  const txt = s.charAt(0).toUpperCase() + s.slice(1);
  return `<span class="${{cls}}">${{esc(txt)}}</span>`;
}}

function applyFilters() {{
  const d = document.getElementById('f-drop').value.trim();
  const s = document.getElementById('f-status').value;
  fDrop   = d !== '' ? parseFloat(d) : null;
  fStatus = s !== '' ? s : null;
  render();
}}
function resetFilters() {{
  fDrop = null; fStatus = null;
  document.getElementById('f-drop').value = '';
  document.getElementById('f-status').value = '';
  render();
}}
function passes(r) {{
  if (fDrop != null && (r.drop_pct == null || r.drop_pct < fDrop)) return false;
  if (fStatus != null && (r.status || '').toLowerCase() !== fStatus) return false;
  return true;
}}

function sortBy(col, th) {{
  if (sortCol === col) {{ sortDir *= -1; }}
  else {{ sortCol = col; sortDir = (col === 'original' || col === 'asking') ? 1 : -1; }}
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
      <td>${{statusCell(r.status)}}</td>
      <td class="num">${{fmtMoney(r.original)}}</td>
      <td class="num">${{fmtMoney(r.asking)}}</td>
      <td class="num drop">-${{fmtMoney(r.drop_amt)}}</td>
      <td class="num drop">${{r.drop_pct.toFixed(1)}}%</td>
      <td class="num ${{scoreCls(r.score)}}">${{r.score != null ? r.score.toFixed(0) + '/100' : '\\u2014'}}</td>
      <td class="num ${{capCls(r.cap_rate)}}">${{fp(r.cap_rate)}}</td>
      <td class="num">${{r.dom ? r.dom + 'd' : '\\u2014'}}</td>
    </tr>`).join('') : '<tr><td colspan="11" class="empty">No listings match the filters.</td></tr>';

  document.getElementById('count').textContent =
    rows.length + ' of ' + DATA.length + ' reduced listings';
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
            prefix="price_drop_", encoding="utf-8"
        )
        tmp.write(html_str)
        tmp.close()
        webbrowser.open(f"file://{tmp.name}")
        print(f"\n  Price drop alerts opened in browser.")
        print(f"  File saved to: {tmp.name}")
