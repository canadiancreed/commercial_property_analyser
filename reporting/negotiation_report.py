"""HTML report: Negotiation Targets (bid anchors).

For each active, scored property, the scorer's target solver finds the single
lever value that — changed on its own — would lift the deal to a perfect score:
the price to negotiate down to, the rent it would need, a refinance rate, or a
larger down payment.

The page embeds the deals as JSON and renders client-side: every column is
click-to-sort, and the list filters live by minimum score, minimum cap rate,
and minimum negotiation room (how far the target price sits below today's
asking).
"""

import json as _json
import tempfile
import webbrowser
from datetime import datetime

_FIELDS = ("address", "city", "type", "asking", "score", "cap_rate")


class NegotiationReportGenerator:
    """Renders the negotiation-targets report as a standalone, interactive file."""

    def render(self, rows: list) -> str:
        deals = []
        for r in rows:
            if r.get("score") is None:
                continue
            if (r.get("status") or "").strip().lower() != "active":
                continue
            t = r.get("targets") or {}
            asking = r.get("asking") or 0
            t_price = t.get("price")
            # Negotiation room: how far below asking the target price sits (%).
            room = ((asking - t_price) / asking * 100
                    if t_price and asking else None)
            deal = {k: r.get(k) for k in _FIELDS}
            deal.update({
                "t_price": t_price, "t_rent": t.get("rent"),
                "t_rate": t.get("rate"), "t_down": t.get("down_pct"),
                "room": room,
            })
            deals.append(deal)

        data_json = _json.dumps(deals)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Negotiation Targets</title>
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
  .note {{ font-family: var(--mono); font-size: 11.5px; color: var(--muted); margin-top: 0.8rem; line-height: 1.6; max-width: 78ch; border-left: 3px solid var(--gold); padding-left: 0.7rem; }}
  .filters {{ display: flex; flex-wrap: wrap; gap: 1rem; align-items: flex-end; margin-top: 1rem; }}
  .filter-group {{ display: flex; flex-direction: column; gap: 0.25rem; }}
  .filter-group label {{ font-family: var(--mono); font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }}
  .filter-group input {{ font-family: var(--mono); font-size: 13px; width: 130px; padding: 0.35rem 0.55rem; border: 1px solid var(--rule); border-radius: 2px; background: var(--paper); color: var(--ink); }}
  .filter-group input:focus {{ outline: none; border-color: var(--gold); }}
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
  td.good {{ color: var(--green); }}
  td.fair {{ color: var(--amber); }}
  td.poor {{ color: var(--red); }}
  span.good {{ color: var(--green); }}
  span.poor {{ color: var(--red); }}
  tr:hover td {{ background: #fffdf5; }}
  .empty {{ text-align: center; color: var(--muted); padding: 2rem; }}
</style>
</head>
<body>
<header>
  <h1>Negotiation <em>Targets</em></h1>
  <div class="header-meta">Active listings · {len(deals)} scored · {stamp}</div>
  <div class="note">Each target is the single lever value that alone would lift the deal to a
  perfect score — the price to negotiate down to, the rent it would need, a refinance rate, or a
  larger down payment. "Room" beside Target Price is how far below today's asking it sits.</div>
  <div class="filters">
    <div class="filter-group">
      <label>Min Score</label>
      <input type="number" id="f-score" min="0" max="100" placeholder="any">
    </div>
    <div class="filter-group">
      <label>Min Cap Rate %</label>
      <input type="number" id="f-cap" step="0.5" placeholder="any">
    </div>
    <div class="filter-group">
      <label>Min Room %</label>
      <input type="number" id="f-room" step="1" placeholder="any">
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
        <th data-col="asking"   onclick="sortBy('asking',this)">Asking</th>
        <th data-col="score"    onclick="sortBy('score',this)" class="sort-desc">Score</th>
        <th data-col="cap_rate" onclick="sortBy('cap_rate',this)">Cap Rate</th>
        <th data-col="t_price"  onclick="sortBy('t_price',this)">Target Price</th>
        <th data-col="room"     onclick="sortBy('room',this)">Room</th>
        <th data-col="t_rent"   onclick="sortBy('t_rent',this)">Target Rent/yr</th>
        <th data-col="t_rate"   onclick="sortBy('t_rate',this)">Target Rate</th>
        <th data-col="t_down"   onclick="sortBy('t_down',this)">Target Down%</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
</div>

<script>
const DATA = {data_json};
let sortCol = 'score';
let sortDir = -1;
let fScore = null, fCap = null, fRoom = null;

function esc(s) {{
  return String(s == null ? '' : s).replace(/[&<>"]/g, c =>
    ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}})[c]);
}}
function fmtMoney(n) {{ return (n == null || isNaN(n)) ? '\\u2014' : '$' + Math.round(n).toLocaleString('en-CA'); }}
function fp(n) {{ return (n == null || isNaN(n)) ? '\\u2014' : n.toFixed(2) + '%'; }}
function capCls(v) {{ return v == null ? '' : v >= 7.5 ? 'good' : v >= 5.5 ? 'fair' : 'poor'; }}
function scoreCls(v) {{ return v == null ? '' : v >= 55 ? 'good' : v >= 35 ? 'fair' : 'poor'; }}
function roomCell(v) {{
  if (v == null) return '\\u2014';
  const cls = v > 0 ? 'good' : 'poor';
  return `<span class="${{cls}}">${{v > 0 ? '-' : '+'}}${{Math.abs(v).toFixed(1)}}%</span>`;
}}

function applyFilters() {{
  const s = document.getElementById('f-score').value.trim();
  const c = document.getElementById('f-cap').value.trim();
  const r = document.getElementById('f-room').value.trim();
  fScore = s !== '' ? parseFloat(s) : null;
  fCap   = c !== '' ? parseFloat(c) : null;
  fRoom  = r !== '' ? parseFloat(r) : null;
  render();
}}
function resetFilters() {{
  fScore = fCap = fRoom = null;
  ['f-score','f-cap','f-room'].forEach(id => document.getElementById(id).value = '');
  render();
}}
function passes(r) {{
  if (fScore != null && (r.score == null || r.score < fScore)) return false;
  if (fCap   != null && (r.cap_rate == null || r.cap_rate < fCap)) return false;
  if (fRoom  != null && (r.room == null || r.room < fRoom)) return false;
  return true;
}}

function sortBy(col, th) {{
  if (sortCol === col) {{ sortDir *= -1; }}
  else {{ sortCol = col; sortDir = (col === 'asking' || col === 't_price') ? 1 : -1; }}
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
      <td class="num">${{fmtMoney(r.t_price)}}</td>
      <td class="num">${{roomCell(r.room)}}</td>
      <td class="num">${{r.t_rent != null ? fmtMoney(r.t_rent) + '/yr' : '\\u2014'}}</td>
      <td class="num">${{r.t_rate != null ? (r.t_rate * 100).toFixed(2) + '%' : '\\u2014'}}</td>
      <td class="num">${{r.t_down != null ? (r.t_down * 100).toFixed(1) + '%' : '\\u2014'}}</td>
    </tr>`).join('') : '<tr><td colspan="11" class="empty">No active deals match the filters.</td></tr>';

  document.getElementById('count').textContent =
    rows.length + ' of ' + DATA.length + ' active deals';
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
            prefix="negotiation_targets_", encoding="utf-8"
        )
        tmp.write(html_str)
        tmp.close()
        webbrowser.open(f"file://{tmp.name}")
        print(f"\n  Negotiation targets opened in browser.")
        print(f"  File saved to: {tmp.name}")
