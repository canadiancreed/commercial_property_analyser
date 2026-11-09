"""HTML report: Cash-Flow Proforma (the DCF behind the IRR).

The headline IRR and equity multiple come from a year-by-year cash-flow array —
equity invested at close, operating cash flow each year (NOI escalated at the
growth assumption, debt service flat), and the net sale proceeds in the final
year. This report lays that array out as a table so the return is auditable:
pick a deal, read every year's NOI, debt service, operating cash flow,
reversion, net cash flow and running cumulative, with the IRR / EM / equity
restated in the header.
"""

import json as _json
import tempfile
import webbrowser
from datetime import datetime

_FIELDS = ("address", "city", "type", "asking", "score", "irr", "em",
           "equity", "exit_price", "net_sale", "growth", "hold", "schedule")


class ProformaReportGenerator:
    """Renders the per-deal cash-flow proforma as a standalone HTML file."""

    def render(self, rows: list) -> str:
        deals = [{k: r.get(k) for k in _FIELDS} for r in rows if r.get("schedule")]
        deals.sort(key=lambda d: (d.get("score") is None, -(d.get("score") or 0)))
        data_json = _json.dumps(deals)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cash-Flow Proforma</title>
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
  .page-wrap {{ max-width:1050px; margin:0 auto; padding:2rem 2.5rem; }}
  .deal-head {{ font-family:'DM Serif Display',serif; font-size:1.5rem; margin-bottom:0.2rem; }}
  .deal-meta {{ font-family:var(--mono); font-size:12px; color:var(--muted); margin-bottom:1rem; }}
  .kpis {{ display:flex; flex-wrap:wrap; gap:1.8rem; margin:0.5rem 0 1.4rem; padding:0.9rem 1.1rem; background:var(--cream); border:1px solid var(--rule); border-radius:3px; }}
  .kpi {{ display:flex; flex-direction:column; }}
  .kpi .k {{ font-family:var(--mono); font-size:10px; text-transform:uppercase; letter-spacing:0.07em; color:var(--muted); }}
  .kpi .v {{ font-family:var(--mono); font-size:16px; font-weight:500; }}
  table {{ width:100%; border-collapse:collapse; background:var(--cream); font-size:13px; }}
  th, td {{ padding:0.5rem 0.7rem; border-bottom:1px solid var(--rule); text-align:right; white-space:nowrap; font-family:var(--mono); }}
  th {{ font-size:10px; text-transform:uppercase; letter-spacing:0.06em; color:var(--muted); background:var(--paper); }}
  th:first-child, td:first-child {{ text-align:left; }}
  tr.close td {{ color:var(--muted); font-style:italic; }}
  tr.exit td {{ border-top:2px solid var(--rule); font-weight:600; }}
  td.pos {{ color:var(--green); }}
  td.neg {{ color:var(--red); }}
  .note {{ font-family:var(--mono); font-size:11px; color:var(--muted); margin-top:0.7rem; }}
  .empty {{ text-align:center; color:var(--muted); padding:2rem; }}
</style>
</head>
<body>
<header>
  <h1>Cash-Flow <em>Proforma</em></h1>
  <div class="header-meta">The DCF behind the IRR · {len(deals)} scored deals · {stamp}</div>
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
function money(n) {{ if (n==null||isNaN(n)) return '\\u2014'; return (n<0?'-':'')+'$'+Math.abs(Math.round(n)).toLocaleString('en-CA'); }}
function fp(n,d=2) {{ return (n==null||isNaN(n))?'n/m':n.toFixed(d)+'%'; }}
function signCls(n) {{ return n==null?'':(n>0?'pos':(n<0?'neg':'')); }}

const sel = document.getElementById('pick');
sel.innerHTML = DATA.map((d,i) =>
  `<option value="${{i}}">${{esc(d.address)}} — ${{esc(d.city)}} · ${{esc(d.type)}} · ${{d.score!=null?d.score.toFixed(0)+'/100':'—'}}</option>`
).join('');

function render() {{
  const wrap = document.getElementById('wrap');
  if (!DATA.length) {{ wrap.innerHTML = '<div class="empty">No scored income deals with a cash-flow basis.</div>'; return; }}
  const d = DATA[parseInt(sel.value||'0',10)];
  const rows = d.schedule.rows;
  const N = rows.length - 1;

  const body = rows.map(r => {{
    if (r.year === 0) {{
      return `<tr class="close">
        <td>Close</td><td>\\u2014</td><td>\\u2014</td><td>\\u2014</td><td>\\u2014</td>
        <td class="neg">${{money(r.net_cf)}}</td><td class="neg">${{money(r.cumulative)}}</td></tr>`;
    }}
    const isExit = (r.year === N);
    return `<tr class="${{isExit?'exit':''}}">
      <td>Year ${{r.year}}</td>
      <td>${{money(r.noi)}}</td>
      <td>${{money(-r.debt_service)}}</td>
      <td class="${{signCls(r.operating_cf)}}">${{money(r.operating_cf)}}</td>
      <td>${{r.reversion!=null?money(r.reversion):'\\u2014'}}</td>
      <td class="${{signCls(r.net_cf)}}">${{money(r.net_cf)}}</td>
      <td class="${{signCls(r.cumulative)}}">${{money(r.cumulative)}}</td></tr>`;
  }}).join('');

  wrap.innerHTML = `
    <div class="deal-head">${{esc(d.address)}}</div>
    <div class="deal-meta">${{esc(d.city)}} · ${{esc(d.type)}} · asking ${{money(d.asking)}} · score ${{d.score!=null?d.score.toFixed(0)+'/100':'—'}}</div>
    <div class="kpis">
      <div class="kpi"><span class="k">IRR (${{N}}-yr)</span><span class="v">${{fp(d.irr)}}</span></div>
      <div class="kpi"><span class="k">Equity Multiple</span><span class="v">${{d.em!=null?d.em.toFixed(2)+'x':'\\u2014'}}</span></div>
      <div class="kpi"><span class="k">Equity Invested</span><span class="v">${{money(d.equity)}}</span></div>
      <div class="kpi"><span class="k">NOI Growth</span><span class="v">${{fp(d.growth*100,2)}}/yr</span></div>
      <div class="kpi"><span class="k">Exit Price</span><span class="v">${{money(d.exit_price)}}</span></div>
      <div class="kpi"><span class="k">Net Sale Proceeds</span><span class="v">${{money(d.net_sale)}}</span></div>
    </div>
    <table>
      <thead><tr>
        <th>Period</th><th>NOI</th><th>Debt Service</th><th>Operating CF</th>
        <th>Reversion</th><th>Net CF</th><th>Cumulative</th>
      </tr></thead>
      <tbody>${{body}}</tbody>
    </table>
    <div class="note">Operating CF = NOI (escalated at the growth assumption) − debt service. The final year adds net sale proceeds (exit price − loan payoff). Net CF is the array the IRR and equity multiple are computed from.</div>`;
}}
render();
</script>
</body>
</html>"""

    def open_in_browser(self, rows: list):
        html_str = self.render(rows)
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False,
                                          prefix="proforma_", encoding="utf-8")
        tmp.write(html_str)
        tmp.close()
        webbrowser.open(f"file://{tmp.name}")
