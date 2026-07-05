# Commercial Property Analyser v1.0

A terminal-based tool for evaluating Canadian commercial real estate investments. It calculates key performance metrics (Cap Rate, NOI, DSCR, IRR, Cash-on-Cash, Equity Multiple, and more), scores properties against configurable thresholds, ranks cities by investment opportunity, and generates HTML reports — all from a single interactive menu driven by local JSON data files.

---

## Quick Start

```bash
# 1. Install dependencies (Python 3.11+)
pip install -r requirements.txt

# 2. Run the application
python main.py
```

No database or internet connection required. All data is stored in the `json/` directory.

---

## Directory Structure

```
commercial_property_analyser_v2/
├── main.py                    # Entry point
├── utils.py                   # Shared address helpers
├── conftest.py                # pytest sys.path setup
├── pytest.ini                 # Test runner config + coverage flags
├── .coveragerc                # Coverage source/omit/threshold rules
├── requirements.txt           # numpy-financial (runtime), pytest, pytest-cov
│
├── config/                    # House underwriting assumptions (editable, no code changes needed)
│   └── underwriting.json      # NOI growth default, exit cap spread/aging bps, inflation rate
│
├── models/                    # Plain data containers (no logic)
│   ├── property_input.py      # PropertyInput, UnitMix dataclasses
│   └── report_row.py          # ReportRow (metric / value / grade)
│
├── data/                      # JSON persistence layer
│   └── store.py               # DataStore, CommercialRentLoader, ResidentialRentLoader
│
├── config/                    # House underwriting assumptions (editable, no code changes needed)
│   └── underwriting.json      # NOI growth, exit-cap spread, stress test, data-confidence shape
│
├── analysis/                  # Core financial analysis engine
│   ├── analyzer.py            # CommercialPropertyAnalyzer — orchestrates all metric groups
│   ├── mortgage.py            # MortgageCalculator, DaysOnMarketCalculator
│   ├── rent_resolver.py       # RentResolver — derives annual rent from inputs or market data;
│   │                          #   flags residential lines priced at a city-wide average as imputed
│   ├── underwriting_config.py # load_underwriting_config() — loader/validator for config/underwriting.json
│   ├                          # Loads config/underwriting.json (NOI growth, exit cap spread, inflation)
│   └── metrics/               # Individual metric calculators
│       ├── income.py          # NOI, Cap Rate, Gross/Effective Rent, GRM, Cap Rate Risk Check,
│       │                      #   IncomeConfidenceMetrics (verified vs. imputed income, confidence multiplier)
│       ├── cash_flow.py       # Annual Cash Flow, CoCR, Cash Invested, DSCR, rate-shock Stress Test
│       ├── returns.py         # IRR, Equity Multiple, CELOC
│       ├── pricing.py         # Price/sqft, Price Drop %, Loan-to-Value
│       ├── property_types.py  # HotelMetrics (RevPAR, ADR, GOP), IndustrialMetrics
│       └── grader.py          # Converts numeric values to GOOD / FAIR / POOR grades
│
├── scoring/                   # Investment scoring and city ranking
│   ├── scorer.py              # PropertyScorer — 0-100 weighted score per property
│   └── city_ranker.py         # CityRanker — aggregates scores into city opportunity rankings
│
├── reporting/                 # Output generation
│   ├── printer.py             # ReportPrinter — terminal output (list, analysis view)
│   ├── property_report.py     # PropertyReportGenerator — HTML property investment report
│   ├── city_report.py         # CityReportGenerator — HTML city opportunity report
│   ├── price_check_report.py  # PriceCheckReportGenerator — realtor.ca price sweep results
│   ├── deal_watchlist_report.py   # DealWatchlistReportGenerator — scored deals over a threshold
│   ├── negotiation_report.py  # NegotiationReportGenerator — bid anchors for active deals
│   ├── vacancy_report.py      # VacancyReportGenerator — cash flow at 100/85/75/60% occupancy
│   ├── price_drop_report.py   # PriceDropReportGenerator — listings cut below original list
│   └── benchmark_report.py    # BenchmarkReportGenerator — $/sqft & cap rate vs peer comps
│
├── ui/                        # Interactive terminal menu (excluded from coverage)
│   ├── menu.py                # PropertyMenu — main loop, CRUD, analysis view, helpers
│   ├── rate_editor.py         # RateEditorMixin — commercial & residential rate editing
│   ├── config_editor.py       # ConfigEditorMixin — scoring weights, distances, demographics
│   └── csv_handler.py         # CsvHandlerMixin — CSV import and template export
│
├── json/                      # Runtime data files (auto-created on first use)
│   ├── properties.json        # Saved property records with full analysis results
│   ├── commercial_rents.json  # Commercial rent rates ($/sqft/yr) by city and type
│   ├── residential_rents.json # Residential rent rates ($/mo) by city and unit type
│   ├── score_weights.json     # Scoring weights and thresholds (editable via menu → s)
│   ├── city_distances.json    # Distance from each city to its nearest regional centre
│   ├── city_demographics.json # Population and annual growth data per city
│   └── missing_rent_data.json # Cities with incomplete rent data, tracked for follow-up
│
└── tests/                     # Unit and integration tests (99%+ branch coverage)
    ├── test_models.py
    ├── test_utils.py
    ├── test_analysis_analyzer.py
    ├── test_analysis_mortgage.py
    ├── test_analysis_rent_resolver.py
    ├── test_metrics_income.py
    ├── test_metrics_cash_flow.py
    ├── test_metrics_returns.py
    ├── test_metrics_pricing.py
    ├── test_consistency_invariants.py
    ├── test_metrics_property_types.py
    ├── test_metrics_grader.py
    ├── test_data_store.py
    ├── test_scoring_scorer.py
    ├── test_scoring_scorer_extended.py
    ├── test_scoring_city_ranker.py
    ├── test_reporting_printer.py
    ├── test_reporting_generators.py
    ├── test_deal_watchlist_report.py
    ├── test_negotiation_report.py
    ├── test_vacancy_report.py
    ├── test_price_drop_report.py
    └── test_benchmark_report.py
```

