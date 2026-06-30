"""HTML report: Negotiation Targets (bid anchors).

For each active, scored property, the scorer's target solver finds the single
lever value that — changed on its own — would lift the deal to a perfect score:
the price to negotiate down to, the rent it would need, a refinance rate, or a
larger down payment. This report lays those anchors out in a table so they can
be taken into a negotiation.

Mirrors the look of reporting/price_check_report.py and renders server-side,
sorted best-score first.
"""

import html
import tempfile
import webbrowser
from datetime import datetime


def _money(v):
    if not v and v != 0:
        return "—"
    return f"${v:,.0f}"


def _pct(v, decimals=2):
    if v is None:
        return "—"
    return f"{v:.{decimals}f}%"


def _grade(metric: str, v) -> str:
    if v is None:
        return "info"
    if metric == "cap_rate": return "good" if v >= 7.5 else "fair" if v >= 5.5 else "poor"
    if metric == "score":    return "good" if v >= 55 else "fair" if v >= 35 else "poor"
    return "info"


def _delta_cell(asking, target) -> str:
    """The signed % gap from today's asking to the target price. A target below
    asking (room to negotiate down) is good news; above asking is not."""
    if not asking or not target:
        return ""
    d = (target - asking) / asking * 100
    cls = "good" if d < 0 else "poor"
    return (f' <span class="{cls}" style="font-size:11px">'
            f'({"+" if d > 0 else ""}{d:.1f}%)</span>')


class NegotiationReportGenerator:
    """Renders the negotiation-targets report as a standalone HTML file."""

    def render(self, rows: list) -> str:
        # Active, scored deals only — targets are only actionable on live listings.
        deals = [r for r in rows
                 if r.get("score") is not None
                 and (r.get("status") or "").strip().lower() == "active"]
        deals.sort(key=lambda r: r["score"], reverse=True)

        body_rows = "".join(self._row_html(r) for r in deals) or (
            '<tr><td colspan="10" class="empty">'
            'No active, scored properties to negotiate.</td></tr>'
        )

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
    max-width: 70ch;
    border-left: 3px solid var(--gold);
    padding-left: 0.7rem;
  }}
  .page-wrap {{ max-width: 1200px; margin: 0 auto; padding: 2rem 2.5rem; }}
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
  }}
  th:first-child, td:first-child {{ text-align: left; white-space: normal; }}
  td.num {{ font-family: var(--mono); }}
  td.addr {{ font-weight: 500; }}
  td.good {{ color: var(--green); }}
  td.fair {{ color: var(--amber); }}
  td.poor {{ color: var(--red); }}
  span.good {{ color: var(--green); }}
  span.poor {{ color: var(--red); }}
  td.optimal {{ color: var(--green); text-align: center; }}
  .st-active {{ color: var(--green); font-weight: 500; }}
  .empty {{ text-align: center; color: var(--muted); padding: 2rem; }}
</style>
</head>
<body>
<header>
  <h1>Negotiation <em>Targets</em></h1>
  <div class="header-meta">{len(deals)} active deals · {stamp}</div>
  <div class="note">Each target is the single lever value that alone would lift the deal to a
  perfect score — the price to negotiate down to, the rent it would need, a refinance rate, or a
  larger down payment. The % beside Target Price is the gap from today's asking.</div>
</header>
<div class="page-wrap">
  <table>
    <thead>
      <tr>
        <th>Address</th>
        <th>City</th>
        <th>Type</th>
        <th>Asking</th>
        <th>Score</th>
        <th>Cap Rate</th>
        <th>Target Price</th>
        <th>Target Rent/yr</th>
        <th>Target Rate</th>
        <th>Target Down%</th>
      </tr>
    </thead>
    <tbody>
{body_rows}
    </tbody>
  </table>
</div>
</body>
</html>"""

    def _row_html(self, r: dict) -> str:
        addr  = html.escape(r.get("address") or "—")
        city  = html.escape(r.get("city") or "—")
        ptype = html.escape(r.get("type") or "—")
        score = r.get("score")
        cap   = r.get("cap_rate")
        asking = r.get("asking")

        t = r.get("targets") or {}
        t_price = t.get("price")
        t_rent  = t.get("rent")
        t_rate  = t.get("rate")
        t_down  = t.get("down_pct")

        if not any(v is not None for v in (t_price, t_rent, t_rate, t_down)):
            target_cells = ('<td class="optimal" colspan="4">'
                            'All negotiable levers already optimal</td>')
        else:
            rent_cell = f"{_money(t_rent)}/yr" if t_rent is not None else "—"
            rate_cell = f"{t_rate * 100:.2f}%" if t_rate is not None else "—"
            down_cell = f"{t_down * 100:.1f}%" if t_down is not None else "—"
            price_cell = (_money(t_price) + _delta_cell(asking, t_price)
                          if t_price is not None else "—")
            target_cells = (
                f'<td class="num">{price_cell}</td>'
                f'<td class="num">{rent_cell}</td>'
                f'<td class="num">{rate_cell}</td>'
                f'<td class="num">{down_cell}</td>'
            )

        return f"""      <tr>
        <td class="addr">{addr}</td>
        <td>{city}</td>
        <td>{ptype}</td>
        <td class="num">{_money(asking)}</td>
        <td class="num {_grade('score', score)}">{f'{score:.0f}/100' if score is not None else '—'}</td>
        <td class="num {_grade('cap_rate', cap)}">{_pct(cap)}</td>
        {target_cells}
      </tr>"""

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
