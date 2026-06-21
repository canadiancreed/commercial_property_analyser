"""HTML report for realtor.ca price checks.

Mirrors the look of reporting/city_report.py (same palette and fonts) and opens
the rendered report in the browser. Each row classifies a stored property as
price same / dropped / risen / not found / could-not-check.
"""

import html
import tempfile
import webbrowser
from datetime import datetime

# status -> (label, css class). Dropped is good news for a buyer (green); a price
# rise is red; a delisting is amber; an un-checkable lookup is neutral grey.
_STATUS_META = {
    "dropped":   ("Dropped",   "s-drop"),
    "risen":     ("Risen",     "s-rise"),
    "same":      ("Unchanged", "s-same"),
    "not_found": ("Not found", "s-gone"),
    "error":     ("Not checked", "s-err"),
}

_STATUS_ORDER = ["dropped", "risen", "same", "not_found", "error"]


def _money(v):
    if v is None:
        return "—"
    # Put the minus sign before the dollar sign: -$100, not $-100.
    return f"{'-' if v < 0 else ''}${abs(v):,.0f}"


def _pct(v):
    # Two decimals so a small but real change (e.g. -0.01%) doesn't read as 0.0%.
    return "—" if v is None else f"{v:+.2f}%"


class PriceCheckReportGenerator:
    """Renders the price-check results as a standalone HTML file and opens it."""

    def render(self, rows: list) -> str:
        counts = {s: 0 for s in _STATUS_ORDER}
        for r in rows:
            counts[r.get("status", "error")] = counts.get(r.get("status", "error"), 0) + 1

        # Sort so the actionable changes (drops, then rises) surface first.
        order = {s: i for i, s in enumerate(_STATUS_ORDER)}
        rows_sorted = sorted(rows, key=lambda r: (order.get(r.get("status"), 99),
                                                  (r.get("address") or "").lower()))

        summary = "".join(
            f'<span class="pill {_STATUS_META[s][1]}">{_STATUS_META[s][0]}: {counts[s]}</span>'
            for s in _STATUS_ORDER
        )

        body_rows = "".join(self._row_html(r) for r in rows_sorted) or (
            '<tr><td colspan="8" class="empty">No properties checked.</td></tr>'
        )

        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Price Check — realtor.ca</title>
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
  .summary {{ margin-top: 1rem; display: flex; flex-wrap: wrap; gap: 0.5rem; }}
  .pill {{
    font-family: var(--mono);
    font-size: 11px;
    padding: 0.25rem 0.6rem;
    border-radius: 999px;
    border: 1px solid var(--rule);
    letter-spacing: 0.04em;
  }}
  .page-wrap {{ max-width: 1100px; margin: 0 auto; padding: 2rem 2.5rem; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--cream); }}
  th, td {{
    text-align: left;
    padding: 0.6rem 0.8rem;
    border-bottom: 1px solid var(--rule);
    vertical-align: top;
  }}
  th {{
    font-family: var(--mono);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
  }}
  td.num {{ font-family: var(--mono); text-align: right; white-space: nowrap; }}
  .addr a {{ color: var(--ink); }}
  .badge {{
    font-family: var(--mono);
    font-size: 10px;
    padding: 0.18rem 0.5rem;
    border-radius: 4px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #fff;
    white-space: nowrap;
  }}
  .s-drop {{ background: var(--green); }} .pill.s-drop {{ color: var(--green); }}
  .s-rise {{ background: var(--red);   }} .pill.s-rise {{ color: var(--red);   }}
  .s-same {{ background: var(--muted); }} .pill.s-same {{ color: var(--muted); }}
  .s-gone {{ background: var(--amber); }} .pill.s-gone {{ color: var(--amber); }}
  .s-err  {{ background: #8a8278;      }} .pill.s-err  {{ color: #8a8278;      }}
  td.delta-drop {{ color: var(--green); }}
  td.delta-rise {{ color: var(--red); }}
  .st-active {{ color: var(--green); font-weight: 500; }}
  .st-inactive {{ color: var(--muted); }}
  .empty {{ text-align: center; color: var(--muted); padding: 2rem; }}
</style>
</head>
<body>
<header>
  <h1>Price <em>Check</em></h1>
  <div class="header-meta">realtor.ca · {len(rows)} properties · {stamp}</div>
  <div class="summary">{summary}</div>
</header>
<div class="page-wrap">
  <table>
    <thead>
      <tr>
        <th>Address</th>
        <th>City</th>
        <th>State</th>
        <th style="text-align:right">Stored</th>
        <th style="text-align:right">Found</th>
        <th style="text-align:right">&Delta; $</th>
        <th style="text-align:right">&Delta; %</th>
        <th>Status</th>
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
        status = r.get("status", "error")
        label, cls = _STATUS_META.get(status, _STATUS_META["error"])

        addr = html.escape(r.get("address") or "—")
        url  = r.get("listing_url") or ""
        if url:
            addr_cell = f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{addr}</a>'
        else:
            addr_cell = addr

        loc = ", ".join(p for p in (r.get("city"), r.get("province")) if p)

        state     = (r.get("state") or "").strip()
        state_cls = "st-active" if state.lower() == "active" else "st-inactive"
        state_cell = (f'<span class="{state_cls}">{html.escape(state).title()}</span>'
                      if state else "—")

        delta     = r.get("delta")
        delta_cls = ""
        if status == "dropped":
            delta_cls = " delta-drop"
        elif status == "risen":
            delta_cls = " delta-rise"

        return f"""      <tr>
        <td class="addr">{addr_cell}</td>
        <td>{html.escape(loc) or '—'}</td>
        <td>{state_cell}</td>
        <td class="num">{_money(r.get('stored'))}</td>
        <td class="num">{_money(r.get('fetched'))}</td>
        <td class="num{delta_cls}">{_money(delta) if delta is not None else '—'}</td>
        <td class="num{delta_cls}">{_pct(r.get('delta_pct'))}</td>
        <td><span class="badge {cls}">{label}</span></td>
      </tr>"""

    def open_in_browser(self, rows: list):
        """Build the report and open it in the default browser."""
        html_str = self.render(rows)
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False,
            prefix="price_check_", encoding="utf-8"
        )
        tmp.write(html_str)
        tmp.close()
        webbrowser.open(f"file://{tmp.name}")
        print(f"\n  Price-check report opened in browser.")
        print(f"  File saved to: {tmp.name}")