---

## File Reference

### Root

| File | Purpose |
|---|---|
| `main.py` | Bootstraps `DataStore`, `RentResolver`, and `PropertyMenu`, then starts the menu loop. Sets the working directory to the project root so all relative JSON paths resolve correctly. |
| `utils.py` | `_display_address` formats an address for display; `_parse_address_sort` extracts street name and number for alphabetic property list sorting. |
| `conftest.py` | Adds the project root to `sys.path` so absolute imports work correctly during `pytest` runs. |
| `pytest.ini` | Configures test discovery, coverage sources, branch coverage, and XML/terminal report output. Coverage flags are in `addopts` so VS Code's Coverage Gutters extension picks up `coverage.xml` automatically on every test run. |
| `.coveragerc` | Excludes `main.py`, `ui/`, and `tests/` from coverage measurement. Enforces a 90% minimum. |
| `requirements.txt` | `numpy-financial` (runtime — used by `returns.py` for IRR via `numpy_financial.irr`, which pulls in `numpy`), plus `pytest` and `pytest-cov` for tests. Otherwise the application uses only the Python standard library. |

---

### `config/`

| File | Purpose |
|---|---|
| `underwriting.json` | House underwriting assumptions, loaded by `analysis/underwriting_config.py`: `noi_growth_default` (flat annual NOI growth applied to every property unless a property has a manual `noi_growth_rate` override), `exit_cap_spread_bps` / `exit_cap_aging_bps_per_year` (feed `ExitCapEstimator`), and `inflation_rate` (bands the NOI Growth Assumption grade). Missing file/keys raise `UnderwritingConfigError` rather than falling back to a hardcoded literal — change a value here and every property's returns move on the next analysis, no code edit required. |

---

### `models/`

Plain dataclasses with no business logic or I/O.

| File | Key Classes |
|---|---|
| `property_input.py` | `PropertyInput` — all user-supplied fields for a property (address, price, rates, unit mix, hotel/industrial details). `UnitMix` — residential unit breakdown by bedroom count and floor count. |
| `report_row.py` | `ReportRow(metric, value, grade)` — one row in a printed or saved analysis report. |

---

### `data/`

| File | Purpose |
|---|---|
| `store.py` | **`DataStore`** — reads and writes all JSON files under `json/`. Manages property CRUD (`load_properties`, `save_property`, `update_property`, `delete_property`), commercial and residential rent persistence, city tracking, and the missing-rent registry. **`CommercialRentLoader`** / **`ResidentialRentLoader`** — thin adapters that wrap `DataStore` for dependency injection into `RentResolver`. |

---

### `config/`

