import json as _json
import os
import tempfile
import webbrowser

_SCORE_WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), "..", "json", "score_weights.json")


def _load_city_thresholds() -> dict:
    try:
        with open(_SCORE_WEIGHTS_PATH, encoding="utf-8") as fh:
            return _json.load(fh).get("city_score_thresholds", {})
    except (OSError, _json.JSONDecodeError):
        return {}


class CityReportGenerator:
    """Renders the city investment rankings as a standalone HTML file and opens it."""

    def render(self, cities: list) -> str:
        """Build and return the full HTML string for the city report."""
        cities_json = _json.dumps(cities, indent=2)
        thresholds = _load_city_thresholds()
        thresholds_json = _json.dumps(thresholds)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>City Investment Rankings</title>
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
  .page-wrap {{
    max-width: 860px;
    margin: 0 auto;
    padding: 2rem 2rem 4rem;
  }}
  .city-list {{
    display: flex;
    flex-direction: column;
    gap: 0;
  }}
  .city-row {{
    border: 1px solid var(--rule);
    border-top: none;
    background: white;
    transition: background 0.1s;
    cursor: pointer;
  }}
  .city-row:first-child {{ border-top: 1px solid var(--rule); border-radius: 2px 2px 0 0; }}
  .city-row:last-child  {{ border-radius: 0 0 2px 2px; }}
  .city-row:hover .city-row-main {{ background: #fffdf5; }}
  .city-row-main {{
    display: grid;
    grid-template-columns: 48px 1fr auto 180px;
    align-items: center;
    padding: 1rem 1.2rem;
    gap: 1rem;
    border-left: 5px solid var(--rule);
    transition: border-color 0.15s;
  }}
  .city-row.rank-1 .city-row-main  {{ border-left-color: #b8960c; }}
  .city-row.rank-2 .city-row-main  {{ border-left-color: #9aa0a6; }}
  .city-row.rank-3 .city-row-main  {{ border-left-color: #cd7f32; }}
  .city-row.excellent .city-row-main {{ border-left-color: var(--green); }}
  .city-row.good      .city-row-main {{ border-left-color: #8db87a; }}
  .city-row.fair      .city-row-main {{ border-left-color: var(--amber); }}
  .city-row.poor      .city-row-main {{ border-left-color: var(--red); }}
  .rank-num {{
    font-family: var(--mono);
    font-size: 1.2rem;
    font-weight: 500;
    color: var(--muted);
    text-align: center;
  }}
  .city-info {{ min-width: 0; }}
  .city-name {{
    font-family: 'DM Serif Display', serif;
    font-size: 1.35rem;
    line-height: 1.1;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .city-pills {{
    display: flex;
    gap: 0.5rem;
    margin-top: 0.25rem;
    flex-wrap: wrap;
  }}
  .pill {{
    font-family: var(--mono);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    padding: 0.1rem 0.5rem;
    border: 1px solid var(--rule);
    border-radius: 2px;
    color: var(--muted);
    background: var(--cream);
  }}
  .pill.active {{ color: var(--green); border-color: var(--green); background: #edf7f1; }}
  .pill.inactive {{ color: var(--muted); border-color: var(--rule); }}
  .city-score-col {{ text-align: right; }}
  .city-opp-num {{
    font-family: var(--mono);
    font-size: 1.6rem;
    font-weight: 500;
    line-height: 1;
  }}
  .city-opp-label {{
    font-family: var(--mono);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
    margin-top: 0.1rem;
  }}
  .city-metrics {{
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }}
  .opp-bar-track {{
    height: 6px;
    background: var(--cream);
    border: 1px solid var(--rule);
    border-radius: 0;
    overflow: hidden;
  }}
  .opp-bar-fill {{ height: 100%; transition: width 0.3s; }}
  .mini-stats {{
    display: flex;
    gap: 0.8rem;
    font-family: var(--mono);
    font-size: 10px;
    color: var(--muted);
    flex-wrap: wrap;
  }}
  .mini-stat span {{ font-weight: 500; }}
  .mini-stat span.good {{ color: var(--green); }}
  .mini-stat span.fair {{ color: var(--amber); }}
  .mini-stat span.poor {{ color: var(--red); }}
  .chevron {{
    display: inline-block;
    transition: transform 0.2s;
    font-size: 0.7rem;
    color: var(--muted);
    margin-left: 0.4rem;
  }}
  .city-row.open .chevron {{ transform: rotate(180deg); }}
  .city-detail {{
    display: none;
    padding: 1.2rem 1.5rem 1.5rem 1.5rem;
    border-top: 1px dashed var(--rule);
    background: var(--cream);
  }}
  .city-row.open .city-detail {{ display: block; }}
  .detail-verdict {{
    font-size: 13.5px;
    line-height: 1.65;
    color: var(--ink);
    padding: 0.8rem 1rem;
    background: white;
    border-left: 3px solid var(--gold);
    margin-bottom: 1.2rem;
  }}
  .detail-grid {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 0.7rem;
    margin-bottom: 1.2rem;
  }}
  .detail-card {{
    background: white;
    border: 1px solid var(--rule);
    padding: 0.65rem 0.8rem;
  }}
  .detail-card-label {{
    font-family: var(--mono);
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--muted);
    margin-bottom: 0.2rem;
  }}
  .detail-card-val {{
    font-family: var(--mono);
    font-size: 1.05rem;
    font-weight: 500;
  }}
  .detail-card-val.good {{ color: var(--green); }}
  .detail-card-val.fair {{ color: var(--amber); }}
  .detail-card-val.poor {{ color: var(--red); }}
  .detail-card-val.info {{ color: var(--ink); }}
  .detail-card-sub {{ font-size: 10px; color: var(--muted); margin-top: 0.15rem; }}
  .factor-section-title, .detail-section-title {{
    font-family: var(--mono);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--muted);
    border-bottom: 1px solid var(--rule);
    padding-bottom: 0.3rem;
    margin-bottom: 0.6rem;
    margin-top: 1rem;
  }}
  .factor-bar-row {{
    display: flex;
    align-items: center;
    gap: 0.7rem;
    padding: 0.2rem 0;
    font-size: 12px;
  }}
  .factor-bar-label {{ width: 160px; color: var(--muted); flex-shrink: 0; font-size: 11px; }}
  .factor-bar-track {{
    flex: 1;
    height: 7px;
    background: white;
    border: 1px solid var(--rule);
    overflow: hidden;
  }}
  .factor-bar-fill {{ height: 100%; background: var(--gold); }}
  .factor-bar-right {{
    font-family: var(--mono);
    font-size: 11px;
    color: var(--muted);
    width: 100px;
    text-align: right;
    flex-shrink: 0;
  }}
  .good {{ color: var(--green); }}
  .fair {{ color: var(--amber); }}
  .poor {{ color: var(--red); }}
  .price-filter {{
    display: flex;
    align-items: center;
    gap: 0.6rem;
    margin-top: 1rem;
    flex-wrap: wrap;
  }}
  .price-filter label {{
    font-family: var(--mono);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
  }}
  .price-filter input[type=number] {{
    font-family: var(--mono);
    font-size: 12px;
    width: 110px;
    padding: 0.3rem 0.5rem;
    border: 1px solid var(--rule);
    border-radius: 2px;
    background: white;
    color: var(--ink);
  }}
  .price-filter input[type=number]:focus {{ outline: none; border-color: var(--gold); }}
  .price-filter button {{
    font-family: var(--mono);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    padding: 0.3rem 0.9rem;
    background: var(--ink);
    color: var(--paper);
    border: none;
    border-radius: 2px;
    cursor: pointer;
  }}
  .price-filter button:hover {{ background: #333; }}
  .price-filter .reset-btn {{
    background: transparent;
    color: var(--muted);
    border: 1px solid var(--rule);
  }}
  .price-filter .reset-btn:hover {{ color: var(--ink); border-color: var(--ink); background: transparent; }}
  .filter-badge {{
    font-family: var(--mono);
    font-size: 10px;
    color: var(--amber);
    border: 1px solid var(--amber);
    padding: 0.1rem 0.5rem;
    border-radius: 2px;
    display: none;
  }}
  .filter-badge.visible {{ display: inline-block; }}
  .no-results {{
    text-align: center;
    padding: 3rem 1rem;
    font-family: var(--mono);
    font-size: 13px;
    color: var(--muted);
    display: none;
  }}
</style>
</head>
<body>
<header>
  <h1>City <em>Investment</em> Rankings</h1>
  <div class="header-meta" id="report-date"></div>
  <div class="price-filter">
    <label>Price Range:</label>
    <label>Min $</label>
    <input type="number" id="price-min" placeholder="No min" min="0" step="50000">
    <label>Max $</label>
    <input type="number" id="price-max" placeholder="No max" min="0" step="50000">
    <button onclick="applyPriceFilter()">Apply</button>
    <button class="reset-btn" onclick="resetPriceFilter()">Reset</button>
    <span class="filter-badge" id="filter-badge">Filtered</span>
  </div>
</header>

<div class="page-wrap">
  <div class="city-list" id="city-list"></div>
  <div class="no-results" id="no-results">No cities match the selected price range.</div>
</div>

<script>
const CITIES = {cities_json};

let _priceMin = null;
let _priceMax = null;

function applyPriceFilter() {{
  const minRaw = document.getElementById('price-min').value.trim();
  const maxRaw = document.getElementById('price-max').value.trim();
  _priceMin = minRaw !== '' ? parseFloat(minRaw) : null;
  _priceMax = maxRaw !== '' ? parseFloat(maxRaw) : null;
  const badge = document.getElementById('filter-badge');
  badge.classList.toggle('visible', _priceMin !== null || _priceMax !== null);
  renderAll();
}}

function resetPriceFilter() {{
  _priceMin = null; _priceMax = null;
  document.getElementById('price-min').value = '';
  document.getElementById('price-max').value = '';
  document.getElementById('filter-badge').classList.remove('visible');
  renderAll();
}}

function cityMatchesFilter(c) {{
  if (_priceMin === null && _priceMax === null) return true;
  if (!c.act_price) return true;
  if (_priceMin !== null && c.act_price < _priceMin) return false;
  if (_priceMax !== null && c.act_price > _priceMax) return false;
  return true;
}}

function renderAll() {{
  const filtered = CITIES.filter(cityMatchesFilter);
  const list = document.getElementById('city-list');
  const noResults = document.getElementById('no-results');
  if (filtered.length === 0) {{
    list.innerHTML = '';
    noResults.style.display = 'block';
  }} else {{
    noResults.style.display = 'none';
    list.innerHTML = filtered.map((c, i) => renderCity(c, i)).join('');
  }}
  const badge = document.getElementById('report-date');
  const total  = CITIES.reduce((s,c)=>s+c.total,0);
  const shown  = filtered.reduce((s,c)=>s+c.total,0);
  const filterNote = (_priceMin !== null || _priceMax !== null)
    ? ` · showing ${{filtered.length}} of ${{CITIES.length}} cit${{CITIES.length===1?'y':'ies'}} (${{shown}} props)`
    : '';
  badge.textContent = 'Generated ' + new Date().toLocaleDateString('en-CA', {{year:'numeric',month:'long',day:'numeric'}})
    + ' · ' + CITIES.length + ' cit' + (CITIES.length===1?'y':'ies') + ' · '
    + total + ' properties' + filterNote;
}}

document.addEventListener('DOMContentLoaded', () => {{
  ['price-min','price-max'].forEach(id => {{
    document.getElementById(id).addEventListener('keydown', e => {{
      if (e.key === 'Enter') applyPriceFilter();
    }});
  }});
}});

function fp(n)  {{ return n ? n.toFixed(1) + '%' : '—'; }}
function fi(n)  {{ return (n !== null && n !== undefined && n !== 0) ? n.toFixed(0) : '—'; }}
function fm(n)  {{
  if (!n) return '—';
  if (n >= 1e6) return '$' + (n/1e6).toFixed(1) + 'M';
  if (n >= 1e3) return '$' + (n/1e3).toFixed(0) + 'K';
  return '$' + n.toLocaleString('en-CA');
}}
function gc(metric, v) {{
  if (!v && v !== 0) return 'info';
  if (metric === 'cap')   return v >= 7   ? 'good' : v >= 5   ? 'fair' : 'poor';
  if (metric === 'coc')   return v >= 10  ? 'good' : v >= 5   ? 'fair' : 'poor';
  if (metric === 'irr')   return v >= 15  ? 'good' : v >= 10  ? 'fair' : 'poor';
  if (metric === 'dscr')  return v >= 1.5 ? 'good' : v >= 1.25? 'fair' : 'poor';
  if (metric === 'score') return v >= 70  ? 'good' : v >= 45  ? 'fair' : 'poor';
  if (metric === 'drop')  return v > 2    ? 'good' : v > 0    ? 'fair' : 'info';
  if (metric === 'dom')   return v >= 90  ? 'good' : v >= 60  ? 'fair' : 'info';
  return 'info';
}}

function gradeOf(opp) {{
  if (opp >= 75) return ['excellent', 'Excellent'];
  if (opp >= 55) return ['good',      'Good'];
  if (opp >= 35) return ['fair',      'Fair'];
  return ['poor', 'Weak'];
}}

function oppColor(opp) {{
  if (opp >= 65) return 'var(--green)';
  if (opp >= 35) return 'var(--amber)';
  return 'var(--red)';
}}

function buildVerdict(c, rank) {{
  const strengths = [], weaknesses = [], context = [];
  if (c.act_score >= 60)  strengths.push(`active deal quality averaging ${{fi(c.act_score)}}/100`);
  else if (c.act_score > 0 && c.act_score < 40) weaknesses.push(`weak active deal quality (${{fi(c.act_score)}}/100)`);
  if (c.act_cap >= 7)     strengths.push(`strong live cap rate of ${{fp(c.act_cap)}}`);
  else if (c.act_cap > 0 && c.act_cap < 5) weaknesses.push(`below-target live cap rate (${{fp(c.act_cap)}})`);
  if (c.act_coc >= 10)    strengths.push(`solid active cash-on-cash (${{fp(c.act_coc)}})`);
  else if (c.act_coc > 0 && c.act_coc < 5) weaknesses.push(`low active cash-on-cash (${{fp(c.act_coc)}})`);
  if (c.act_drop > 3)     strengths.push(`avg price reduction of ${{fp(c.act_drop)}} on active listings`);
  if (c.act_dom >= 90)    strengths.push(`active properties averaging ${{c.act_dom}} days listed`);
  else if (c.act_dom > 0 && c.act_dom < 30) weaknesses.push(`fast-moving market (${{c.act_dom}}d avg DOM)`);
  if (c.active === 0)     weaknesses.push(`no active listings — no actionable deals`);
  if (c.confidence < 0.5) weaknesses.push(`limited data (${{c.total}} propert${{c.total===1?'y':'ies'}} — score discounted)`);
  if (c.inact_score >= 60) context.push(`historical deals averaged ${{fi(c.inact_score)}}/100 — market has produced quality`);
  else if (c.inactive > 0 && c.inact_score < 40) context.push(`historical deals were weak (${{fi(c.inact_score)}}/100)`);
  if (c.cap_trend > 0.5)       context.push(`cap rates trending up vs historical (${{c.cap_trend > 0 ? '+' : ''}}${{fp(c.cap_trend)}} vs inactive)`);
  else if (c.cap_trend < -0.5) context.push(`cap rates trending down vs historical (${{fp(c.cap_trend)}} vs inactive)`);
  if (c.has_demo) {{
    const popFmtV = p => p >= 1000000 ? (p/1000000).toFixed(1)+'M' : p >= 1000 ? Math.round(p/1000)+'K' : p;
    if (c.pop_growth >= 2.0)       strengths.push(`strong pop. growth (${{c.pop_growth.toFixed(2)}}%/yr) — expanding tenant base`);
    else if (c.pop_growth >= 0.5)  context.push(`steady pop. growth (${{c.pop_growth.toFixed(2)}}%/yr)`);
    else if (c.pop_growth < 0)     weaknesses.push(`declining population (${{c.pop_growth.toFixed(2)}}%/yr) — exit risk`);
    if (c.population >= 50000)     strengths.push(`large market (${{popFmtV(c.population)}} people) — liquidity and tenant depth`);
    else if (c.population < 5000)  context.push(`small market (${{popFmtV(c.population)}} people) — niche, lower liquidity`);
  }} else {{
    context.push('no demographic data on file — population/growth not factored in');
  }}
  let out = `Ranked <strong>#${{rank}}</strong> of ${{CITIES.length}} cities. `;
  if (strengths.length)  out += `Strengths: ${{strengths.join('; ')}}. `;
  else                   out += `No standout active metrics. `;
  if (weaknesses.length) out += `Headwinds: ${{weaknesses.join('; ')}}. `;
  if (context.length)    out += `Historical context: ${{context.join('; ')}}.`;
  return out;
}}

function renderCity(c, i) {{
  const rank       = i + 1;
  const [grade, gradeLabel] = gradeOf(c.opportunity);
  const barColor   = oppColor(c.opportunity);
  const barW       = Math.min(100, c.opportunity);
  const rankClass  = rank <= 3 ? `rank-${{rank}}` : grade;
  const miniStats = [
    c.act_cap   ? `Cap <span class="${{gc('cap',   c.act_cap)}}">${{fp(c.act_cap)}}</span>`   : '',
    c.act_coc   ? `CoCR <span class="${{gc('coc',  c.act_coc)}}">${{fp(c.act_coc)}}</span>`  : '',
    c.act_irr   ? `IRR <span class="${{gc('irr',   c.act_irr)}}">${{fp(c.act_irr)}}</span>`  : '',
    c.act_score ? `Score <span style="color:${{barColor}}">${{fi(c.act_score)}}</span>` : '',
  ].filter(Boolean).map(s => `<span class="mini-stat">${{s}}</span>`).join('');
  const typeStr = Object.entries(c.type_counts || {{}})
    .sort((a,b) => b[1]-a[1])
    .map(([t,n]) => `${{n}}× ${{t}}`).join(', ');
  const trendArrow = c.cap_trend > 0.1 ? '▲' : c.cap_trend < -0.1 ? '▼' : '→';
  const trendCls   = c.cap_trend > 0.1 ? 'good' : c.cap_trend < -0.1 ? 'poor' : 'info';
  const confPctStr = c.confidence ? (c.confidence * 100).toFixed(0) + '%' : '—';
  const confCls    = c.confidence >= 0.8 ? 'good' : c.confidence >= 0.5 ? 'fair' : 'poor';
  const activeCards = [
    {{ label:'Deal Score (Active)',  val: c.act_score  ? fi(c.act_score)+'/100':'—',  cls: gc('score',c.act_score),  sub:'avg across active listings' }},
    {{ label:'Cap Rate (Active)',    val: fp(c.act_cap),   cls: gc('cap',c.act_cap),   sub:'≥7% strong · live deals' }},
    {{ label:'CoCR (Active)',        val: fp(c.act_coc),   cls: gc('coc',c.act_coc),   sub:'≥10% strong · live deals' }},
    {{ label:'IRR (Active)',         val: fp(c.act_irr),   cls: gc('irr',c.act_irr),   sub:'≥15% strong · live deals' }},
    {{ label:'DSCR (Active)',        val: c.act_dscr ? c.act_dscr.toFixed(2):'—', cls: gc('dscr',c.act_dscr), sub:'≥1.5 strong' }},
    {{ label:'Price Drop (Active)',  val: fp(c.act_drop),  cls: gc('drop',c.act_drop), sub:'from original list' }},
    {{ label:'Days Listed (Active)', val: c.act_dom ? c.act_dom+'d':'—', cls: gc('dom',c.act_dom), sub:'seller motivation' }},
    {{ label:'Avg Price (Active)',   val: fm(c.act_price), cls:'info', sub:'active listings' }},
  ];
  const popFmt = p => p >= 1000000 ? (p/1000000).toFixed(1)+'M' : p >= 1000 ? Math.round(p/1000)+'K' : (p||'—');
  const growthCls = g => g == null ? 'info' : g >= 2 ? 'good' : g >= 0.5 ? 'fair' : g >= 0 ? 'info' : 'poor';
  const contextCards = [
    {{ label:'Deal Score (Hist.)',   val: c.inact_score ? fi(c.inact_score)+'/100':'—', cls: gc('score',c.inact_score), sub:'avg across inactive listings' }},
    {{ label:'Cap Rate (Hist.)',     val: fp(c.inact_cap), cls: gc('cap',c.inact_cap),  sub:'historical market rate' }},
    {{ label:'CoCR (Hist.)',         val: fp(c.inact_coc), cls: gc('coc',c.inact_coc),  sub:'historical returns' }},
    {{ label:'Cap Rate Trend',       val: trendArrow + ' ' + (c.cap_trend > 0 ? '+':'') + fp(c.cap_trend), cls: trendCls, sub:'active vs historical' }},
    {{ label:'Data Confidence',      val: confPctStr,      cls: confCls, sub:`n/(n+k) · ${{c.total}} total props` }},
    {{ label:'Best Deal Score',      val: c.best_score ? fi(c.best_score)+'/100':'—', cls: gc('score',c.best_score), sub:'ceiling — any property' }},
    {{ label:'Population (2021)',    val: c.population ? popFmt(c.population) : '—', cls: c.population >= 50000 ? 'good' : c.population >= 10000 ? 'fair' : c.population ? 'info' : 'poor', sub:'Stats Canada 2021 Census' }},
    {{ label:'Pop. Growth (Ann.)',   val: c.pop_growth != null ? (c.pop_growth > 0 ? '+' : '') + c.pop_growth.toFixed(2) + '%/yr' : '—', cls: growthCls(c.pop_growth), sub:'2016→2021 annualised' }},
  ];
  function cardHtml(cards) {{
    return cards.map(cd => `
      <div class="detail-card">
        <div class="detail-card-label">${{cd.label}}</div>
        <div class="detail-card-val ${{cd.cls}}">${{cd.val}}</div>
        <div class="detail-card-sub">${{cd.sub}}</div>
      </div>`).join('');
  }}
  function norm(v, lo, hi) {{ return hi===lo ? 0 : Math.max(0, Math.min(1, (v-lo)/(hi-lo))); }}
  const T = {thresholds_json};
  function t(key, lo, hi) {{ return T[key] || [lo, hi]; }}
  function tn(v, key, lo, hi) {{ const [l,h] = t(key,lo,hi); return norm(v,l,h); }}
  function log10PopScore(pop) {{ const [l,h] = t('pop_score',3.0,5.7); return pop > 0 ? norm(Math.log10(pop),l,h) : 0; }}
  const factors = [
    {{ label:'Cap Rate (Active)',    w:0.25, raw: tn(c.act_cap,   'act_cap',   3,  10) * 0.25 * 100, src:'active' }},
    {{ label:'CoCR (Active)',        w:0.20, raw: tn(c.act_coc,   'act_coc',   0,  15) * 0.20 * 100, src:'active' }},
    {{ label:'Active Volume',        w:0.20, raw: tn(c.active,    'n_active',  1,  10) * 0.20 * 100, src:'active' }},
    {{ label:'Price Drop (Active)',  w:0.10, raw: tn(c.act_drop,  'act_drop',  0,  15) * 0.10 * 100, src:'active' }},
    {{ label:'Days Listed (Active)', w:0.10, raw: tn(c.act_dom,   'act_dom',  30, 180) * 0.10 * 100, src:'active' }},
    {{ label:'Hist. Cap Rate',       w:0.05, raw: tn(c.inact_cap, 'inact_cap', 3,  10) * 0.05 * 100, src:'inactive' }},
    {{ label:'Cap Rate Trend',       w:0.05, raw: tn(c.cap_trend, 'cap_trend',-3,   3) * 0.05 * 100, src:'cross' }},
    {{ label:'Population Size',      w:0.05, raw: log10PopScore(c.population||0)        * 0.05 * 100, src:'demo' }},
    {{ label:'Pop. Growth Rate',     w:0.10, raw: (c.pop_growth != null ? tn(c.pop_growth,'growth_score',-1.0,3.0) : 0) * 0.10 * 100, src:'demo' }},
  ];
  const srcColor = {{ active:'var(--green)', inactive:'var(--amber)', cross:'var(--muted)', demo:'#7c9fbf' }};
  const maxRaw = Math.max(...factors.map(f => f.raw), 1);
  const confPct = ((c.confidence || 1) * 100).toFixed(0);
  const factorBars = factors
    .sort((a,b) => b.raw - a.raw)
    .map(f => {{
      const pct = (f.raw / maxRaw * 100).toFixed(0);
      return `<div class="factor-bar-row">
        <span class="factor-bar-label">
          ${{f.label}}
          <span style="color:${{srcColor[f.src]}};font-size:9px;margin-left:3px">[${{f.src}}]</span>
          <span style="color:var(--gold);font-size:9px">(${{(f.w*100).toFixed(0)}}%)</span>
        </span>
        <div class="factor-bar-track"><div class="factor-bar-fill" style="width:${{pct}}%;background:${{srcColor[f.src]}}"></div></div>
        <span class="factor-bar-right">${{f.raw.toFixed(1)}} pts</span>
      </div>`;
    }}).join('') + `
    <div class="factor-bar-row" style="margin-top:0.5rem;border-top:1px dashed var(--rule);padding-top:0.5rem">
      <span class="factor-bar-label" style="color:var(--ink);font-weight:500">
        Data Confidence
        <span style="font-size:9px;color:var(--muted);font-weight:normal"> (scales final score)</span>
      </span>
      <div class="factor-bar-track"><div class="factor-bar-fill" style="width:${{confPct}}%;background:var(--ink)"></div></div>
      <span class="factor-bar-right" style="color:var(--ink)">${{confPct}}% · ${{c.total}} prop${{c.total===1?'':'s'}}</span>
    </div>`;
  return `<div class="city-row ${{rankClass}}" id="city-${{i}}">
    <div class="city-row-main" onclick="toggleCity(${{i}})">
      <div class="rank-num">#${{rank}}</div>
      <div class="city-info">
        <div class="city-name">${{c.city}} <span class="chevron">▼</span></div>
        <div class="city-pills">
          <span class="pill active">${{c.active}} active</span>
          ${{c.inactive ? `<span class="pill inactive">${{c.inactive}} inactive</span>` : ''}}
          ${{typeStr ? `<span class="pill">${{typeStr}}</span>` : ''}}
        </div>
      </div>
      <div class="city-score-col">
        <div class="city-opp-num" style="color:${{barColor}}">${{c.opportunity.toFixed(0)}}</div>
        <div class="city-opp-label">/ 100 · ${{gradeLabel}}</div>
      </div>
      <div class="city-metrics">
        <div class="opp-bar-track">
          <div class="opp-bar-fill" style="width:${{barW}}%;background:${{barColor}}"></div>
        </div>
        <div class="mini-stats">${{miniStats}}</div>
      </div>
    </div>
    <div class="city-detail">
      <div class="detail-verdict">${{buildVerdict(c, rank)}}</div>
      <div class="detail-section-title">Active Listings — Actionable Now</div>
      <div class="detail-grid">${{cardHtml(activeCards)}}</div>
      <div class="detail-section-title" style="margin-top:1rem">Historical Context — Inactive Listings</div>
      <div class="detail-grid">${{cardHtml(contextCards)}}</div>
      <div class="factor-section-title" style="margin-top:1.2rem">
        Score contributions &nbsp;
        <span style="color:var(--green)">[active]</span>
        <span style="color:var(--amber)"> [inactive]</span>
        <span style="color:var(--gold)"> [structure]</span>
        <span style="color:var(--muted)"> [cross]</span>
      </div>
      ${{factorBars}}
    </div>
  </div>`;
}}

function toggleCity(i) {{
  const row = document.getElementById('city-' + i);
  row.classList.toggle('open');
}}

renderAll();
</script>
</body>
</html>"""

    def open_in_browser(self, cities: list):
        """Build the report and open it in the default browser."""
        html = self.render(cities)
        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.html', delete=False,
            prefix='city_report_', encoding='utf-8'
        )
        tmp.write(html)
        tmp.close()
        webbrowser.open(f'file://{tmp.name}')
        print(f"\n  City report opened in browser.")
        print(f"  File saved to: {tmp.name}")
