"""HTML report: the Deal Watchlist.

A focused table of scored properties at or above a score threshold, surfacing
the return metrics that matter for a buy decision (cap rate, cash-on-cash, IRR,
annual cash flow, DSCR) alongside days-on-market and any reduction from list.

Mirrors the look of reporting/price_check_report.py (same palette and fonts) and
renders the rows server-side, sorted best-score first.
"""

import html
import tempfile
import webbrowser
from datetime import datetime

DEFAULT_MIN_SCORE = 55


def _money(v):
    if not v and v != 0:
        return "—"
    return f"${v:,.0f}"


def _money_signed(v):
    if v is None:
        return "—"
    return f"{'-' if v < 0 else ''}${abs(v):,.0f}"


def _pct(v, decimals=2):
    if v is None:
        return "—"
    return f"{v:.{decimals}f}%"


def _grade(metric: str, v) -> str:
    """Return a css grade class (good/fair/poor) for a metric value, matching the
    thresholds used in the investment report's metric chips."""
    if v is None:
        return "info"
    if metric == "cap_rate":  return "good" if v >= 7.5 else "fair" if v >= 5.5 else "poor"
    if metric == "coc":       return "good" if v >= 10  else "fair" if v >= 5   else "poor"
    if metric == "irr":       return "good" if v >= 15  else "fair" if v >= 10  else "poor"
    if metric == "dscr":      return "good" if v >= 1.5 else "fair" if v >= 1.25 else "poor"
    if metric == "cf_annual": return "poor" if v <= 0 else "good" if v >= 10000 else "fair"
    if metric == "score":     return "good" if v >= 55 else "fair" if v >= 35 else "poor"
    return "info"


class DealWatchlistReportGenerator:
    """Renders the deal watchlist as a standalone HTML file and opens it."""

    def render(self, rows: list, min_score: float = DEFAULT_MIN_SCORE) -> str:
        # Only scored deals at or above the threshold; best score first.
        watch = [r for r in rows
                 if r.get("score") is not None and r["score"] >= min_score]
        watch.sort(key=lambda r: r["score"], reverse=True)

        body_rows = "".join(self._row_html(r) for r in watch) or (
            f'<tr><td colspan="13" class="empty">'
            f'No scored properties at or above {min_score:g}.</td></tr>'
        )

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
  .page-wrap {{ max-width: 1250px; margin: 0 auto; padding: 2rem 2.5rem; }}
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
  .st-active {{ color: var(--green); font-weight: 500; }}
  .st-inactive {{ color: var(--muted); }}
  .empty {{ text-align: center; color: var(--muted); padding: 2rem; }}
</style>
</head>
<body>
<header>
  <h1>Deal <em>Watchlist</em></h1>
  <div class="header-meta">{len(watch)} deals · score &ge; {min_score:g} · {stamp}</div>
</header>
<div class="page-wrap">
  <table>
    <thead>
      <tr>
        <th>Address</th>
        <th>City</th>
        <th>Type</th>
        <th>Status</th>
        <th>Price</th>
        <th>Score</th>
        <th>Cap Rate</th>
        <th>CoCR</th>
        <th>IRR</th>
        <th>Annual CF</th>
        <th>DSCR</th>
        <th>DOM</th>
        <th>Price Drop</th>
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
        addr = html.escape(r.get("address") or "—")
        city = html.escape(r.get("city") or "—")
        ptype = html.escape(r.get("type") or "—")

        status = (r.get("status") or "").strip()
        st_cls = "st-active" if status.lower() == "active" else "st-inactive"
        status_cell = (f'<span class="{st_cls}">{html.escape(status).title()}</span>'
                       if status else "—")

        score = r.get("score")
        cap   = r.get("cap_rate")
        coc   = r.get("coc")
        irr   = r.get("irr")
        cf    = r.get("cf_annual")
        dscr  = r.get("dscr")
        dom   = r.get("dom")
        drop  = r.get("price_drop")

        dom_cell  = f"{dom:g}d" if dom else "—"
        drop_cell = _pct(drop, 1) if drop and drop > 0 else "—"
        drop_cls  = "good" if drop and drop > 0 else ""

        return f"""      <tr>
        <td class="addr">{addr}</td>
        <td>{city}</td>
        <td>{ptype}</td>
        <td>{status_cell}</td>
        <td class="num">{_money(r.get('asking'))}</td>
        <td class="num {_grade('score', score)}">{f'{score:.0f}/100' if score is not None else '—'}</td>
        <td class="num {_grade('cap_rate', cap)}">{_pct(cap)}</td>
        <td class="num {_grade('coc', coc)}">{_pct(coc)}</td>
        <td class="num {_grade('irr', irr)}">{_pct(irr)}</td>
        <td class="num {_grade('cf_annual', cf)}">{_money_signed(cf)}</td>
        <td class="num {_grade('dscr', dscr)}">{f'{dscr:.2f}' if dscr is not None else '—'}</td>
        <td class="num">{dom_cell}</td>
        <td class="num {drop_cls}">{drop_cell}</td>
      </tr>"""

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