| File | Purpose |
|---|---|
| `underwriting.json` | House underwriting assumptions, loaded and validated by `analysis/underwriting_config.py` (missing file/keys are a hard error, not a silent fallback). Every tunable risk constant lives here — nothing is hardcoded in the Python: `noi_growth_default`, `exit_cap_spread_bps`, `exit_cap_aging_bps_per_year`, `inflation_rate`, `stress_rate_bump` / `stress_min_dscr` (rate-shock stress test), `confidence_uncertainty_start` / `confidence_steepness` / `confidence_floor` (data-confidence multiplier shape), `cap_rate_risk_threshold_pct` / `cap_rate_risk_slope` / `cap_rate_risk_max_haircut` (graduated high-cap-rate haircut), `dom_normal_days` / `dom_stale_days` / `drop_modest_pct` / `drop_large_pct` / `drop_severe_pct` (DOM/Price Drop bands), `market_signal_verified_income_threshold_pct` / `dom_stale_confidence_factor` / `price_drop_confidence_factor` / `joint_signal_confidence_factor` / `thin_market_confidence_factor` / `market_signal_confidence_floor` / `amplifier_engage_min_signals` / `low_income_conf_always_engages_amplifier` (market-signal confidence amplifier), `liquidity_distance_reference_km` / `liquidity_population_reference` / `liquidity_weight_distance` / `liquidity_weight_population` / `liquidity_weight_growth` / `liquidity_liquid_threshold` / `liquidity_thin_threshold` (market-liquidity proxy). |

---

### `analysis/`

| File | Purpose |
|---|---|
| `analyzer.py` | **`CommercialPropertyAnalyzer`** — the central analysis orchestrator. Takes a `PropertyInput` and a `RentResolver`, resolves rent, constructs all metric groups, and exposes `report()` (list of `ReportRow`) and `to_record()` (dict ready for `DataStore`). `_resolve_noi_growth` picks a property's manual `noi_growth_rate` override if set, else the flat `noi_growth_default` house assumption from `config/underwriting.json` — no per-city rate; `json/city_demographics.json` population growth is not used here (only by `scoring/`). |
| `mortgage.py` | **`MortgageCalculator`** — monthly payment, annual payment, down payment, loan balance, and outstanding principal at end of hold period. Compounding is province-aware: every Canadian jurisdiction (all 10 provinces + 3 territories, matched by 2-letter code **or** spelled-out name, e.g. "Ontario"/"Québec") uses semi-annual compounding per the Interest Act s. 6; anything else falls back to monthly. **`DaysOnMarketCalculator`** — days between the listing date and today. |
| `rent_resolver.py` | **`RentResolver`** — determines effective annual rent in priority order: explicit `annual_rent` on the property → market commercial rates × sqft → market residential rates × unit mix. Logs cities with missing market data to `DataStore` for follow-up. |
| `underwriting_config.py` | Loads and caches `config/underwriting.json`. Hard-fails (`UnderwritingConfigError`) if the file or a required key (`noi_growth_default`, `exit_cap_spread_bps`, `inflation_rate`) is missing, rather than silently falling back to a hardcoded default. |

#### `analysis/metrics/`

Each module exposes a class whose `rows()` method returns a list of `ReportRow` objects included in the final report.

| File | Metrics Produced |
|---|---|
| `income.py` | Gross Rent, Effective Gross Income, Estimated Expenses, NOI, Entry Cap Rate, Estimated Exit NOI, GRM, Cap Rate Risk Check (flags cap rates well above the regional norm), Income Verification / Confidence Multiplier (data-confidence axis — verified vs. imputed income share) |
| `cash_flow.py` | Annual Cash Flow, Cash-on-Cash Return (CoCR), Cash Invested, DSCR, Stress Test (DSCR re-priced at `interest_rate + stress_rate_bump`, graded PASS/FAIL against `stress_min_dscr`) |
| `returns.py` | IRR (`numpy_financial.irr`), Equity Multiple, CELOC Speed Score and Seller Bleed (informational listing-economics rows — not inputs to the property score), Market Staleness (DOM) |
| `pricing.py` | Price/Sq Ft (labeled with its scope — e.g. "Ground Floor" when the mixed-use commercial component is priced separately from the whole building), Original Price, Price Drop %, Loan-to-Value |
| `property_types.py` | **Hotel**: Rooms, ADR, Occupancy %, RevPAR, CPOR, Annual Revenue, GOP grade. **Industrial**: Warehouse/office/yard sqft, dock & drive-in door counts, clear height, blended rate, estimated annual rent. |
| `grader.py` | `grade(metric, value)` — maps a numeric value to `"GOOD"`, `"FAIR"`, `"POOR"`, or `""` using per-metric thresholds. |

