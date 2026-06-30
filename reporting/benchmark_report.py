"""HTML report: Cap-Rate & $/sqft Benchmarking.

Places every listing next to its peers and flags the over- and under-priced
ones. For each property it computes price per square foot and cap rate, then
compares both against the average of comparable properties — preferring the
tightest comp set available:

    city + type  →  province + type  →  type-wide

The property itself is excluded from its own peer average, and the basis used
is shown so the strength of each comparison is visible (a city comp is stronger
than a type-wide one). Renders server-side, most-underpriced first.
"""

import html
import tempfile
import webbrowser
from datetime import datetime

# A property is called cheap/pricey only past this gap from peers; inside it,
# it reads as "at market" rather than over-claiming signal from noise.
_MATERIAL_PCT = 10.0


def _money(v):
    if not v and v != 0:
        return "—"
    return f"${v:,.0f}"


def _pct(v, decimals=2):
    if v is None:
        return "—"
    return f"{v:.{decimals}f}%"


def _signed_pct(v, decimals=1):
    if v is None:
        return "—"
    return f"{'+' if v > 0 else ''}{v:.{decimals}f}%"


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


_VERDICT_META = {
    "under":  ("Underpriced", "good"),
    "over":   ("Overpriced",  "poor"),
    "market": ("At market",   "info"),
}
_BASIS_LABEL = {"city": "city", "province": "prov.", "type": "type"}


class BenchmarkReportGenerator:
    """Renders the cap-rate & $/sqft benchmarking report as a standalone HTML file."""

    def render(self, rows: list) -> str:
        data = benchmark_rows(rows)

        body_rows = "".join(self._row_html(e) for e in data) or (
            '<tr><td colspan="11" class="empty">'
            'No priced properties with square footage to benchmark.</td></tr>'
        )

        n_under = sum(1 for e in data if e["verdict"] == "under")
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

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
    max-width: 86ch;
    border-left: 3px solid var(--gold);
    padding-left: 0.7rem;
  }}
  .page-wrap {{ max-width: 1300px; margin: 0 auto; padding: 2rem 2.5rem; }}
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
    letter-spacing: 0.06em;
    color: var(--muted);
  }}
  th:first-child, td:first-child {{ text-align: left; white-space: normal; }}
  td.num {{ font-family: var(--mono); }}
  td.addr {{ font-weight: 500; }}
  td.good {{ color: var(--green); }}
  td.fair {{ color: var(--amber); }}
  td.poor {{ color: var(--red); }}
  td.muted {{ color: var(--muted); }}
  .basis {{ color: var(--muted); font-size: 10px; }}
  .verdict {{
    font-family: var(--mono); font-size: 10px; text-transform: uppercase;
    letter-spacing: 0.05em; padding: 0.15rem 0.5rem; border-radius: 3px;
  }}
  .verdict.good {{ background: #d4edda; color: var(--green); }}
  .verdict.poor {{ background: #f8d7da; color: var(--red); }}
  .verdict.info {{ background: var(--cream); color: var(--muted); }}
  .empty {{ text-align: center; color: var(--muted); padding: 2rem; }}
</style>
</head>
<body>
<header>
  <h1>Cap Rate &amp; <em>$/sqft</em> Benchmarking</h1>
  <div class="header-meta">{len(data)} properties · {n_under} underpriced vs peers · {stamp}</div>
  <div class="note">Each property vs the average of comparable listings — closest comp set first
  (city+type, then province+type, then type-wide; the basis is shown in the Comps column). The
  property itself is excluded from its own average. "Δ" is the gap from peers: negative $/sqft and
  positive cap are in the buyer's favour.</div>
</header>
<div class="page-wrap">
  <table>
    <thead>
      <tr>
        <th>Address</th>
        <th>City</th>
        <th>Type</th>
        <th>$/sqft</th>
        <th>Peer $/sqft</th>
        <th>Δ $/sqft</th>
        <th>Cap</th>
        <th>Peer Cap</th>
        <th>Δ Cap</th>
        <th>Comps</th>
        <th>Verdict</th>
      </tr>
    </thead>
    <tbody>
{body_rows}
    </tbody>
  </table>
</div>
</body>
</html>"""

    def _row_html(self, e: dict) -> str:
        r = e["row"]
        addr  = html.escape(r.get("address") or "—")
        city  = html.escape(r.get("city") or "—")
        ptype = html.escape(r.get("type") or "—")

        ppsf_delta = e["ppsf_delta"]
        ppsf_cls = ("good" if ppsf_delta is not None and ppsf_delta <= -_MATERIAL_PCT
                    else "poor" if ppsf_delta is not None and ppsf_delta >= _MATERIAL_PCT
                    else "")
        cap_delta = e["cap_delta"]
        cap_cls = ("good" if cap_delta is not None and cap_delta > 0
                   else "poor" if cap_delta is not None and cap_delta < 0
                   else "")

        if e["basis"]:
            comps_cell = (f'{e["comps"]} '
                          f'<span class="basis">{_BASIS_LABEL.get(e["basis"], e["basis"])}</span>')
        else:
            comps_cell = "—"

        if e["verdict"]:
            label, vcls = _VERDICT_META[e["verdict"]]
            verdict_cell = f'<span class="verdict {vcls}">{label}</span>'
        else:
            verdict_cell = '<span class="verdict info">No comps</span>'

        cap_str = _pct(e["cap"]) if e["cap"] is not None else "—"

        return f"""      <tr>
        <td class="addr">{addr}</td>
        <td>{city}</td>
        <td>{ptype}</td>
        <td class="num">{_money(round(e['ppsf']))}</td>
        <td class="num">{_money(round(e['peer_ppsf'])) if e['peer_ppsf'] is not None else '—'}</td>
        <td class="num {ppsf_cls}">{_signed_pct(ppsf_delta)}</td>
        <td class="num">{cap_str}</td>
        <td class="num">{_pct(e['peer_cap']) if e['peer_cap'] is not None else '—'}</td>
        <td class="num {cap_cls}">{_signed_pct(cap_delta, 2).replace('%', ' pts') if cap_delta is not None else '—'}</td>
        <td class="num">{comps_cell}</td>
        <td>{verdict_cell}</td>
      </tr>"""

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
