"""HTML report: Cap-Rate & $/sqft Benchmarking.

Places every listing next to its peers and flags the over- and under-priced
ones. For each property it computes price per square foot and cap rate, then
compares both against the average of comparable properties — preferring the
tightest comp set available:

    city + type  →  province + type  →  type-wide

The property itself is excluded from its own peer average, and the basis used
is shown so the strength of each comparison is visible (a city comp is stronger
than a type-wide one).

The comparison is computed server-side (benchmark_rows) and embedded as JSON;
the page renders client-side so every column is click-to-sort and the list
filters live by verdict and by a minimum number of comparables.
"""

import json as _json
import tempfile
import webbrowser
from datetime import datetime

# A property is called cheap/pricey only past this gap from peers; inside it,
# it reads as "at market" rather than over-claiming signal from noise.
_MATERIAL_PCT = 10.0


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def benchmark_rows(rows: list) -> list:
    """Enrich each priced property with peer-comparison fields and return the
    list sorted most-underpriced first (un-benchmarkable rows sink to the end).

    Each returned dict carries: the original row, ppsf, peer_ppsf, ppsf_delta
    (%), cap, peer_cap, cap_delta (pts), basis ('city'/'province'/'type'/None),
    comps (peer count), and verdict ('under'/'over'/'market'/None).
    """
    # Build the priced universe with an index so a property can be excluded from
    # its own peer set.
    items = []
    for i, r in enumerate(rows):
        sqft   = r.get("total_sq_ft") or r.get("sqft") or 0
        asking = r.get("asking") or 0
        if sqft > 0 and asking > 0:
            cap = r.get("cap_rate")
            items.append({
                "i": i, "row": r,
                "ppsf": asking / sqft,
                "cap": cap if cap else None,   # treat 0 / None as "no cap"
                "city": (r.get("city") or "").strip().lower(),
                "prov": (r.get("province") or "").strip().lower(),
                "type": (r.get("type") or "").strip().lower(),
            })

    def group_by(keyfn):
        g = {}
        for it in items:
            g.setdefault(keyfn(it), []).append(it)
        return g

    by_city = group_by(lambda it: (it["city"], it["prov"], it["type"]))
    by_prov = group_by(lambda it: (it["prov"], it["type"]))
    by_type = group_by(lambda it: (it["type"],))

    tiers = [
        ("city",     by_city, lambda it: (it["city"], it["prov"], it["type"])),
        ("province", by_prov, lambda it: (it["prov"], it["type"])),
        ("type",     by_type, lambda it: (it["type"],)),
    ]

    out = []
    for it in items:
        peers = []
        basis = None
        # City needs a real city to be a meaningful tier; an empty type can't
        # benchmark at all.
        for label, group, keyfn in tiers:
            if label == "city" and not it["city"]:
                continue
            if label == "type" and not it["type"]:
                continue
            candidates = [m for m in group.get(keyfn(it), []) if m["i"] != it["i"]]
            if candidates:
                peers, basis = candidates, label
                break

        peer_ppsf = _mean([m["ppsf"] for m in peers]) if peers else None
        peer_cap  = _mean([m["cap"] for m in peers]) if peers else None
        ppsf_delta = ((it["ppsf"] - peer_ppsf) / peer_ppsf * 100
                      if peer_ppsf else None)
        cap_delta = (it["cap"] - peer_cap
                     if it["cap"] is not None and peer_cap is not None else None)

        if ppsf_delta is None:
            verdict = None
        elif ppsf_delta <= -_MATERIAL_PCT:
            verdict = "under"
        elif ppsf_delta >= _MATERIAL_PCT:
            verdict = "over"
        else:
            verdict = "market"

        out.append({
            "row": it["row"], "ppsf": it["ppsf"], "cap": it["cap"],
            "peer_ppsf": peer_ppsf, "peer_cap": peer_cap,
            "ppsf_delta": ppsf_delta, "cap_delta": cap_delta,
            "basis": basis, "comps": len(peers), "verdict": verdict,
        })

    # Most underpriced first; un-benchmarkable rows (no delta) at the very end.
    out.sort(key=lambda e: (e["ppsf_delta"] is None,
                            e["ppsf_delta"] if e["ppsf_delta"] is not None else 0))
    return out