**Data integrity — no silent fallbacks.** The metrics never emit a plausible-looking
number in place of a broken one. Mandatory inputs fail loudly: a missing/zero square
footage or a zero exit cap rate raises `ValueError` (callers already route these to a
partial "no analysis" record rather than crashing). Where a zero is a legitimate edge
rather than bad data, the row is flagged instead of faked: GRM shows `N/A (no rent)` for
a property in a city with no rent data yet; DSCR and the stress test show `N/A (no debt)`
for an all-cash deal; CoCR, Equity Multiple, and CELOC show `N/A (no cash invested)`.
`tests/test_consistency_invariants.py` drives a matrix of Canadian configurations through
the real analyzer and asserts the metric groups stay internally consistent (e.g. annual
debt service == monthly payment × 12, `exit_price × exit_cap == terminal NOI`), and locks
the Canadian semi-annual compounding convention against a regression to US monthly.

**Independent risk axes.** Risk is deliberately kept on separate signals rather
than collapsed into one opaque number:
- **Structural/debt risk** — DSCR, Break-Even NOI/Occupancy, and the rate-shock **Stress Test**
  (`cash_flow.py`): the mortgage payment re-priced at `interest_rate + stress_rate_bump` (default
  +2 percentage points, config-driven), graded PASS/FAIL against `stress_min_dscr`.
- **Data confidence** — `IncomeConfidenceMetrics` (`income.py`): how much of a property's income
  is stated in the listing versus imputed from a city-wide bedroom-type average (the "Unknown"
  unit-type bucket is the imputed signal). Imputed lines carry the coefficient of variation of the
  *same* city rent sample used to build the average — no invented risk premium. Feeds a small,
  bounded `confidence_multiplier` onto the overall property score only; DSCR/cap rate/NOI/IRR are
  never touched.
- **Pricing/cap-rate signal** — the **Cap Rate Risk Check** row (`income.py`): a cap rate above
  `cap_rate_risk_threshold_pct` (Canadian commercial prime trades ~5–7%) is flagged as a market
  signal of illiquidity/vacancy/value-erosion risk rather than read as pure upside. It's a soft
  flag — it does not fail the deal — and feeds the same bounded confidence multiplier via a
  graduated (not cliff) haircut: 0 at/below the threshold, growing linearly at
  `cap_rate_risk_slope` per point above it, capped at `cap_rate_risk_max_haircut` no matter how
  high the cap rate goes.
