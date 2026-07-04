import json as _json
import tempfile
import webbrowser
from analysis.metrics.returns import METRIC_MARKET_STALENESS


class PropertyReportGenerator:
    """
    Renders the property investment report as a standalone HTML file.

    Accepts the enriched rows list produced by the UI layer (each row is a dict
    with scoring, metrics, and property metadata) plus an optional pre-built city
    rankings panel HTML string.
    """

    def render(self, rows: list, city_table_html: str = "") -> str:
        data_json = _json.dumps(rows, indent=2)

        cities    = sorted({r["city"]     for r in rows if r.get("city")})
        provinces = sorted({r["province"] for r in rows if r.get("province")})
        types     = sorted({r["type"]     for r in rows if r.get("type") and r["type"] != "—"})

        province_opts = "".join(f'<option value="{p}">{p}</option>' for p in provinces)
        city_opts     = "".join(f'<option value="{c}">{c}</option>' for c in cities)
        type_opts     = "".join(f'<option value="{t}">{t}</option>' for t in types)

        staleness_key = METRIC_MARKET_STALENESS

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Property Investment Report</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --ink:     #0f0f0f;
    --paper:   #f5f0e8;
    --cream:   #ede8dc;
    --rule:    #c8bfaa;
    --gold:    #b8960c;
    --green:   #2d6a4f;
    --red:     #8b1a1a;
    --amber:   #c17f24;
    --muted:   #6b6355;
    --col-w:   1200px;
    --mono:    'DM Mono', monospace;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--paper);
    color: var(--ink);
    font-family: 'DM Sans', sans-serif;
    font-size: 14px;
    line-height: 1.5;
    min-height: 100vh;
  }}
  header {{
    border-bottom: 3px double var(--rule);
    padding: 2rem 2.5rem 1.5rem;
    background: var(--cream);
  }}
  header h1 {{
    font-family: 'DM Serif Display', serif;
    font-size: 2.6rem;
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
  .filters {{
    background: var(--cream);
    border-bottom: 1px solid var(--rule);
    padding: 1rem 2.5rem;
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
    align-items: flex-end;
  }}
  .filter-group {{
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }}
  .filter-group label {{
    font-family: var(--mono);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--muted);
  }}
  .filter-group select,
  .filter-group input {{
    background: var(--paper);
    border: 1px solid var(--rule);
    padding: 0.4rem 0.6rem;
    font-family: 'DM Sans', sans-serif;
    font-size: 13px;
    color: var(--ink);
    border-radius: 2px;
    min-width: 140px;
    appearance: none;
    -webkit-appearance: none;
  }}
  .filter-group select:focus,
  .filter-group input:focus {{ outline: 2px solid var(--gold); outline-offset: -1px; }}
  .filter-group.range-group {{ flex-direction: row; align-items: flex-end; gap: 0.4rem; }}
  .filter-group.range-group label {{ align-self: flex-start; }}
  .range-inputs {{ display: flex; gap: 0.4rem; align-items: center; }}
  .range-inputs span {{ color: var(--muted); font-size: 12px; }}
  .filter-group input[type=number] {{ min-width: 100px; }}
  .filter-actions {{
    display: flex;
    align-items: flex-end;
    gap: 0.5rem;
    margin-left: auto;
  }}
  button {{
    background: var(--ink);
    color: var(--paper);
    border: none;
    padding: 0.45rem 1.1rem;
    font-family: var(--mono);
    font-size: 11px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    cursor: pointer;
    border-radius: 2px;
    transition: background 0.15s;
  }}
  button:hover {{ background: #333; }}
  button.ghost {{
    background: transparent;
    color: var(--muted);
    border: 1px solid var(--rule);
  }}
  button.ghost:hover {{ border-color: var(--ink); color: var(--ink); }}
  .summary-strip {{
    padding: 0.6rem 2.5rem;
    border-bottom: 1px solid var(--rule);
    font-family: var(--mono);
    font-size: 11px;
    color: var(--muted);
    display: flex;
    justify-content: space-between;
    align-items: center;
    letter-spacing: 0.05em;
  }}
  .sort-controls {{ display: flex; gap: 0.5rem; align-items: center; }}
  .sort-btn {{
    background: none;
    border: none;
    color: var(--muted);
    font-family: var(--mono);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    cursor: pointer;
    padding: 0.2rem 0.5rem;
    border-radius: 2px;
    transition: all 0.1s;
  }}
  .sort-btn:hover {{ background: var(--cream); color: var(--ink); }}
  .sort-btn.active {{ background: var(--ink); color: var(--paper); }}
  main {{ padding: 1.5rem 2.5rem 3rem; max-width: var(--col-w); }}
  #cards {{ display: flex; flex-direction: column; gap: 1.2rem; }}
  .card {{
    background: white;
    border: 1px solid var(--rule);
    border-left: 4px solid var(--rule);
    display: grid;
    grid-template-columns: 220px 1fr auto;
    transition: border-color 0.15s, box-shadow 0.15s;
    cursor: pointer;
  }}
  .card:hover {{ border-color: var(--gold); box-shadow: 4px 4px 0 var(--gold); }}
  .card.score-excellent {{ border-left-color: var(--green); }}
  .card.score-good      {{ border-left-color: #4a9e72; }}
  .card.score-fair      {{ border-left-color: var(--amber); }}
  .card.score-poor      {{ border-left-color: var(--red); }}
  .card.score-none      {{ border-left-color: var(--rule); opacity: 0.75; }}
  .card-score {{
    background: var(--cream);
    border-right: 1px solid var(--rule);
    padding: 1.2rem 1rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    gap: 0.4rem;
  }}
  .score-num {{
    font-family: 'DM Serif Display', serif;
    font-size: 3rem;
    line-height: 1;
    color: var(--ink);
  }}
  .score-num.no-score {{
    font-size: 1.2rem;
    color: var(--muted);
    font-family: var(--mono);
  }}
  .score-label {{
    font-family: var(--mono);
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--muted);
  }}
  .score-grade {{
    font-family: var(--mono);
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    padding: 0.15rem 0.5rem;
    border-radius: 1px;
  }}
  .score-grade.excellent {{ background: #d4edda; color: var(--green); }}
  .score-grade.good      {{ background: #d9eedf; color: #2d6a4f; }}
  .score-grade.fair      {{ background: #fef3cd; color: var(--amber); }}
  .score-grade.poor      {{ background: #f8d7da; color: var(--red); }}
  .score-grade.none      {{ background: var(--cream); color: var(--muted); }}
  .card-body {{ padding: 1rem 1.2rem; }}
  .card-address {{
    font-family: 'DM Serif Display', serif;
    font-size: 1.1rem;
    margin-bottom: 0.2rem;
  }}
  .card-meta {{
    font-family: var(--mono);
    font-size: 10px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.07em;
    margin-bottom: 0.75rem;
    display: flex;
    gap: 0.8rem;
    flex-wrap: wrap;
  }}
  .card-meta .pill {{
    background: var(--cream);
    padding: 0.1rem 0.4rem;
    border-radius: 1px;
    border: 1px solid var(--rule);
  }}
  .metrics-row {{ display: flex; gap: 1.2rem; flex-wrap: wrap; margin-top: 0.3rem; }}
  .metric-chip {{ display: flex; flex-direction: column; gap: 0.1rem; }}
  .metric-chip .m-label {{
    font-family: var(--mono);
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--muted);
  }}
  .metric-chip .m-value {{
    font-family: var(--mono);
    font-size: 13px;
    font-weight: 500;
  }}
  .metric-chip .m-value.good {{ color: var(--green); }}
  .metric-chip .m-value.fair {{ color: var(--amber); }}
  .metric-chip .m-value.poor {{ color: var(--red); }}
  .metric-chip .m-value.info {{ color: var(--ink); }}
  .card-right {{
    padding: 1rem 1.2rem;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    justify-content: space-between;
    min-width: 160px;
    border-left: 1px solid var(--rule);
  }}
  .asking-price {{ font-family: 'DM Serif Display', serif; font-size: 1.4rem; text-align: right; }}
  .price-meta {{ font-family: var(--mono); font-size: 10px; color: var(--muted); text-align: right; margin-top: 0.15rem; }}
  .card-notes {{
    font-size: 11px;
    color: var(--muted);
    font-style: italic;
    max-width: 120px;
    text-align: right;
    line-height: 1.4;
    margin-top: 0.5rem;
  }}
  .status-badge {{
    font-family: var(--mono);
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    padding: 0.15rem 0.45rem;
    border-radius: 1px;
    margin-top: auto;
  }}
  .status-badge.active   {{ background: #d4edda; color: var(--green); }}
  .status-badge.inactive {{ background: #f8d7da; color: var(--red); }}
  .status-badge.sold     {{ background: var(--cream); color: var(--muted); }}
  .no-results {{
    text-align: center;
    padding: 4rem;
    color: var(--muted);
    font-family: 'DM Serif Display', serif;
    font-style: italic;
    font-size: 1.3rem;
  }}
  .modal-overlay {{
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(15,15,15,0.65);
    z-index: 1000;
    overflow-y: auto;
    padding: 2rem 1rem;
  }}
  .modal-overlay.open {{ display: flex; justify-content: center; align-items: flex-start; }}
  .modal {{
    background: var(--paper);
    border: 1px solid var(--rule);
    max-width: 900px;
    width: 100%;
    position: relative;
    animation: modalIn 0.18s ease;
  }}
  @keyframes modalIn {{
    from {{ opacity: 0; transform: translateY(12px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
  }}
  .modal-close {{
    position: absolute;
    top: 1rem; right: 1rem;
    background: none; border: none;
    font-size: 1.4rem; cursor: pointer;
    color: var(--muted); line-height: 1;
    padding: 0.2rem 0.4rem;
  }}
  .modal-close:hover {{ color: var(--ink); }}
  .modal-map-frame {{
    width: 100%;
    height: 420px;
    border: none;
    display: block;
    background: var(--cream);
  }}
  #modal-content {{ display: block; width: 100%; box-sizing: border-box; }}
  .modal-map-bar {{
    background: var(--cream);
    border-bottom: 1px solid var(--rule);
    padding: 0.35rem 1rem;
    display: flex; justify-content: space-between; align-items: center;
    font-family: var(--mono); font-size: 10px; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.07em;
  }}
  .modal-map-bar a {{ color: var(--gold); text-decoration: none; font-weight: 500; }}
  .modal-map-bar a:hover {{ text-decoration: underline; }}
  .modal-body {{ padding: 1.5rem 2rem 2rem; }}
  .modal-header {{ margin-bottom: 1.2rem; }}
  .modal-address {{
    font-family: 'DM Serif Display', serif;
    font-size: 1.6rem; line-height: 1.1;
  }}
  .modal-sub {{
    font-family: var(--mono); font-size: 11px;
    color: var(--muted); text-transform: uppercase;
    letter-spacing: 0.07em; margin-top: 0.35rem;
    display: flex; gap: 1rem; flex-wrap: wrap;
  }}
  .modal-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1.5rem;
    margin-top: 1.2rem;
  }}
  .modal-section h3 {{
    font-family: var(--mono);
    font-size: 10px; text-transform: uppercase;
    letter-spacing: 0.12em; color: var(--muted);
    border-bottom: 1px solid var(--rule);
    padding-bottom: 0.3rem; margin-bottom: 0.6rem;
  }}
  .modal-metric-row {{
    display: flex; justify-content: space-between;
    align-items: baseline;
    padding: 0.2rem 0;
    border-bottom: 1px dotted var(--cream);
    font-size: 13px;
  }}
  .modal-metric-row:last-child {{ border-bottom: none; }}
  .modal-metric-name {{ color: var(--muted); font-size: 12px; }}
  .modal-metric-val  {{ font-family: var(--mono); font-weight: 500; }}
  .modal-metric-val.good {{ color: var(--green); }}
  .modal-metric-val.fair {{ color: var(--amber); }}
  .modal-metric-val.poor {{ color: var(--red); }}
  .modal-metric-val.info {{ color: var(--ink); }}
  .modal-metric-note {{
    display: block;
    font-family: 'DM Sans', sans-serif;
    font-size: 10px; font-weight: 400;
    color: var(--muted);
    text-align: right;
  }}
  .score-bar-row {{
    display: flex; align-items: center; gap: 0.6rem;
    padding: 0.25rem 0; font-size: 12px;
  }}
  .score-bar-label {{ width: 120px; color: var(--muted); flex-shrink: 0; font-size: 11px; }}
  .score-bar-track {{
    flex: 1; height: 6px; background: var(--cream);
    border-radius: 0; overflow: hidden; border: 1px solid var(--rule);
  }}
  .score-bar-fill {{ height: 100%; background: var(--gold); transition: width 0.3s ease; }}
  .score-bar-num {{
    font-family: var(--mono); font-size: 11px;
    color: var(--muted); width: 28px; text-align: right; flex-shrink: 0;
  }}
  .modal-notes {{
    margin-top: 1rem; padding: 0.8rem 1rem;
    background: var(--cream); border-left: 3px solid var(--gold);
    font-style: italic; font-size: 13px; color: var(--ink); line-height: 1.5;
  }}
  #city-panel {{ background: var(--cream); border-bottom: 3px double var(--rule); }}
  .city-panel-header {{ padding: 0.8rem 1.5rem; display: flex; align-items: center; gap: 1.5rem; }}
  .cr-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  .cr-table th {{
    font-family: var(--mono); font-size: 10px;
    text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted);
    padding: 0.4rem 0.7rem; text-align: right;
    border-bottom: 2px solid var(--rule); white-space: nowrap;
  }}
  .cr-table td {{
    padding: 0.4rem 0.7rem; border-bottom: 1px solid var(--rule);
    text-align: right; vertical-align: middle;
  }}
  .cr-row {{ cursor: pointer; }}
  .cr-row:hover td {{ background: #faf0d0; }}
  .cr-row.active td {{ background: #fdf5d0; }}
  .cr-city {{ font-family: 'DM Serif Display', serif; font-size: 1rem; }}
  .city-sub {{ font-family: var(--mono); font-size: 10px; color: var(--muted); margin-left: 0.5rem; }}
  .cr-bar-wrap {{ display: inline-block; width: 50px; height: 5px; background: var(--paper); border: 1px solid var(--rule); vertical-align: middle; }}
  .cr-bar {{ display: block; height: 100%; }}
  .good {{ color: var(--green); }}
  .fair {{ color: var(--amber); }}
  .poor {{ color: var(--red); }}
</style>
</head>
<body>

{city_table_html}

<div class="modal-overlay" id="modal-overlay" onclick="handleOverlayClick(event)">
  <div class="modal" id="modal">
    <button class="modal-close" onclick="closeModal()">✕</button>
    <div id="modal-content"></div>
  </div>
</div>

<header>
  <h1>Property <em>Investment</em> Report</h1>
  <div class="header-meta" id="report-date"></div>
</header>

<div class="filters">
  <div class="filter-group">
    <label>Province</label>
    <select id="f-province">
      <option value="">All Provinces</option>
      {province_opts}
    </select>
  </div>
  <div class="filter-group">
    <label>City</label>
    <select id="f-city">
      <option value="">All Cities</option>
      {city_opts}
    </select>
  </div>
  <div class="filter-group">
    <label>Property Type</label>
    <select id="f-type">
      <option value="">All Types</option>
      {type_opts}
    </select>
  </div>
  <div class="filter-group">
    <label>Status</label>
    <select id="f-status">
      <option value="">All Statuses</option>
      <option value="active">Active</option>
      <option value="inactive">Inactive</option>
    </select>
  </div>
  <div class="filter-group range-group">
    <label>Price Range</label>
    <div class="range-inputs">
      <input type="number" id="f-price-min" placeholder="Min $" step="50000">
      <span>–</span>
      <input type="number" id="f-price-max" placeholder="Max $" step="50000">
    </div>
  </div>
  <div class="filter-group">
    <label>Analysis</label>
    <select id="f-analysis">
      <option value="">All Properties</option>
      <option value="scored">Scored Only</option>
      <option value="partial">Partial Only</option>
    </select>
  </div>
  <div class="filter-actions">
    <button onclick="applyFilters()">Apply</button>
    <button class="ghost" onclick="resetFilters()">Reset</button>
  </div>
</div>

<div class="summary-strip">
  <span id="result-count"></span>
  <div class="sort-controls">
    <span style="margin-right:0.3rem">Sort:</span>
    <button class="sort-btn active" data-sort="score"     onclick="setSort('score')">Score ↓</button>
    <button class="sort-btn"        data-sort="cap_rate"  onclick="setSort('cap_rate')">Cap Rate</button>
    <button class="sort-btn"        data-sort="coc"       onclick="setSort('coc')">CoCR</button>
    <button class="sort-btn"        data-sort="irr"       onclick="setSort('irr')">IRR</button>
    <button class="sort-btn"        data-sort="cf_annual" onclick="setSort('cf_annual')">Cash Flow</button>
    <button class="sort-btn"        data-sort="asking"    onclick="setSort('asking')">Price ↑</button>
    <button class="sort-btn"        data-sort="dom"       onclick="setSort('dom')">Days Listed</button>
  </div>
</div>

<main>
  <div id="cards"></div>
</main>

<script>
const DATA = {data_json};

let currentSort = 'score';
let sortAsc = false;
let filteredData = [...DATA];
let SORTED_CACHE  = [...DATA];

function fmt(n, decimals=2, prefix='') {{
  if (n === null || n === undefined || isNaN(n)) return '—';
  return prefix + n.toLocaleString('en-CA', {{minimumFractionDigits: decimals, maximumFractionDigits: decimals}});
}}
function fmtMoney(n) {{
  if (!n && n !== 0) return '—';
  if (n >= 1e6) return '$' + (n/1e6).toFixed(2) + 'M';
  if (n >= 1e3) return '$' + (n/1e3).toFixed(0) + 'K';
  return '$' + n.toLocaleString('en-CA');
}}
function scoreGradeLabel(s) {{
  if (s === null || s === undefined) return ['none', 'No Analysis'];
  if (s >= 75) return ['excellent', 'Excellent'];
  if (s >= 55) return ['good', 'Good'];
  if (s >= 35) return ['fair', 'Fair'];
  return ['poor', 'Weak'];
}}
function metricClass(metric, value) {{
  if (value === null || value === undefined) return 'info';
  if (metric === 'cap_rate') return value >= 7.5 ? 'good' : value >= 5.5 ? 'fair' : 'poor';
  if (metric === 'coc')      return value >= 10  ? 'good' : value >= 5   ? 'fair' : 'poor';
  if (metric === 'dscr')     return value >= 1.5 ? 'good' : value >= 1.25? 'fair' : 'poor';
  if (metric === 'irr')      return value >= 15  ? 'good' : value >= 10  ? 'fair' : 'poor';
  if (metric === 'em')       return value >= 2.0 ? 'good' : value >= 1.5 ? 'fair' : 'poor';
  if (metric === 'cf_annual')return value > 0    ? (value >= 10000 ? 'good' : 'fair') : 'poor';
  return 'info';
}}
function gradeFromLabel(label) {{
  const l = (label || '').toLowerCase();
  if (l.includes('good') || l.includes('excellent') || l.includes('pass') || l.includes('celoc')) return 'good';
  if (l.includes('fair') || l.includes('friction')) return 'fair';
  if (l.includes('poor') || l.includes('bleed') || l.includes('fail') || l.includes('risk') || l.includes('no celoc')) return 'poor';
  return 'info';
}}

function renderCard(p) {{
  const [gradeClass, gradeLabel] = scoreGradeLabel(p.score);
  const scoreCardClass = p.score !== null ? `score-${{gradeClass}}` : 'score-none';
  const hasIncome = p.score !== null;

  const scoreDisplay = p.score !== null
    ? `<div class="score-num">${{p.score.toFixed(0)}}</div>`
    : `<div class="score-num no-score">No<br>Analysis</div>`;

  const metricsHtml = hasIncome ? `
    <div class="metrics-row">
      <div class="metric-chip">
        <span class="m-label">Cap Rate</span>
        <span class="m-value ${{metricClass('cap_rate', p.cap_rate)}}">${{fmt(p.cap_rate)}}%</span>
      </div>
      <div class="metric-chip">
        <span class="m-label">CoCR</span>
        <span class="m-value ${{metricClass('coc', p.coc)}}">${{fmt(p.coc)}}%</span>
      </div>
      <div class="metric-chip">
        <span class="m-label">DSCR</span>
        <span class="m-value ${{metricClass('dscr', p.dscr)}}">${{fmt(p.dscr)}}</span>
      </div>
      <div class="metric-chip">
        <span class="m-label">IRR</span>
        <span class="m-value ${{metricClass('irr', p.irr)}}">${{fmt(p.irr)}}%</span>
      </div>
      <div class="metric-chip">
        <span class="m-label">Equity ×</span>
        <span class="m-value ${{metricClass('em', p.em)}}">${{fmt(p.em)}}x</span>
      </div>
      <div class="metric-chip">
        <span class="m-label">Annual CF</span>
        <span class="m-value ${{metricClass('cf_annual', p.cf_annual)}}">${{fmtMoney(p.cf_annual)}}</span>
      </div>
      ${{p.price_drop > 0 ? `<div class="metric-chip">
        <span class="m-label">Price Drop</span>
        <span class="m-value good">${{fmt(p.price_drop)}}%</span>
      </div>` : ''}}
    </div>` : `<div style="color:#6b6355;font-style:italic;font-size:12px;margin-top:0.5rem">Partial analysis only — income metrics unavailable</div>`;

  const statusClass = (p.status || '').toLowerCase();
  const ppSqft = p.sqft > 0 ? (p.asking / p.sqft) : null;
  const idx = SORTED_CACHE.indexOf(p);

  return `<div class="card ${{scoreCardClass}}" data-idx="${{idx}}" title="Click for full report">
    <div class="card-score">
      ${{scoreDisplay}}
      <div class="score-label">Investment Score</div>
      <div class="score-grade ${{gradeClass}}">${{gradeLabel}}</div>
    </div>
    <div class="card-body">
      <div class="card-address">${{p.address}}</div>
      <div class="card-meta">
        <span class="pill">${{p.type}}</span>
        <span>${{p.mls}}</span>
        <span>${{p.sqft > 0 ? p.sqft.toLocaleString() + ' sq ft' : ''}}</span>
        ${{ppSqft ? `<span>${{fmt(ppSqft, 0, '$')}}/sq ft</span>` : ''}}
        ${{p.construction > 0 ? `<span class="pill" style="color:#b8960c">+${{fmtMoney(p.construction)}} reno</span>` : ''}}
        ${{p.dist_km !== null && p.dist_km !== undefined ? `<span class="pill">${{p.dist_km}}km to ${{p.dist_centre || 'centre'}}</span>` : ''}}
        <span>${{p.dom > 0 ? p.dom + ' days listed' : ''}}</span>
      </div>
      ${{metricsHtml}}
    </div>
    <div class="card-right">
      <div>
        <div class="asking-price">${{fmtMoney(p.asking)}}</div>
        <div class="price-meta">${{p.city}}${{p.province ? ', ' + p.province : ''}}</div>
        ${{p.price_drop > 0 ? `<div class="price-meta" style="color:#2d6a4f">▼ ${{fmt(p.price_drop)}}% from list</div>` : ''}}
      </div>
      ${{p.notes ? `<div class="card-notes">${{p.notes.slice(0,80)}}${{p.notes.length>80?'…':''}}</div>` : ''}}
      <div class="status-badge ${{statusClass}}">${{p.status}}</div>
    </div>
  </div>`;
}}

function applyFilters() {{
  const province = document.getElementById('f-province').value;
  const city     = document.getElementById('f-city').value;
  const type     = document.getElementById('f-type').value;
  const status   = document.getElementById('f-status').value;
  const priceMin = parseFloat(document.getElementById('f-price-min').value) || 0;
  const priceMax = parseFloat(document.getElementById('f-price-max').value) || Infinity;
  const analysis = document.getElementById('f-analysis').value;

  filteredData = DATA.filter(p => {{
    if (province && p.province !== province) return false;
    if (city     && p.city     !== city)     return false;
    if (type     && p.type     !== type)     return false;
    if (status   && p.status   !== status)   return false;
    if (p.asking < priceMin || p.asking > priceMax) return false;
    if (analysis === 'scored'  && p.score === null) return false;
    if (analysis === 'partial' && p.score !== null) return false;
    return true;
  }});
  renderAll();
}}

function resetFilters() {{
  ['f-province','f-city','f-type','f-status','f-analysis'].forEach(id => document.getElementById(id).value = '');
  document.getElementById('f-price-min').value = '';
  document.getElementById('f-price-max').value = '';
  filteredData = [...DATA];
  renderAll();
}}

function setSort(field) {{
  if (currentSort === field) {{
    sortAsc = !sortAsc;
  }} else {{
    currentSort = field;
    sortAsc = field === 'asking';
  }}
  document.querySelectorAll('.sort-btn').forEach(b => b.classList.remove('active'));
  document.querySelector(`[data-sort="${{field}}"]`).classList.add('active');
  renderAll();
}}

function renderAll() {{
  const sorted = [...filteredData].sort((a, b) => {{
    let va = a[currentSort], vb = b[currentSort];
    if (va === null || va === undefined) va = sortAsc ?  Infinity : -Infinity;
    if (vb === null || vb === undefined) vb = sortAsc ?  Infinity : -Infinity;
    return sortAsc ? va - vb : vb - va;
  }});
  const container = document.getElementById('cards');
  if (sorted.length === 0) {{
    container.innerHTML = '<div class="no-results">No properties match the current filters</div>';
  }} else {{
    SORTED_CACHE = sorted;
    container.innerHTML = sorted.map(renderCard).join('');
  }}
  document.getElementById('result-count').textContent =
    `${{sorted.length}} of ${{DATA.length}} properties`;
}}

document.getElementById('cards').addEventListener('click', function(e) {{
  const card = e.target.closest('.card[data-idx]');
  if (!card) return;
  const idx = parseInt(card.getAttribute('data-idx'), 10);
  if (!isNaN(idx) && SORTED_CACHE[idx]) openModal(SORTED_CACHE[idx]);
}});

document.querySelectorAll('.cr-row').forEach(function(row) {{
  row.addEventListener('click', function() {{
    const city = this.getAttribute('data-city');
    document.querySelectorAll('.cr-row').forEach(r => r.classList.remove('active'));
    this.classList.add('active');
    const sel = document.getElementById('f-city');
    if (sel) {{
      sel.value = city;
      applyFilters();
      document.querySelector('.filters').scrollIntoView({{behavior:'smooth'}});
    }}
  }});
}});

document.getElementById('report-date').textContent =
  'Generated ' + new Date().toLocaleDateString('en-CA', {{year:'numeric',month:'long',day:'numeric'}});
renderAll();

// ── Modal ──────────────────────────────────────────────────────────────────
function openModal(p) {{
  const addrEnc       = encodeURIComponent(p.address);
  const mapEmbedUrl   = `https://www.google.com/maps?q=${{addrEnc}}&layer=c&output=svembed`;
  const mapsSearchUrl = `https://www.google.com/maps/search/?api=1&query=${{addrEnc}}`;

  const SECTIONS = [
    {{ label: "Mortgage & Financing", keys: ["Loan Amount","Down Payment","Construction Cost","Total Cash In","Monthly Payment","Annual Debt Svc"] }},
    {{ label: "Pricing",              keys: ["Price/Sq Ft (*","GRM","Tax Load","Price Drop %","Loan to Value"] }},
    {{ label: "Income",               keys: ["Gross Potential Rent","Vacancy Rate","Effective Gross Income","Expense Ratio","NOI","Cap Rate","Op Expense Ratio"] }},
    {{ label: "Exit",                 keys: ["Exit Cap Rate","Exit Cap Ratio","Exit Price"] }},
    {{ label: "Cash Flow",            keys: ["Annual Cash Flow","Monthly Cash Flow","CoCR"] }},
    {{ label: "Debt",                 keys: ["DSCR","Break-Even NOI","Break-Even NOI %","Break-Even Occupancy %","Stress Test (+2%)"] }},
    {{ label: "Returns",              keys: ["IRR (*","Equity Multiple","NOI Growth Assumption"] }},
    {{ label: "Market",               keys: ["CELOC Speed Score","{staleness_key}","Seller Bleed"] }},
    {{ label: "Hotel Operations",     keys: ["Hotel Rooms","ADR","Occupancy Rate","RevPAR","NRevPAR (low dist.)","NRevPAR (mid dist.)","NRevPAR (high dist.)","Rev/Room/Yr","GOP Margin","GOP Amount","CPOR","FF&E Reserve"] }},
    {{ label: "Industrial",           keys: ["Clear Height","Dock Doors","Drive-In Doors","Warehouse Income","Office Income","Yard Income","Door Income","Total Industrial Rev","Blended Rate"] }},
  ];
  const CONF_LABELS = {{ HIGH: "High confidence", MED: "Medium confidence", LOW: "Approximate — details required" }};
  const confBadge = p.income_confidence
    ? `<span style="color:${{p.income_confidence==='LOW'?'#8b1a1a':p.income_confidence==='MED'?'#c17f24':'#2d6a4f'}}">${{CONF_LABELS[p.income_confidence] || p.income_confidence}}</span>`
    : '';

  const resultMap = {{}};
  (p.results || []).forEach(r => {{ resultMap[r.metric] = r; }});
  const rentLines = (p.rent_breakdown || []).filter(l => l && !l.startsWith('  ⚠'));
  const [gradeClass_, gradeLabel_] = scoreGradeLabel(p.score);
  const ppSqft = p.sqft > 0 ? (p.asking / p.sqft) : null;

  const resolveKey = k => k.endsWith('*')
    ? Object.keys(resultMap).find(rk => rk.startsWith(k.slice(0, -1))) || null
    : (resultMap[k] ? k : null);

  const sectionsHtml = SECTIONS.map(sec => {{
    const rows = sec.keys
      .map(k => resolveKey(k))
      .filter(k => k)
      .map(k => {{
        const r  = resultMap[k];
        const gc = gradeFromLabel(r.grade);
        // "value — annotation" renders as the value with a small muted
        // note beneath it (e.g. NOI growth provenance), keeping the
        // value column short and numeric.
        const parts = String(r.value).split(' — ');
        const val   = parts[0];
        const note  = parts.slice(1).join(' — ');
        return `<div class="modal-metric-row">
          <span class="modal-metric-name">${{r.metric}}</span>
          <span class="modal-metric-val ${{gc}}">${{val}}${{note ? `<span class="modal-metric-note">${{note}}</span>` : ''}}</span>
        </div>`;
      }}).join('');
    if (!rows) return '';
    return `<div class="modal-section"><h3>${{sec.label}}</h3>${{rows}}</div>`;
  }}).filter(Boolean).join('');

  const breakdown = p.breakdown || {{}};
  const weights   = p.weights   || {{}};
  const barsHtml  = Object.entries(breakdown)
    .filter(([k]) => (weights[k] || 0) > 0)
    .sort((a,b) => b[1] - a[1])
    .map(([k, v]) => {{
      const pct = Math.min(100, v);
      const w   = ((weights[k] || 0) * 100).toFixed(0);
      return `<div class="score-bar-row">
        <span class="score-bar-label">${{k}} <span style="color:#b8960c">(${{w}}%)</span></span>
        <div class="score-bar-track"><div class="score-bar-fill" style="width:${{pct}}%"></div></div>
        <span class="score-bar-num">${{v.toFixed(0)}}</span>
      </div>`;
    }}).join('');

  const notesHtml = p.notes ? `<div class="modal-notes">${{p.notes}}</div>` : '';
  const rentHtml  = rentLines.length
    ? `<div class="modal-section" style="margin-top:1rem"><h3>Rent Detail</h3>
        ${{rentLines.map(l=>`<div class="modal-metric-row"><span class="modal-metric-name" style="color:var(--ink)">${{l}}</span></div>`).join('')}}
      </div>` : '';

  const propDetails = `
    <div class="modal-metric-row"><span class="modal-metric-name">MLS #</span><span class="modal-metric-val info">${{p.mls}}</span></div>
    <div class="modal-metric-row"><span class="modal-metric-name">Type</span><span class="modal-metric-val info">${{p.type}}</span></div>
    <div class="modal-metric-row"><span class="modal-metric-name">Total Sq Ft</span><span class="modal-metric-val info">${{p.sqft.toLocaleString()}}</span></div>
    ${{ppSqft ? `<div class="modal-metric-row"><span class="modal-metric-name">Price / Sq Ft</span><span class="modal-metric-val info">${{fmt(ppSqft, 0, '$')}}</span></div>` : ''}}
    <div class="modal-metric-row"><span class="modal-metric-name">Asking Price</span><span class="modal-metric-val info">${{fmtMoney(p.asking)}}</span></div>
    <div class="modal-metric-row"><span class="modal-metric-name">Original Price</span><span class="modal-metric-val info">${{fmtMoney(p.original)}}</span></div>
    ${{p.construction > 0 ? `<div class="modal-metric-row"><span class="modal-metric-name">Construction</span><span class="modal-metric-val info">+${{fmtMoney(p.construction)}}</span></div>` : ''}}
    <div class="modal-metric-row"><span class="modal-metric-name">Property Taxes</span><span class="modal-metric-val info">${{fmtMoney(p.taxes)}}/yr</span></div>
    <div class="modal-metric-row"><span class="modal-metric-name">Down Payment</span><span class="modal-metric-val info">${{(p.down_pct*100).toFixed(0)}}%</span></div>
    <div class="modal-metric-row"><span class="modal-metric-name">Interest Rate</span><span class="modal-metric-val info">${{(p.rate*100).toFixed(2)}}%</span></div>
    <div class="modal-metric-row"><span class="modal-metric-name">Term / Hold</span><span class="modal-metric-val info">${{p.term}} yr / ${{p.hold}} yr</span></div>
    <div class="modal-metric-row"><span class="modal-metric-name">Expense Ratio</span><span class="modal-metric-val info">${{(p.expense_ratio*100).toFixed(0)}}%</span></div>
    <div class="modal-metric-row"><span class="modal-metric-name">Lease Type</span><span class="modal-metric-val info">${{p.lease_type}}</span></div>
    <div class="modal-metric-row"><span class="modal-metric-name">Listed</span><span class="modal-metric-val info">${{p.listed}}</span></div>
    ${{p.dist_km != null ? `<div class="modal-metric-row"><span class="modal-metric-name">Distance</span><span class="modal-metric-val info">${{p.dist_km}}km to ${{p.dist_centre}}</span></div>` : ''}}
  `;

  const targets = p.targets || {{}};
  const hasTargets = Object.keys(targets).length > 0;
  const TARGET_LABELS = {{
    price:    {{ label: "Asking Price",  fmt: v => fmtMoney(v),            note: "negotiate down to" }},
    rent:     {{ label: "Annual Rent",   fmt: v => fmtMoney(v) + "/yr",    note: "needs to reach"    }},
    rate:     {{ label: "Interest Rate", fmt: v => (v*100).toFixed(2)+"%", note: "refinance below"   }},
    down_pct: {{ label: "Down Payment",  fmt: v => (v*100).toFixed(0)+"%", note: "increase to"       }},
  }};
  const targetRows = Object.entries(targets).map(([k, v]) => {{
    const def_ = TARGET_LABELS[k] || {{ label: k, fmt: x => x, note: "target" }};
    return `<div class="modal-metric-row">
      <span class="modal-metric-name">${{def_.label}} <span style="color:var(--muted);font-size:10px">(${{def_.note}})</span></span>
      <span class="modal-metric-val good">${{def_.fmt(v)}}</span>
    </div>`;
  }}).join('');
  const targetsHtml = hasTargets
    ? `<div style="margin-top:1.5rem"><div class="modal-section">
        <h3 style="color:var(--gold)">What would make this a 100/100?</h3>
        <div style="font-size:11px;color:var(--muted);margin-bottom:0.6rem;font-style:italic">
          Each lever shown independently — changing one alone would achieve a perfect score.
        </div>
        ${{targetRows}}
      </div></div>`
    : (p.score !== null && p.score >= 99
        ? `<div style="margin-top:1rem;padding:0.8rem 1rem;background:#d4edda;border-left:3px solid var(--green);font-family:var(--mono);font-size:12px;color:var(--green)">
            Already scores 100/100 — this is an exceptional investment.</div>`
        : '');

  document.getElementById('modal-content').innerHTML = `
    <iframe class="modal-map-frame" src="${{mapEmbedUrl}}" loading="lazy"
            referrerpolicy="no-referrer-when-downgrade" allowfullscreen></iframe>
    <div class="modal-map-bar">
      <span>${{p.address}}</span>
      <a href="${{mapsSearchUrl}}" target="_blank" rel="noopener">Open in Google Maps ↗</a>
    </div>
    <div class="modal-body">
      <div class="modal-header">
        <div class="modal-address">${{p.address}}</div>
        <div class="modal-sub">
          <span>${{p.city}}${{p.province ? ', ' + p.province : ''}}</span>
          <span>${{p.type}}</span>
          <span style="color:${{p.status==='active'?'#2d6a4f':'#8b1a1a'}}">${{p.status}}</span>
          ${{p.score !== null ? `<span style="color:var(--gold);font-weight:500">Score: ${{p.score.toFixed(0)}}/100 — ${{scoreGradeLabel(p.score)[1]}}</span>` : ''}}
          ${{confBadge}}
        </div>
      </div>
      ${{notesHtml}}
      <div class="modal-grid">
        <div>
          <div class="modal-section"><h3>Property Details</h3>${{propDetails}}</div>
          ${{rentHtml}}
        </div>
        <div>${{sectionsHtml}}</div>
      </div>
      ${{barsHtml ? `<div style="margin-top:1.5rem"><div class="modal-section"><h3>Score Breakdown</h3>${{barsHtml}}</div></div>` : ''}}
      ${{targetsHtml}}
    </div>
  `;

  document.getElementById('modal-overlay').classList.add('open');
  document.body.style.overflow = 'hidden';
}}

function closeModal() {{
  document.getElementById('modal-overlay').classList.remove('open');
  document.body.style.overflow = '';
}}

function handleOverlayClick(e) {{
  if (e.target === document.getElementById('modal-overlay')) closeModal();
}}

document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeModal(); }});
</script>
</body>
</html>"""

    def open_in_browser(self, rows: list, city_table_html: str = ""):
        """Build the report and open it in the default browser."""
        html = self.render(rows, city_table_html)
        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.html', delete=False,
            prefix='property_report_', encoding='utf-8'
        )
        tmp.write(html)
        tmp.close()
        webbrowser.open(f'file://{tmp.name}')
        print(f"\n  Report opened in browser.")
        print(f"  File saved to: {tmp.name}")