class BenchmarkReportGenerator:
    """Renders the cap-rate & $/sqft benchmarking report as a standalone,
    interactive HTML file."""

    def render(self, rows: list) -> str:
        deals = []
        for e in benchmark_rows(rows):
            r = e["row"]
            deals.append({
                "address": r.get("address"), "city": r.get("city"),
                "type": r.get("type"),
                "ppsf": round(e["ppsf"]) if e["ppsf"] is not None else None,
                "peer_ppsf": round(e["peer_ppsf"]) if e["peer_ppsf"] is not None else None,
                "ppsf_delta": round(e["ppsf_delta"], 1) if e["ppsf_delta"] is not None else None,
                "cap": round(e["cap"], 2) if e["cap"] is not None else None,
                "peer_cap": round(e["peer_cap"], 2) if e["peer_cap"] is not None else None,
                "cap_delta": round(e["cap_delta"], 2) if e["cap_delta"] is not None else None,
                "basis": e["basis"], "comps": e["comps"], "verdict": e["verdict"],
            })

        data_json = _json.dumps(deals)
        n_under = sum(1 for d in deals if d["verdict"] == "under")
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        material = _MATERIAL_PCT

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cap Rate &amp; $/sqft Benchmarking</title>
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
  .note {{ font-family: var(--mono); font-size: 11.5px; color: var(--muted); margin-top: 0.8rem; line-height: 1.6; max-width: 86ch; border-left: 3px solid var(--gold); padding-left: 0.7rem; }}
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
  th, td {{ padding: 0.55rem 0.7rem; border-bottom: 1px solid var(--rule); text-align: right; white-space: nowrap; vertical-align: middle; }}
  th {{ font-family: var(--mono); font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); cursor: pointer; user-select: none; }}
  th:hover {{ color: var(--ink); }}
  th.sort-asc::after  {{ content: ' \\25B2'; font-size: 9px; }}
  th.sort-desc::after {{ content: ' \\25BC'; font-size: 9px; }}
  th:first-child, td:first-child {{ text-align: left; white-space: normal; }}
  td.num {{ font-family: var(--mono); }}
  td.addr {{ font-weight: 500; }}
  td.good {{ color: var(--green); }}
  td.poor {{ color: var(--red); }}
  .basis {{ color: var(--muted); font-size: 10px; }}
  .verdict {{ font-family: var(--mono); font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; padding: 0.15rem 0.5rem; border-radius: 3px; }}
  .verdict.good {{ background: #d4edda; color: var(--green); }}
  .verdict.poor {{ background: #f8d7da; color: var(--red); }}
  .verdict.info {{ background: var(--cream); color: var(--muted); }}
  tr:hover td {{ background: #fffdf5; }}
  .empty {{ text-align: center; color: var(--muted); padding: 2rem; }}
</style>
</head>
<body>
<header>
  <h1>Cap Rate &amp; <em>$/sqft</em> Benchmarking</h1>
  <div class="header-meta">{len(deals)} properties · {n_under} underpriced vs peers · {stamp}</div>
  <div class="note">Each property vs the average of comparable listings — closest comp set first
  (city+type, then province+type, then type-wide; the basis is shown in the Comps column). The
  property itself is excluded from its own average. "Δ" is the gap from peers: negative $/sqft and
  positive cap are in the buyer's favour.</div>
  <div class="filters">
    <div class="filter-group">
      <label>Verdict</label>
      <select id="f-verdict">
        <option value="">All</option>
        <option value="under">Underpriced</option>
        <option value="market">At market</option>
        <option value="over">Overpriced</option>
      </select>
    </div>
    <div class="filter-group">
      <label>Min Comps</label>
      <input type="number" id="f-comps" min="0" step="1" placeholder="any">
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
        <th data-col="address"    onclick="sortBy('address',this)">Address</th>
        <th data-col="city"       onclick="sortBy('city',this)">City</th>
        <th data-col="type"       onclick="sortBy('type',this)">Type</th>
        <th data-col="ppsf"       onclick="sortBy('ppsf',this)">$/sqft</th>
        <th data-col="peer_ppsf"  onclick="sortBy('peer_ppsf',this)">Peer $/sqft</th>
        <th data-col="ppsf_delta" onclick="sortBy('ppsf_delta',this)" class="sort-asc">Δ $/sqft</th>
        <th data-col="cap"        onclick="sortBy('cap',this)">Cap</th>
        <th data-col="peer_cap"   onclick="sortBy('peer_cap',this)">Peer Cap</th>
        <th data-col="cap_delta"  onclick="sortBy('cap_delta',this)">Δ Cap</th>
        <th data-col="comps"      onclick="sortBy('comps',this)">Comps</th>
        <th data-col="verdict"    onclick="sortBy('verdict',this)">Verdict</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
</div>

<script>
const DATA = {data_json};
const VERDICT_META = {{ under: ['Underpriced','good'], over: ['Overpriced','poor'], market: ['At market','info'] }};
const BASIS_LABEL = {{ city: 'city', province: 'prov.', type: 'type' }};
let sortCol = 'ppsf_delta';
let sortDir = 1;            // ascending = most underpriced first
let fVerdict = null, fComps = null;

function esc(s) {{
  return String(s == null ? '' : s).replace(/[&<>"]/g, c =>
    ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}})[c]);
}}
function fmtMoney(n) {{ return (n == null || isNaN(n)) ? '\\u2014' : '$' + Math.round(n).toLocaleString('en-CA'); }}
function fp(n) {{ return (n == null || isNaN(n)) ? '\\u2014' : n.toFixed(2) + '%'; }}
function signedPct(n) {{ return (n == null || isNaN(n)) ? '\\u2014' : (n > 0 ? '+' : '') + n.toFixed(1) + '%'; }}

function applyFilters() {{
  const v = document.getElementById('f-verdict').value;
  const c = document.getElementById('f-comps').value.trim();
  fVerdict = v !== '' ? v : null;
  fComps   = c !== '' ? parseFloat(c) : null;
  render();
}}
function resetFilters() {{
  fVerdict = null; fComps = null;
  document.getElementById('f-verdict').value = '';
  document.getElementById('f-comps').value = '';
  render();
}}
function passes(r) {{
  if (fVerdict != null && r.verdict !== fVerdict) return false;
  if (fComps != null && r.comps < fComps) return false;
  return true;
}}

function sortBy(col, th) {{
  if (sortCol === col) {{ sortDir *= -1; }}
  else {{ sortCol = col; sortDir = (col === 'ppsf_delta' || col === 'ppsf' || col === 'peer_ppsf') ? 1 : -1; }}
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

  document.getElementById('tbody').innerHTML = rows.length ? rows.map(r => {{
    const ppsfCls = r.ppsf_delta == null ? '' : r.ppsf_delta <= -{material} ? 'good' : r.ppsf_delta >= {material} ? 'poor' : '';
    const capCls  = r.cap_delta == null ? '' : r.cap_delta > 0 ? 'good' : r.cap_delta < 0 ? 'poor' : '';
    const comps = r.basis
      ? r.comps + ' <span class="basis">' + (BASIS_LABEL[r.basis] || r.basis) + '</span>'
      : '\\u2014';
    let vcell;
    if (r.verdict) {{ const m = VERDICT_META[r.verdict]; vcell = `<span class="verdict ${{m[1]}}">${{m[0]}}</span>`; }}
    else vcell = '<span class="verdict info">No comps</span>';
    return `<tr>
      <td class="addr">${{esc(r.address)}}</td>
      <td>${{esc(r.city)}}</td>
      <td>${{esc(r.type)}}</td>
      <td class="num">${{fmtMoney(r.ppsf)}}</td>
      <td class="num">${{fmtMoney(r.peer_ppsf)}}</td>
      <td class="num ${{ppsfCls}}">${{signedPct(r.ppsf_delta)}}</td>
      <td class="num">${{fp(r.cap)}}</td>
      <td class="num">${{fp(r.peer_cap)}}</td>
      <td class="num ${{capCls}}">${{r.cap_delta == null ? '\\u2014' : (r.cap_delta > 0 ? '+' : '') + r.cap_delta.toFixed(2) + ' pts'}}</td>
      <td class="num">${{comps}}</td>
      <td>${{vcell}}</td>
    </tr>`;
  }}).join('') : '<tr><td colspan="11" class="empty">No properties match the filters.</td></tr>';

  document.getElementById('count').textContent =
    rows.length + ' of ' + DATA.length + ' properties';
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
            prefix="benchmark_", encoding="utf-8"
        )
        tmp.write(html_str)
        tmp.close()
        webbrowser.open(f"file://{tmp.name}")
        print(f"\n  Benchmarking report opened in browser.")
        print(f"  File saved to: {tmp.name}")