- **Market/listing signals** — DOM ("Market Staleness") and Price Drop % (`scoring/scorer.py`)
  carry no fixed sign: a long time-on-market or big price cut can mean opportunity (motivated
  seller) or warning (something's wrong), depending on the rest of the deal. Both are weighted
  **zero** in the raw score (`json/score_weights.json`) — they never move the score on their own.
  Instead they **amplify** the existing confidence haircut above, but only when there's genuine
  low confidence: income confidence (`is_high_income_conf`) is INCOME-only — verified income vs.
  `market_signal_verified_income_threshold_pct` — and does not look at cap rate, since cap-rate
  risk already gets its own direct haircut above and would otherwise be double-counted. The
  amplifier engages when income confidence is low, or when at least
  `amplifier_engage_min_signals` independent risk signals stack up together (e.g. a flagged cap
  rate *and* a thin market) — a lone cap-rate flag on an otherwise clean, verified deal does not
  open it. A clean, liquid, fully-verified deal with a stale, discounted listing scores exactly
  as it would without those signals; a low-confidence or thin-market deal with the same signals
  gets a deeper, floor-bounded haircut.
  Always surfaced as a neutral **Deal Context** panel (DOM/drop/liquidity bands, income
  verification %, and a factual — never a buy/pass — "Read" line) in the property report modal, so
  a human makes the final opportunity-vs-warning call.

All thresholds/weights/shapes for these axes live in `config/underwriting.json`.

---

### `scoring/`

| File | Purpose |
|---|---|
| `scorer.py` | **`PropertyScorer`** — produces a 0–100 investment score from a saved property record. Weights nine components (Cap Rate, CoCR, DSCR, IRR, Equity Multiple, Cash Flow, Price Drop, DOM, Location); Price Drop and DOM default to **zero** weight in the shipped config (see "Market/listing signals" above) and instead amplify the confidence multiplier via `_dom_band` / `_drop_band` / `_liquidity_band`. Weights and floor/ceiling thresholds are configurable and persisted in `json/score_weights.json`. Also provides `solve_targets()` — binary search over each lever (asking price, rent, interest rate, down payment) to find the value that would push the score to ≥ 99.5/100. |
| `city_ranker.py` | **`CityRanker`** — groups scored properties by city, computes per-city signals (avg score, best score, volume, cap rate, price drop, DOM, CoCR), applies configurable city-level signal weights, then adjusts the opportunity score toward a neutral 50 using a confidence factor `n / (n + k)` — cities with few properties are pulled toward the mean to avoid overconfident rankings on small samples. |

---

### `reporting/`

| File | Purpose |
|---|---|
| `printer.py` | **`ReportPrinter`** — terminal-only output. `print_report(analyzer)` prints a formatted metric table to stdout. `list_properties(store)` prints a numbered property list sorted by city then street name/number. |
| `property_report.py` | **`PropertyReportGenerator`** — renders a self-contained HTML file with a sortable, filterable table of all properties. Each row shows the investment score, per-component breakdown, financial metrics, and the target asking price / rent / interest rate / down payment that would achieve a near-perfect score. The modal for each property includes a neutral **Deal Context** panel (DOM/price-drop/liquidity bands, income verification %, and a factual "Read" line). Opens in the default browser. |
| `city_report.py` | **`CityReportGenerator`** — renders a self-contained HTML city opportunity report ranked by opportunity score (geometric mean of deal quality × market depth). Shows volume, avg/best scores, key financial signals, inactive-listing comparables, and demographic data where available. The per-city "Score contributions" breakdown is the actual factor contribution emitted by `CityRanker` (no recomputation), so it always matches the configured weights. Opens in the default browser. |
| `price_check_report.py` | **`PriceCheckReportGenerator`** — renders the results of a realtor.ca price sweep: each stored property classified as price dropped / risen / unchanged / not found / not checked, with the stored vs found price and delta. |
| `deal_watchlist_report.py` | **`DealWatchlistReportGenerator`** — an interactive table of **active**, scored deals. Embeds the deals as JSON and renders client-side: every column is click-to-sort and the list filters live by minimum score, cap rate, and price drop. Surfaces cap rate, cash-on-cash, IRR, annual cash flow, DSCR, days-on-market and price drop. |
| `negotiation_report.py` | **`NegotiationReportGenerator`** — for each active, scored property, the single lever value (price / rent / interest rate / down payment) that would alone lift the deal to a perfect score, with the gap from today's asking. Uses the scorer's `solve_targets`. Interactive: click-to-sort columns and live filters for minimum score, cap rate, and negotiation room. |
| `vacancy_report.py` | **`VacancyReportGenerator`** — stress-tests each income property by recomputing cap rate and annual cash flow at 100 / 85 / 75 / 60% occupancy, holding debt service constant. Debt service comes from the province-aware `MortgageCalculator`. Interactive: click-to-sort columns and filters for minimum score and "stays cash-flow positive at a chosen occupancy". |
| `price_drop_report.py` | **`PriceDropReportGenerator`** — listings whose current asking has fallen below their original list price. Interactive: click-to-sort columns (default largest drop first) and filters for minimum drop % and status. |
| `benchmark_report.py` | **`BenchmarkReportGenerator`** — compares each property's $/sqft and cap rate against the average of comparable listings, preferring the tightest comp set available (city+type → province+type → type-wide) and excluding the property from its own average. Flags each as underpriced / at market / overpriced. Interactive: click-to-sort columns and filters for verdict and minimum comp count. |

---

### `ui/`

The interactive terminal menu. Excluded from test coverage — all logic that can be unit-tested lives in the layers below. `PropertyMenu` inherits from three mixins so each file stays under 1 000 lines.

| File | Purpose |
|---|---|
| `menu.py` | **`PropertyMenu`** — main menu loop (`run()`), property CRUD actions (`_add`, `_edit`, `_delete`, `_view`, `_list`), HTML report launchers (`_open_report`, `_open_city_report`, `_open_watchlist_report`, `_open_negotiation_report`, `_open_vacancy_report`, `_open_price_drop_report`, `_open_benchmark_report`), the realtor.ca price check (`_price_check`), bulk re-analysis (`_reanalyze_all`, `_reanalyze_city`), and core helpers (`_prompt_property`, `_record_to_prop`, `_sorted_props`, `_pick_index`). |
| `rate_editor.py` | **`RateEditorMixin`** — menu options 7 & 8. Edit or add commercial rent rates ($/sqft/yr, split by property type) and residential rent rates ($/mo, split by bedroom count) per city. Automatically re-analyses all properties in that city after saving. |
| `config_editor.py` | **`ConfigEditorMixin`** — menu option `s`. Edit per-component scoring weights and floor/ceiling thresholds. Sub-options let you manage city distances to regional centres (used by the Location scoring component) and city demographic data (population, annual growth). |
| `csv_handler.py` | **`CsvHandlerMixin`** — menu option 9. Imports properties from a CSV file (auto-detects encoding, handles files with or without a header row). Also exports a blank template CSV so users know the expected column order. |

---

### `json/`

All files are created automatically on first use. They are plain UTF-8 JSON and can be edited manually if needed.

| File | Schema Summary |
|---|---|
| `properties.json` | Array of property records. Each record is the output of `CommercialPropertyAnalyzer.to_record()` — all input fields plus a `results` array of `{metric, value, grade}` objects. |
| `commercial_rents.json` | `{ "cities": { "Ottawa": { "province": "ON", "types": { "Office": 22.5, "Retail": 28.0 } } } }` |
| `residential_rents.json` | `{ "cities": { "Ottawa": { "province": "ON", "units": { "bachelor": 1400, "one_br": 1700, "two_br": 2100 } } } }` |
| `score_weights.json` | Scoring weights (active, non-zero weights are renormalized to sum to 1.0 — Price Drop and DOM ship at zero, see "Market/listing signals" above), floor/ceiling thresholds per metric, city-level signal weights, and confidence smoothing constant `k`. |
| `city_distances.json` | `{ "Cobourg": { "nearest_centre": "Toronto", "distance_km": 100 } }` |
| `city_demographics.json` | `{ "cobourg": { "population": 20000, "population_2016": 19000, "growth_pct_annual": 1.02, "source": "Stats Canada 2021 Census" } }` — census population growth, used by `scoring/city_ranker.py` for city opportunity depth and by `scoring/scorer.py` (with `city_distances.json`) as one input to the market-liquidity proxy that gates the DOM/Price-Drop confidence amplifier. Not used as a rent/NOI growth assumption (see `config/underwriting.json`). |
| `missing_rent_data.json` | Tracks which cities are missing commercial or residential rent data so the menu can prompt the user to fill them in. |

---

## Menu Reference

```
  1  List all properties
  2  View analysis for a property
  3  Add a new property
  u  Add a property from a realtor.ca URL
  4  Edit a property
  5  Delete a property
  6  Open investment report in browser
  c  Open city opportunity report
  w  Open deal watchlist
  n  Open negotiation targets
  v  Open vacancy sensitivity
  d  Open price drop alerts
  b  Open cap-rate & $/sqft benchmarking
  p  Check realtor.ca prices (all properties)
  7  Edit commercial rent rates
  8  Edit residential rent rates
  9  Import properties from CSV
  r  Re-analyze all properties
  s  Scoring formula & weights
  0  Exit
```

### Key Workflows

**Adding your first property (option 3)**
Enter the address (must include city and province, e.g. `123 Main St, Ottawa ON`), listing price, MLS number, property type, square footage, unit mix if residential, and financial assumptions (down payment %, interest rate, amortisation term, hold period, expense ratio). The analyser resolves rent from market data if available; otherwise it saves the property with partial results and prompts you to add rates via option 7 or 8.

**Adding rent data (options 7 / 8)**
Enter commercial rates in $/sqft/year, broken down by type (Office, Retail, Industrial, Mixed-Use). Enter residential rates in $/month by bedroom count (Bachelor through 4BR). After saving, every property in that city is automatically re-analysed with the new data.

**Importing from CSV (option 9)**
Type `template` at the path prompt to save a pre-filled example CSV. Populate it and re-import. Rows missing an address, MLS number, original price, or square footage are skipped with a logged error; all others are saved even if a full analysis cannot be run.

**Scoring & weights (option `s`)**
Adjust the weight (0–100%) of each of the nine **property** scoring components and set the floor (score = 0) and ceiling (score = 10) values. Weights are normalised automatically, so disabling a component (set weight to 0) redistributes its share across the rest. Sub-options `d` and `m` manage city distances and demographic data.

A separate sub-editor tunes the **city opportunity** formula. A city must be good on **both** axes — profitable deals *and* enough of them — so the score is the weighted **geometric mean** of quality and depth: `opportunity = 100 · quality^quality_exp · depth^depth_exp`. Because it's multiplicative, neither axis can carry the other: a huge market full of weak deals scores low, and a single great listing scores low.

- **Quality** (0–1) is the renormalised weighted blend of deal/market metrics (independent of city size), feeding the report's "Deal-quality contributions" breakdown:
  - *Active listings* (still for sale): cap rate, cash-on-cash, IRR, DSCR, annual cash flow, price drop from original list, days on market.
  - *Inactive listings* (off-market, treated as transacted for demand signals): cap rate, absorption (inactive share = demand signal), price trend (active asking vs inactive = appreciation signal).
  - *Cross / structural*: active-vs-inactive cap-rate trend and the single best deal score.
  - *Demographics* (where available): population (log-scaled) and annual population growth.
- **Depth** (0–1) grows log-scaled with active listing count (`opportunity_depth_ref`, the count earning ~full depth, default 50). Its weight is `opportunity_depth_exp` (default 0.4; quality gets the rest).
- **Outlier screen**: active listings whose estimated rent implies an implausible cap rate (`outlier_max_cap_rate`, default 12%) or cash-on-cash (`outlier_max_coc`, default 25%) are kept in the inventory count but dropped from the income averages, so a bad estimate can't inflate a city.

The displayed score is the **honest raw value** (geometric mean, realistic top ~60) — not rescaled, so a weak field of markets reads as mostly Fair/Weak rather than being flattered (grades: Excellent ≥75, Good ≥55, Fair ≥35). The browser price-range filter keeps a city if **any** of its active listings fall in the range (not just the city average). `confidence_k` now only drives the displayed "Data Confidence" indicator; it no longer scales the score. All knobs live in `json/score_weights.json`.

**HTML reports (options 6 / c)**
Option 6 opens a property report in your browser — sortable by any column, showing score breakdowns and the target adjustments needed to reach a near-perfect score. Option `c` opens a city opportunity ranking (geometric mean of deal quality and market depth), with an accurate per-factor quality breakdown and inactive-listing comparables. The price-range filter shows a city only if it has active listings in range, and the shown count/avg price reflect that in-range subset.

**Focused reports (options w / n / v / d / b)**
Each opens a single-purpose HTML report in the browser, built from the same scored property set. All five are interactive: **click any column header to sort** (click again to reverse), plus the report-specific filters noted below.

- **`w` Deal Watchlist** — active, scored deals with the key return metrics. Filters: minimum score (starts at 55), cap rate, and price drop.
- **`n` Negotiation Targets** — for each active, scored deal, the one lever (price / rent / rate / down payment) that alone would make it a perfect score, plus the gap from today's asking. Filters: minimum score, cap rate, and negotiation room.
- **`v` Vacancy Sensitivity** — cap rate and annual cash flow for every income property at 100 / 85 / 75 / 60% occupancy, with debt service held constant, to show how much vacancy each deal can absorb. Filters: minimum score, and "stays cash-flow positive at a chosen occupancy".
- **`d` Price Drop Alerts** — listings now priced below their original list price, largest cut first. Filters: minimum drop % and status.
- **`b` Cap-Rate & $/sqft Benchmarking** — every property's price-per-sqft and cap rate against the average of comparable listings (city+type, then province+type, then type-wide), flagged underpriced / at market / overpriced. Filters: verdict and minimum comp count.

**Price check (option p)**
Drives a real browser to look each stored property up on realtor.ca and reports which prices have dropped, risen, or been delisted since you saved them. Progress is checkpointed so a long sweep can be resumed.

---

## Supported Property Types

| Type | Rent Resolution |
|---|---|
| Office, Retail, Mixed-Use, Retail-Office | Commercial rate ($/sqft/yr) × net leasable sqft |
| Industrial | Blended rate across warehouse, office component, and yard sqft |
| Residential, Multi-Family | Residential rate ($/mo) × unit mix by bedroom count × 12 |
| Hotel | ADR × Occupancy % × Rooms × 365, or manual annual revenue |

---

## Running Tests

```bash
# Full suite with branch coverage (generates coverage.xml for VS Code)
python -m pytest

# Quick run without coverage output
python -m pytest --no-cov

# Show only failures with short tracebacks
python -m pytest --tb=short -q
```

Coverage is enforced at 90% minimum by `.coveragerc`. The current suite achieves **99%+ branch coverage** across all non-UI modules.

---

## Metrics Glossary

| Metric | Description |
|---|---|
| **Cap Rate** | NOI ÷ (Asking Price + Construction Cost). Core yield metric — higher is better. |
| **NOI** | Net Operating Income — Effective Gross Income minus estimated operating expenses. |
| **DSCR** | Debt Service Coverage Ratio — NOI ÷ Annual Mortgage Payment. Values below 1.0 mean the property cannot service its debt from income alone. |
| **CoCR** | Cash-on-Cash Return — Annual Cash Flow ÷ Cash Invested. Measures immediate income yield on equity deployed. |
| **IRR** | Internal Rate of Return — annualised return over the hold period, computed by `numpy_financial.irr` on the period cash-flow array (equity out at year 0, operating cash flow each year, plus **net** sale proceeds at exit), so it reflects cash-flow timing. Independent of the Equity Multiple, not back-derived from it. When the stream has no real IRR root (e.g. an underwater exit) the report reads "IRR not meaningful" rather than a substitute number. |
| **Equity Multiple** | Total positive cash returned ÷ Cash Invested, from the same cash-flow array (sale proceeds are **net** of the loan payoff). A value of 2.0× means you doubled your money over the hold period. |
| **NOI Growth Assumption** | The flat annual NOI escalation used to project the cash-flow array and terminal (exit) NOI. Defaults to `noi_growth_default` in `config/underwriting.json` for every property; a property with a manual `noi_growth_rate` override uses that instead. Not derived from city population growth. |
| **GRM** | Gross Rent Multiplier — Asking Price ÷ Annual Gross Rent. Lower is better. |
| **CELOC Speed Score** | (Est. NOI ÷ Cash Invested) × 100. Graded FAST CELOC / CELOC POSSIBLE / LENDER FRICTION / NO CELOC. Informational listing economics — not an input to the property score. |
| **Seller Bleed** | Estimated cumulative carrying cost the seller has absorbed while the listing sat on market: `((Est. Expenses + Annual Mortgage) ÷ 12) × (Days on Market ÷ 30) × Vacancy Rate`. Informational — not an input to the property score. |
| **RevPAR** | Revenue Per Available Room — ADR × Occupancy Rate. Hotel-specific. |
| **CPOR** | Cost Per Occupied Room — Total Operating Cost ÷ Occupied Room-nights. Hotel-specific. |
| **Price Drop** | (Original Price − Asking Price) ÷ Original Price. Carries no fixed sign — weighted zero in the raw score. A large/severe cut (config: `drop_large_pct` / `drop_severe_pct`) instead amplifies the confidence multiplier, but only when the deal isn't already high-confidence and liquid — see "Market/listing signals" above and the Deal Context panel. |
| **DOM** | Days on Market — from listing date to today. Carries no fixed sign — weighted zero in the raw score. A stale listing (config: `dom_stale_days`) instead amplifies the confidence multiplier under the same condition as Price Drop above. |
| **Stress Test** | DSCR recomputed with the mortgage re-priced at `interest_rate + stress_rate_bump` (config, default +2 pp). PASS/FAIL against `stress_min_dscr` (config, default 1.20). A structural/debt-risk check — independent of the confidence rows below. |
| **Income Verification** | % of a property's income stated in the listing ("verified") vs. imputed from a city-wide bedroom-type average rent ("estimated"). Informational — does not alter DSCR, NOI, cap rate, or IRR. |
| **Confidence Multiplier** | A small, bounded multiplier (config-shaped, floor `confidence_floor`) applied to the **overall property score only**, driven by measured income uncertainty (coefficient of variation of the same rent sample used for imputed lines) and, if flagged, the high-cap-rate signal below. 1.0× = fully verified income. |
| **Cap Rate Risk Check** | Flags when Cap Rate exceeds `cap_rate_risk_threshold_pct` (config, default 10%) — a market signal of illiquidity/vacancy/value-erosion risk that a high cap rate alone doesn't otherwise surface. Soft flag; does not fail the deal. |
| **Market Signal Multiplier** | The DOM/Price-Drop confidence amplifier described above (config: `dom_stale_confidence_factor` / `price_drop_confidence_factor` / `joint_signal_confidence_factor` / `thin_market_confidence_factor`, floor `market_signal_confidence_floor`). 1.0× when the signals don't trigger, or when they do but the deal is already high-confidence and liquid. |
| **Market Liquidity** | A config-weighted thinness proxy (`liquidity_*` keys) from distance to the nearest major centre and city population/growth — bands to liquid / moderate / thin. The switch that decides whether a stale/discounted listing reads as opportunity or warning; never an independent score input. |
| **Deal Context** | The property-report panel that surfaces DOM/price-drop/liquidity bands, income verification %, and a neutral, factual "Read" line (never a buy/pass recommendation) — the human-facing view of the market-signal confidence axis. |
