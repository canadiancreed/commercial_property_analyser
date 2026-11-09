"""HTML report: Shortlist Comparison.

The watchlist ranks a long list; the real decision is "which of these two or
three." This report lets you tick 2–5 active, scored deals from a searchable
list and lays them out side by side — one column per deal, one metric per row —
with the best value in each row highlighted and the weakest muted, so the
trade-offs between finalists are visible at a glance.
"""

import json as _json
import tempfile
import webbrowser
from datetime import datetime

# Carried per deal. price_psf is derived here so the page stays simple.
_FIELDS = ("address", "city", "type", "asking", "sqft", "score", "cap_rate",
           "coc", "irr", "em", "dscr", "cf_annual", "dom", "price_drop",
           "verified_income_pct")


class ComparisonReportGenerator:
    """Renders the side-by-side shortlist comparison as a standalone HTML file."""

    def render(self, rows: list) -> str:
        deals = []
        for r in rows:
            if r.get("score") is None:
                continue
            if (r.get("status") or "").strip().lower() != "active":
                continue
            d = {k: r.get(k) for k in _FIELDS}
            sqft = r.get("sqft") or 0
            d["price_psf"] = (r.get("asking") / sqft) if (r.get("asking") and sqft) else None
            deals.append(d)
        deals.sort(key=lambda d: (d.get("score") is None, -(d.get("score") or 0)))
        data_json = _json.dumps(deals)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Shortlist Comparison</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --ink:#0f0f0f; --paper:#f5f0e8; --cream:#ede8dc; --rule:#c8bfaa;
    --gold:#b8960c; --green:#2d6a4f; --red:#8b1a1a; --amber:#c17f24;
    --muted:#6b6355; --mono:'DM Mono', monospace;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ background:var(--paper); color:var(--ink); font-family:'DM Sans',sans-serif; font-size:14px; line-height:1.5; }}
  header {{ background:var(--cream); border-bottom:3px double var(--rule); padding:2rem 2.5rem 1.5rem; }}
  header h1 {{ font-family:'DM Serif Display',serif; font-size:2.4rem; letter-spacing:-0.02em; line-height:1; }}
  header h1 em {{ font-style:italic; color:var(--gold); }}
  .header-meta {{ font-family:var(--mono); font-size:11px; color:var(--muted); margin-top:0.4rem; letter-spacing:0.08em; text-transform:uppercase; }}
  .layout {{ display:grid; grid-template-columns:320px 1fr; gap:1.5rem; max-width:1250px; margin:0 auto; padding:1.5rem 2.5rem 2.5rem; }}
  @media (max-width:860px) {{ .layout {{ grid-template-columns:1fr; }} }}
  .picker {{ border:1px solid var(--rule); border-radius:3px; background:var(--cream); padding:0.8rem; height:fit-content; position:sticky; top:1rem; }}
  .picker h2 {{ font-family:var(--mono); font-size:10px; text-transform:uppercase; letter-spacing:0.08em; color:var(--muted); margin-bottom:0.5rem; }}
  .picker input {{ width:100%; font-family:var(--mono); font-size:12px; padding:0.35rem 0.5rem; border:1px solid var(--rule); border-radius:2px; background:var(--paper); margin-bottom:0.5rem; }}
  .picker input:focus {{ outline:none; border-color:var(--gold); }}
  .list {{ max-height:62vh; overflow:auto; }}
  .opt {{ display:flex; gap:0.5rem; align-items:baseline; padding:0.3rem 0.2rem; border-bottom:1px solid rgba(200,191,170,0.4); cursor:pointer; font-size:13px; }}
  .opt:hover {{ background:#fffdf5; }}
  .opt input {{ width:auto; margin:0; }}
  .opt .s {{ font-family:var(--mono); font-size:11px; color:var(--muted); margin-left:auto; }}
  .opt.dim {{ display:none; }}
  .hint {{ font-family:var(--mono); font-size:10px; color:var(--muted); margin-top:0.5rem; }}
  .panel {{ overflow:auto; }}
  table {{ border-collapse:collapse; background:var(--cream); font-size:13px; min-width:100%; }}
  th, td {{ padding:0.55rem 0.9rem; border-bottom:1px solid var(--rule); text-align:right; white-space:nowrap; }}
  th {{ font-family:var(--mono); font-size:10px; text-transform:uppercase; letter-spacing:0.06em; color:var(--muted); background:var(--paper); vertical-align:bottom; }}
  th.deal {{ text-align:right; max-width:220px; white-space:normal; }}
  th.deal .city {{ display:block; font-weight:400; color:var(--muted); letter-spacing:0; text-transform:none; font-size:11px; }}
  td.metric, th.metric {{ text-align:left; font-family:var(--mono); font-size:11px; text-transform:uppercase; letter-spacing:0.05em; color:var(--muted); background:var(--paper); position:sticky; left:0; }}
  td.num {{ font-family:var(--mono); }}
  td.best {{ color:var(--green); font-weight:600; background:#e3efe7; }}
  td.worst {{ color:var(--muted); }}
  .empty {{ color:var(--muted); font-family:var(--mono); font-size:13px; padding:2rem 0; }}
</style>
</head>
<body>
<header>
  <h1>Shortlist <em>Comparison</em></h1>
  <div class="header-meta">Finalists side by side · {len(deals)} active deals · {stamp}</div>
</header>
<div class="layout">
  <div class="picker">
    <h2>Pick 2–5 deals</h2>
    <input id="search" placeholder="filter by address or city…" oninput="filter()">
    <div class="list" id="list"></div>
    <div class="hint" id="hint"></div>
  </div>
  <div class="panel" id="panel"></div>
</div>

<script>
const DATA = {data_json};
const MAX = 5;
let picked = [];

function esc(s) {{ return String(s==null?'':s).replace(/[&<>"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}})[c]); }}
function money(n) {{ if (n==null||isNaN(n)) return '\\u2014'; return (n<0?'-':'')+'$'+Math.abs(Math.round(n)).toLocaleString('en-CA'); }}
function fp(n,d=2) {{ return (n==null||isNaN(n))?'\\u2014':n.toFixed(d)+'%'; }}
function fx(n,d=2) {{ return (n==null||isNaN(n))?'\\u2014':n.toFixed(d)+'x'; }}
function fnum(n,d=2) {{ return (n==null||isNaN(n))?'\\u2014':n.toFixed(d); }}

// Metric rows: label, accessor key, formatter, and direction (1 = higher is
// better, -1 = lower is better, 0 = no winner).
const METRICS = [
  {{k:'score',     label:'Score',          fmt:v=>v==null?'\\u2014':v.toFixed(0)+'/100', dir:1}},
  {{k:'asking',    label:'Asking price',   fmt:money, dir:0}},
  {{k:'price_psf', label:'Price / sq ft',  fmt:v=>v==null?'\\u2014':'$'+v.toFixed(0), dir:-1}},
  {{k:'cap_rate',  label:'Cap rate',       fmt:v=>fp(v), dir:1}},
  {{k:'coc',       label:'Cash-on-cash',   fmt:v=>fp(v), dir:1}},
  {{k:'irr',       label:'IRR',            fmt:v=>fp(v), dir:1}},
  {{k:'em',        label:'Equity multiple',fmt:v=>fx(v), dir:1}},
  {{k:'dscr',      label:'DSCR',           fmt:v=>fnum(v), dir:1}},
  {{k:'cf_annual', label:'Annual cash flow',fmt:money, dir:1}},
  {{k:'dom',       label:'Days on market', fmt:v=>v==null?'\\u2014':v+'d', dir:-1}},
  {{k:'price_drop',label:'Price drop',     fmt:v=>(v>0?fp(v,1):'\\u2014'), dir:1}},
  {{k:'verified_income_pct', label:'Verified income', fmt:v=>v==null?'\\u2014':(v*100).toFixed(0)+'%', dir:1}},
];

function render() {{
  const panel = document.getElementById('panel');
  document.getElementById('hint').textContent = picked.length + ' selected (max ' + MAX + ')';
  if (picked.length < 2) {{
    panel.innerHTML = '<div class="empty">Tick at least two deals to compare them side by side.</div>';
    return;
  }}
  const chosen = picked.map(i => DATA[i]);
  let head = '<tr><th class="metric">Metric</th>' + chosen.map(d =>
    `<th class="deal">${{esc(d.address)}}<span class="city">${{esc(d.city)}} · ${{esc(d.type)}}</span></th>`).join('') + '</tr>';
  let body = METRICS.map(m => {{
    const vals = chosen.map(d => d[m.k]);
    let bestIdx = -1, worstIdx = -1;
    if (m.dir !== 0) {{
      const nums = vals.map(v => (v==null||isNaN(v))?null:v);
      const present = nums.filter(v => v!=null);
      if (present.length >= 2) {{
        let bv = m.dir>0 ? -Infinity : Infinity, wv = m.dir>0 ? Infinity : -Infinity;
        nums.forEach((v,i)=>{{ if (v==null) return;
          if (m.dir>0 ? v>bv : v<bv) {{ bv=v; bestIdx=i; }}
          if (m.dir>0 ? v<wv : v>wv) {{ wv=v; worstIdx=i; }}
        }});
        if (bv===wv) {{ bestIdx=-1; worstIdx=-1; }}  // all equal -> no winner
      }}
    }}
    const cells = vals.map((v,i)=>{{
      const cls = i===bestIdx ? 'best' : (i===worstIdx ? 'worst' : '');
      return `<td class="num ${{cls}}">${{m.fmt(v)}}</td>`;
    }}).join('');
    return `<tr><td class="metric">${{m.label}}</td>${{cells}}</tr>`;
  }}).join('');
  panel.innerHTML = `<table><thead>${{head}}</thead><tbody>${{body}}</tbody></table>`;
}}

function buildList() {{
  document.getElementById('list').innerHTML = DATA.map((d,i)=>`
    <label class="opt" data-i="${{i}}" data-txt="${{esc((d.address+' '+d.city).toLowerCase())}}">
      <input type="checkbox" onchange="toggle(${{i}},this.checked)">
      <span>${{esc(d.address)}}<br><span class="s">${{esc(d.city)}} · ${{esc(d.type)}}</span></span>
      <span class="s">${{d.score!=null?d.score.toFixed(0):'—'}}</span>
    </label>`).join('');
}}
function toggle(i, on) {{
  if (on) {{
    if (picked.length >= MAX) {{ event.target.checked = false; return; }}
    if (!picked.includes(i)) picked.push(i);
  }} else {{
    picked = picked.filter(x => x !== i);
  }}
  render();
}}
function filter() {{
  const q = document.getElementById('search').value.trim().toLowerCase();
  document.querySelectorAll('.opt').forEach(o => {{
    o.classList.toggle('dim', q !== '' && !o.dataset.txt.includes(q));
  }});
}}

buildList();
// Pre-select the top two deals so the comparison is populated on open.
if (DATA.length >= 2) {{
  picked = [0, 1];
  document.querySelectorAll('.opt input')[0].checked = true;
  document.querySelectorAll('.opt input')[1].checked = true;
}}
render();
</script>
</body>
</html>"""

    def open_in_browser(self, rows: list):
        html_str = self.render(rows)
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False,
                                          prefix="comparison_", encoding="utf-8")
        tmp.write(html_str)
        tmp.close()
        webbrowser.open(f"file://{tmp.name}")
