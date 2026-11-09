"""HTML report: Pipeline Summary.

Every other report is per-deal or per-city; this one steps back and reads the
whole pipeline of deals under consideration at once — how much capital it would
take, how the quality is distributed, and where the exposure is concentrated by
asset type and geography. It answers "across everything I'm looking at, is the
book any good, and am I over-weighted anywhere?" for a buyer screening many
listings rather than underwriting one.

Only active, scored deals count — the pipeline is what you could still act on.
Quality bands reuse the app's named grades (Excellent >=75, Good >=55,
Fair >=35, Weak below).
"""

import json as _json
import tempfile
import webbrowser
from datetime import datetime

# Named score bands, matching the opportunity grades used elsewhere in the app.
_BANDS = [("Excellent", 75), ("Good", 55), ("Fair", 35), ("Weak", 0)]


def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    mid = n // 2
    return xs[mid] if n % 2 else (xs[mid - 1] + xs[mid]) / 2.0


def _band(score):
    for label, lo in _BANDS:
        if score >= lo:
            return label
    return "Weak"


class PipelineReportGenerator:
    """Renders the pipeline-level quality + concentration summary."""

    @staticmethod
    def summarize(rows: list) -> dict:
        """Aggregate the active, scored deals into pipeline-level figures. Pure
        function of the rows so it is unit-testable without the UI."""
        deals = [r for r in rows
                 if r.get("score") is not None
                 and (r.get("status") or "").strip().lower() == "active"]
        n = len(deals)
        total_value = sum(r.get("asking") or 0 for r in deals)
        scores = [r.get("score") for r in deals]

        band_counts = {label: 0 for label, _ in _BANDS}
        for r in deals:
            band_counts[_band(r.get("score") or 0)] += 1
        score_bands = [{"label": label, "count": band_counts[label],
                        "pct": (band_counts[label] / n * 100.0) if n else 0.0}
                       for label, _ in _BANDS]

        def _group(key):
            g = {}
            for r in deals:
                name = (r.get(key) or "—").strip() or "—"
                e = g.setdefault(name, {"name": name, "count": 0, "value": 0.0,
                                        "_scores": []})
                e["count"] += 1
                e["value"] += r.get("asking") or 0
                if r.get("score") is not None:
                    e["_scores"].append(r["score"])
            out = []
            for e in g.values():
                out.append({
                    "name": e["name"], "count": e["count"], "value": e["value"],
                    "value_pct": (e["value"] / total_value * 100.0) if total_value else 0.0,
                    "avg_score": (sum(e["_scores"]) / len(e["_scores"]))
                                 if e["_scores"] else None,
                })
            out.sort(key=lambda x: (-x["value"], -x["count"]))
            return out

        good_plus = sum(1 for r in deals if (r.get("score") or 0) >= 55)
        cf_pos = sum(1 for r in deals if (r.get("cf_annual") or 0) > 0)

        return {
            "count": n,
            "total_value": total_value,
            "median_score": _median(scores),
            "pct_good_plus": (good_plus / n * 100.0) if n else 0.0,
            "median_cap": _median([r.get("cap_rate") for r in deals]),
            "median_irr": _median([r.get("irr") for r in deals]),
            "pct_cf_positive": (cf_pos / n * 100.0) if n else 0.0,
            "score_bands": score_bands,
            "by_type": _group("type"),
            "by_province": _group("province"),
            "by_city": _group("city")[:12],
        }

    def render(self, rows: list) -> str:
        s = self.summarize(rows)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        def money(v):
            return "—" if v is None else f"${round(v):,}"

        def pct(v, d=1):
            return "—" if v is None else f"{v:.{d}f}%"

        def num(v, d=2):
            return "—" if v is None else f"{v:.{d}f}"

        # KPI tiles.
        kpis = [
            ("Active deals", f"{s['count']:,}"),
            ("Pipeline value", money(s["total_value"])),
            ("Median score", f"{num(s['median_score'], 0)}/100" if s["median_score"] is not None else "—"),
            ("Scoring Good+", pct(s["pct_good_plus"], 0)),
            ("Median cap rate", pct(s["median_cap"], 2)),
            ("Median IRR", pct(s["median_irr"], 2)),
            ("Cash-flow positive", pct(s["pct_cf_positive"], 0)),
        ]
        kpi_html = "".join(
            f'<div class="kpi"><span class="k">{k}</span><span class="v">{v}</span></div>'
            for k, v in kpis)

        # Quality distribution bar.
        band_cls = {"Excellent": "b-exc", "Good": "b-good", "Fair": "b-fair", "Weak": "b-weak"}
        bar = "".join(
            f'<div class="seg {band_cls[b["label"]]}" style="width:{b["pct"]:.2f}%" '
            f'title="{b["label"]}: {b["count"]} ({b["pct"]:.0f}%)"></div>'
            for b in s["score_bands"] if b["pct"] > 0)
        legend = "".join(
            f'<span><span class="sw {band_cls[b["label"]]}"></span>{b["label"]} '
            f'{b["count"]} ({b["pct"]:.0f}%)</span>'
            for b in s["score_bands"])

        def conc_table(title, items, name_hdr):
            body = "".join(
                f"<tr><td class='nm'>{self._esc(it['name'])}</td>"
                f"<td class='num'>{it['count']}</td>"
                f"<td class='num'>{money(it['value'])}</td>"
                f"<td class='num'>{it['value_pct']:.1f}%</td>"
                f"<td class='num'>{num(it['avg_score'], 0) if it['avg_score'] is not None else '—'}</td></tr>"
                for it in items) or "<tr><td colspan='5' class='empty'>No deals.</td></tr>"
            return f"""
    <section>
      <h2>{title}</h2>
      <table>
        <thead><tr><th class="nm">{name_hdr}</th><th>Deals</th><th>Pipeline $</th><th>Share</th><th>Avg score</th></tr></thead>
        <tbody>{body}</tbody>
      </table>
    </section>"""

        type_tbl = conc_table("Concentration by asset type", s["by_type"], "Type")
        prov_tbl = conc_table("Concentration by province", s["by_province"], "Province")
        city_tbl = conc_table("Top cities by pipeline value", s["by_city"], "City")

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pipeline Summary</title>
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
  .page-wrap {{ max-width:1050px; margin:0 auto; padding:2rem 2.5rem; }}
  .kpis {{ display:flex; flex-wrap:wrap; gap:1.3rem 2.2rem; padding:1rem 1.2rem; background:var(--cream); border:1px solid var(--rule); border-radius:3px; }}
  .kpi {{ display:flex; flex-direction:column; }}
  .kpi .k {{ font-family:var(--mono); font-size:10px; text-transform:uppercase; letter-spacing:0.07em; color:var(--muted); }}
  .kpi .v {{ font-family:var(--mono); font-size:18px; font-weight:500; }}
  h2 {{ font-family:var(--mono); font-size:11px; text-transform:uppercase; letter-spacing:0.08em; color:var(--muted); margin:2rem 0 0.6rem; }}
  .bar {{ display:flex; height:28px; border:1px solid var(--rule); border-radius:3px; overflow:hidden; background:var(--cream); }}
  .seg {{ height:100%; }}
  .b-exc {{ background:#2d6a4f; }} .b-good {{ background:#74a892; }} .b-fair {{ background:#d9b46a; }} .b-weak {{ background:#c99; }}
  .legend {{ display:flex; gap:1.2rem; flex-wrap:wrap; margin-top:0.6rem; font-family:var(--mono); font-size:11px; color:var(--muted); }}
  .legend span {{ display:inline-flex; align-items:center; gap:0.35rem; }}
  .sw {{ width:14px; height:12px; display:inline-block; border:1px solid var(--rule); }}
  table {{ width:100%; border-collapse:collapse; background:var(--cream); font-size:13px; }}
  th, td {{ padding:0.5rem 0.8rem; border-bottom:1px solid var(--rule); text-align:right; white-space:nowrap; font-family:var(--mono); }}
  th {{ font-size:10px; text-transform:uppercase; letter-spacing:0.06em; color:var(--muted); background:var(--paper); }}
  th.nm, td.nm {{ text-align:left; }}
  td.nm {{ font-family:'DM Sans',sans-serif; font-weight:500; }}
  .empty {{ text-align:center; color:var(--muted); }}
</style>
</head>
<body>
<header>
  <h1>Pipeline <em>Summary</em></h1>
  <div class="header-meta">Quality &amp; concentration across the deals you're considering · {stamp}</div>
</header>
<div class="page-wrap">
  <div class="kpis">{kpi_html}</div>

  <h2>Quality distribution (by score band)</h2>
  <div class="bar">{bar}</div>
  <div class="legend">{legend}</div>
  {type_tbl}
  {prov_tbl}
  {city_tbl}
</div>
</body>
</html>"""

    @staticmethod
    def _esc(s):
        return (str(s).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))

    def open_in_browser(self, rows: list):
        html_str = self.render(rows)
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False,
                                          prefix="pipeline_", encoding="utf-8")
        tmp.write(html_str)
        tmp.close()
        webbrowser.open(f"file://{tmp.name}")
