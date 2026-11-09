"""HTML report: Deal Sensitivity (rent x exit cap).

For each active, scored income deal the server pre-computes a two-way grid of
IRR across a range of market-rent assumptions (the estimated rent is the tool's
softest input) and exit cap rates (the reversion assumption). The page embeds
every deal's grid as JSON and renders client-side: pick a deal, read the grid as
a heat map. The base case — the rent as estimated, at the deal's own exit cap —
is outlined so you can see at a glance how far the return drifts when either
assumption moves against you.

A deal whose grid stays green across the band is robust; one that is green only
in its base cell is riding on assumptions. Equity multiple is shown alongside
on hover so the two returns stay tied together.
"""

import json as _json
import tempfile
import webbrowser
from datetime import datetime

# Carried per deal (grid is the matrix from analysis.metrics.sensitivity).
_FIELDS = ("address", "city", "type", "asking", "score", "base_irr",
           "base_em", "grid")


class SensitivityReportGenerator:
    """Renders the rent x exit-cap sensitivity grids as a standalone HTML file."""

    def render(self, rows: list) -> str:
        deals = [{k: r.get(k) for k in _FIELDS} for r in rows if r.get("grid")]
        # Best deals first so the default selection is the strongest candidate.
        deals.sort(key=lambda d: (d.get("score") is None, -(d.get("score") or 0)))
        data_json = _json.dumps(deals)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Deal Sensitivity</title>
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
  .controls {{ display:flex; flex-wrap:wrap; gap:1rem; align-items:flex-end; margin-top:1rem; }}
  .control-group {{ display:flex; flex-direction:column; gap:0.25rem; }}
  .control-group label {{ font-family:var(--mono); font-size:10px; text-transform:uppercase; letter-spacing:0.08em; color:var(--muted); }}
  select {{ font-family:var(--mono); font-size:13px; padding:0.35rem 0.55rem; border:1px solid var(--rule); border-radius:2px; background:var(--paper); color:var(--ink); min-width:420px; }}
  select:focus {{ outline:none; border-color:var(--gold); }}
  .page-wrap {{ max-width:1100px; margin:0 auto; padding:2rem 2.5rem; }}
  .deal-head {{ display:flex; flex-wrap:wrap; gap:1.5rem; align-items:baseline; margin-bottom:0.5rem; }}
  .deal-head .addr {{ font-family:'DM Serif Display',serif; font-size:1.5rem; }}
  .deal-head .meta {{ font-family:var(--mono); font-size:12px; color:var(--muted); }}
  .base-note {{ font-family:var(--mono); font-size:11px; color:var(--muted); margin:0.3rem 0 1.2rem; letter-spacing:0.03em; }}
  .base-note b {{ color:var(--ink); }}
  table {{ border-collapse:collapse; background:var(--cream); font-size:13px; margin-top:0.5rem; }}
  caption {{ font-family:var(--mono); font-size:10px; text-transform:uppercase; letter-spacing:0.08em; color:var(--muted); text-align:left; padding:0.4rem 0; }}
  th, td {{ padding:0.5rem 0.7rem; border:1px solid var(--rule); text-align:center; white-space:nowrap; font-family:var(--mono); }}
  th {{ font-size:10px; text-transform:uppercase; letter-spacing:0.06em; color:var(--muted); background:var(--paper); }}
  th.corner {{ background:var(--cream); }}
  td.axis, th.axis {{ color:var(--ink); background:var(--paper); font-weight:500; }}
  td.cell {{ cursor:default; }}
  td.base {{ outline:2px solid var(--ink); outline-offset:-2px; font-weight:600; }}
  /* IRR heat classes — colour by return, dark text stays legible on each. */
  .g3 {{ background:#9ccbb3; }} .g2 {{ background:#c3ddcf; }} .g1 {{ background:#dcebe3; }}
  .n0 {{ background:#f0ead9; }}
  .r1 {{ background:#f0d9cf; }} .r2 {{ background:#e6b7a6; }} .r3 {{ background:#d98f76; color:#2a0f08; }}
  .legend {{ display:flex; gap:0.5rem; align-items:center; margin:1.2rem 0 0; font-family:var(--mono); font-size:11px; color:var(--muted); flex-wrap:wrap; }}
  .legend span {{ display:inline-flex; align-items:center; gap:0.3rem; }}
  .swatch {{ width:16px; height:12px; border:1px solid var(--rule); display:inline-block; }}
  .axis-caption {{ font-family:var(--mono); font-size:11px; color:var(--muted); margin-top:0.6rem; }}
  .empty {{ text-align:center; color:var(--muted); padding:2rem; }}
</style>
</head>
<body>
<header>
  <h1>Deal <em>Sensitivity</em></h1>
  <div class="header-meta">Rent &times; exit cap &rarr; IRR · {len(deals)} scored deals · {stamp}</div>
  <div class="controls">
    <div class="control-group">
      <label>Deal</label>
      <select id="pick" onchange="render()"></select>
    </div>
  </div>
</header>
<div class="page-wrap" id="wrap"></div>

<script>
const DATA = {data_json};

function esc(s) {{ return String(s==null?'':s).replace(/[&<>"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}})[c]); }}
function fmtMoney(n) {{ return (n==null||isNaN(n))?'\\u2014':'$'+Math.round(n).toLocaleString('en-CA'); }}
function fp(n,d=1) {{ return (n==null||isNaN(n))?'n/m':n.toFixed(d)+'%'; }}

// Heat class for an IRR value (percent). Null -> not meaningful.
function heat(irr) {{
  if (irr==null || isNaN(irr)) return 'r3';
  if (irr>=15) return 'g3';
  if (irr>=10) return 'g2';
  if (irr>=6)  return 'g1';
  if (irr>=0)  return 'n0';
  if (irr>=-8) return 'r1';
  if (irr>=-16)return 'r2';
  return 'r3';
}}

const sel = document.getElementById('pick');
sel.innerHTML = DATA.map((d,i) =>
  `<option value="${{i}}">${{esc(d.address)}} — ${{esc(d.city)}} · ${{esc(d.type)}} · ${{d.score!=null?d.score.toFixed(0)+'/100':'—'}}</option>`
).join('');

function render() {{
  const wrap = document.getElementById('wrap');
  if (!DATA.length) {{ wrap.innerHTML = '<div class="empty">No scored income deals to analyse.</div>'; return; }}
  const d = DATA[parseInt(sel.value||'0',10)];
  const g = d.grid;
  const rents = g.rent_factors, caps = g.exit_caps;
  // Base case indices: rent factor nearest 1.0, exit cap nearest base_exit_cap.
  const rBase = rents.reduce((bi,v,i)=>Math.abs(v-1)<Math.abs(rents[bi]-1)?i:bi,0);
  const cBase = (g.base_exit_cap!=null)
    ? caps.reduce((bi,v,i)=>Math.abs(v-g.base_exit_cap)<Math.abs(caps[bi]-g.base_exit_cap)?i:bi,0) : -1;

  let head = '<tr><th class="corner">Rent \\ Exit cap</th>' +
    caps.map(c=>`<th class="axis">${{c.toFixed(2)}}%</th>`).join('') + '</tr>';
  let body = g.cells.map((row,ri)=>{{
    const pct = Math.round((rents[ri]-1)*100);
    const lbl = (pct>0?'+':'')+pct+'%';
    return '<tr><td class="axis">'+lbl+'</td>'+row.map((cell,ci)=>{{
      const isBase = (ri===rBase && ci===cBase);
      const title = `IRR ${{fp(cell.irr,2)}} · EM ${{cell.em!=null?cell.em.toFixed(2)+'x':'n/m'}} · entry cap ${{fp(cell.entry_cap,2)}}`;
      return `<td class="cell ${{heat(cell.irr)}} ${{isBase?'base':''}}" title="${{title}}">${{fp(cell.irr,1)}}</td>`;
    }}).join('')+'</tr>';
  }}).join('');

  wrap.innerHTML = `
    <div class="deal-head">
      <span class="addr">${{esc(d.address)}}</span>
      <span class="meta">${{esc(d.city)}} · ${{esc(d.type)}} · ${{fmtMoney(d.asking)}} · score ${{d.score!=null?d.score.toFixed(0)+'/100':'—'}}</span>
    </div>
    <div class="base-note">Base case: rent as estimated at a <b>${{d.grid.base_exit_cap!=null?d.grid.base_exit_cap.toFixed(2)+'%':'—'}}</b> exit cap &rarr; IRR <b>${{fp(d.base_irr,2)}}</b>, EM <b>${{d.base_em!=null?d.base_em.toFixed(2)+'x':'—'}}</b> (outlined cell).</div>
    <table>
      <caption>Internal rate of return at each rent &times; exit-cap combination</caption>
      ${{head}}${{body}}
    </table>
    <div class="axis-caption">Rows: market rent vs. the estimate. Columns: exit cap rate at sale (wider = lower sale price). Hover a cell for EM and entry cap.</div>
    <div class="legend">
      <span><span class="swatch g3"></span>≥15%</span>
      <span><span class="swatch g2"></span>10–15%</span>
      <span><span class="swatch g1"></span>6–10%</span>
      <span><span class="swatch n0"></span>0–6%</span>
      <span><span class="swatch r1"></span>negative</span>
      <span><span class="swatch r3"></span>deeply negative / not meaningful</span>
    </div>`;
}}
render();
</script>
</body>
</html>"""

    def open_in_browser(self, rows: list):
        html_str = self.render(rows)
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False,
                                          prefix="sensitivity_", encoding="utf-8")
        tmp.write(html_str)
        tmp.close()
        webbrowser.open(f"file://{tmp.name}")
