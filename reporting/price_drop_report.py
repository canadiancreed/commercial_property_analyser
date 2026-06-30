"""HTML report: Price Drop Alerts.

Surfaces listings whose current asking price has fallen below their original
list price — i.e. the seller has already cut the price, which is both a signal
of motivation and a marker of remaining negotiation room. The drop is measured
against original_price on file (the project does not snapshot a first-analyzed
price, so the original list is the honest available baseline).

Renders server-side, sorted by the largest percentage drop first.
"""

import html
import tempfile
import webbrowser
from datetime import datetime

# Ignore sub-0.1% noise so rounding/data jitter doesn't register as a "drop".
_DROP_EPSILON = 0.999


def _money(v):
    if not v and v != 0:
        return "—"
    return f"${v:,.0f}"


def _pct(v, decimals=2):
    if v is None:
        return "—"
    return f"{v:.{decimals}f}%"


def _cap_grade(v) -> str:
    if v is None:
        return "info"
    return "good" if v >= 7.5 else "fair" if v >= 5.5 else "poor"


def _score_grade(v) -> str:
    if v is None:
        return "info"
    return "good" if v >= 55 else "fair" if v >= 35 else "poor"


class PriceDropReportGenerator:
    """Renders the price-drop alerts report as a standalone HTML file."""

    def render(self, rows: list) -> str:
        drops = []
        for r in rows:
            original = r.get("original") or 0
            asking   = r.get("asking") or 0
            if original and asking and asking < original * _DROP_EPSILON:
                amt = original - asking
                pct = amt / original * 100
                drops.append((r, amt, pct))

        drops.sort(key=lambda rap: rap[2], reverse=True)

        body_rows = "".join(self._row_html(r, amt, pct) for r, amt, pct in drops) or (
            '<tr><td colspan="11" class="empty">'
            'No listings priced below their original list.</td></tr>'
        )

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
  td.drop {{ color: var(--green); font-weight: 500; }}
  td.good {{ color: var(--green); }}
  td.fair {{ color: var(--amber); }}
  td.poor {{ color: var(--red); }}
  .st-active {{ color: var(--green); font-weight: 500; }}
  .st-inactive {{ color: var(--muted); }}
  .empty {{ text-align: center; color: var(--muted); padding: 2rem; }}
</style>
</head>
<body>
<header>
  <h1>Price <em>Drop</em> Alerts</h1>
  <div class="header-meta">{len(drops)} listings reduced · {stamp}</div>
  <div class="note">Listings whose current asking has fallen below their original list price. The
  drop is measured against the original list price on file — a price the seller has already conceded,
  and a marker of remaining negotiation room.</div>
</header>
<div class="page-wrap">
  <table>
    <thead>
      <tr>
        <th>Address</th>
        <th>City</th>
        <th>Type</th>
        <th>Status</th>
        <th>Original Price</th>
        <th>Current Price</th>
        <th>Drop $</th>
        <th>Drop %</th>
        <th>Score</th>
        <th>Cap Rate</th>
        <th>DOM</th>
      </tr>
    </thead>
    <tbody>
{body_rows}
    </tbody>
  </table>
</div>
</body>
</html>"""

    def _row_html(self, r: dict, amt: float, pct: float) -> str:
        addr  = html.escape(r.get("address") or "—")
        city  = html.escape(r.get("city") or "—")
        ptype = html.escape(r.get("type") or "—")
        score = r.get("score")
        cap   = r.get("cap_rate")
        dom   = r.get("dom")

        status = (r.get("status") or "").strip()
        st_cls = "st-active" if status.lower() == "active" else "st-inactive"
        status_cell = (f'<span class="{st_cls}">{html.escape(status).title()}</span>'
                       if status else "—")

        dom_cell = f"{dom:g}d" if dom else "—"

        return f"""      <tr>
        <td class="addr">{addr}</td>
        <td>{city}</td>
        <td>{ptype}</td>
        <td>{status_cell}</td>
        <td class="num">{_money(r.get('original'))}</td>
        <td class="num">{_money(r.get('asking'))}</td>
        <td class="num drop">-{_money(amt)}</td>
        <td class="num drop">{_pct(pct, 1)}</td>
        <td class="num {_score_grade(score)}">{f'{score:.0f}/100' if score is not None else '—'}</td>
        <td class="num {_cap_grade(cap)}">{_pct(cap)}</td>
        <td class="num">{dom_cell}</td>
      </tr>"""

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
