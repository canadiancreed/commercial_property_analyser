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
├── requirements.txt           # pytest, pytest-cov
│
├── models/                    # Plain data containers (no logic)
│   ├── property_input.py      # PropertyInput, UnitMix dataclasses
│   └── report_row.py          # ReportRow (metric / value / grade)
│
├── data/                      # JSON persistence layer
│   └── store.py               # DataStore, CommercialRentLoader, ResidentialRentLoader
│
├── analysis/                  # Core financial analysis engine
│   ├── analyzer.py            # CommercialPropertyAnalyzer — orchestrates all metric groups
│   ├── mortgage.py            # MortgageCalculator, DaysOnMarketCalculator
│   ├── rent_resolver.py       # RentResolver — derives annual rent from inputs or market data
│   └── metrics/               # Individual metric calculators
│       ├── income.py          # NOI, Cap Rate, Gross/Effective Rent, GRM
│       ├── cash_flow.py       # Annual Cash Flow, CoCR, Cash Invested, DSCR
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
│   └── city_report.py         # CityReportGenerator — HTML city opportunity report
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
    ├── test_metrics_property_types.py
    ├── test_metrics_grader.py
    ├── test_data_store.py
    ├── test_scoring_scorer.py
    ├── test_scoring_scorer_extended.py
    ├── test_scoring_city_ranker.py
    ├── test_reporting_printer.py
    └── test_reporting_generators.py
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
| `requirements.txt` | `pytest` and `pytest-cov`. No other runtime dependencies — the application uses only the Python standard library. |

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

### `analysis/`

| File | Purpose |
|---|---|
| `analyzer.py` | **`CommercialPropertyAnalyzer`** — the central analysis orchestrator. Takes a `PropertyInput` and a `RentResolver`, resolves rent, constructs all metric groups, and exposes `report()` (list of `ReportRow`) and `to_record()` (dict ready for `DataStore`). |
| `mortgage.py` | **`MortgageCalculator`** — monthly payment, annual payment, down payment, loan balance, and outstanding principal at end of hold period. **`DaysOnMarketCalculator`** — days between the listing date and today. |
| `rent_resolver.py` | **`RentResolver`** — determines effective annual rent in priority order: explicit `annual_rent` on the property → market commercial rates × sqft → market residential rates × unit mix. Logs cities with missing market data to `DataStore` for follow-up. |

#### `analysis/metrics/`

Each module exposes a class whose `rows()` method returns a list of `ReportRow` objects included in the final report.

| File | Metrics Produced |
|---|---|
| `income.py` | Gross Rent, Effective Gross Income, Estimated Expenses, NOI, Entry Cap Rate, Estimated Exit NOI, GRM |
| `cash_flow.py` | Annual Cash Flow, Cash-on-Cash Return (CoCR), Cash Invested, DSCR |
| `returns.py` | IRR (Newton-Raphson), Equity Multiple, CELOC |
| `pricing.py` | Price per sqft, Original Price, Price Drop %, Loan-to-Value |
| `property_types.py` | **Hotel**: Rooms, ADR, Occupancy %, RevPAR, CPOR, Annual Revenue, GOP grade. **Industrial**: Warehouse/office/yard sqft, dock & drive-in door counts, clear height, blended rate, estimated annual rent. |
| `grader.py` | `grade(metric, value)` — maps a numeric value to `"GOOD"`, `"FAIR"`, `"POOR"`, or `""` using per-metric thresholds. |

---

### `scoring/`

| File | Purpose |
|---|---|
| `scorer.py` | **`PropertyScorer`** — produces a 0–100 investment score from a saved property record. Weights nine components (Cap Rate, CoCR, DSCR, IRR, Equity Multiple, Cash Flow, Price Drop, DOM, Location). Weights and floor/ceiling thresholds are configurable and persisted in `json/score_weights.json`. Also provides `solve_targets()` — binary search over each lever (asking price, rent, interest rate, down payment) to find the value that would push the score to ≥ 99.5/100. |
| `city_ranker.py` | **`CityRanker`** — groups scored properties by city, computes per-city signals (avg score, best score, volume, cap rate, price drop, DOM, CoCR), applies configurable city-level signal weights, then adjusts the opportunity score toward a neutral 50 using a confidence factor `n / (n + k)` — cities with few properties are pulled toward the mean to avoid overconfident rankings on small samples. |

---

### `reporting/`

| File | Purpose |
|---|---|
| `printer.py` | **`ReportPrinter`** — terminal-only output. `print_report(analyzer)` prints a formatted metric table to stdout. `list_properties(store)` prints a numbered property list sorted by city then street name/number. |
| `property_report.py` | **`PropertyReportGenerator`** — renders a self-contained HTML file with a sortable, filterable table of all properties. Each row shows the investment score, per-component breakdown, financial metrics, and the target asking price / rent / interest rate / down payment that would achieve a near-perfect score. Opens in the default browser. |
| `city_report.py` | **`CityReportGenerator`** — renders a self-contained HTML city opportunity report ranked by confidence-adjusted opportunity score. Shows volume, avg/best scores, key financial signals, sold/off-market comparables, and demographic data where available. The per-city "Score contributions" breakdown is the actual factor contribution emitted by `CityRanker` (no recomputation), so it always matches the configured weights. Opens in the default browser. |

---

### `ui/`

The interactive terminal menu. Excluded from test coverage — all logic that can be unit-tested lives in the layers below. `PropertyMenu` inherits from three mixins so each file stays under 1 000 lines.

| File | Purpose |
|---|---|
| `menu.py` | **`PropertyMenu`** — main menu loop (`run()`), property CRUD actions (`_add`, `_edit`, `_delete`, `_view`, `_list`), HTML report launchers (`_open_report`, `_open_city_report`), bulk re-analysis (`_reanalyze_all`, `_reanalyze_city`), and core helpers (`_prompt_property`, `_record_to_prop`, `_sorted_props`, `_pick_index`). |
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
| `score_weights.json` | Scoring weights (must sum to 1.0), floor/ceiling thresholds per metric, city-level signal weights, and confidence smoothing constant `k`. |
| `city_distances.json` | `{ "Cobourg": { "nearest_centre": "Toronto", "distance_km": 100 } }` |
| `city_demographics.json` | `{ "cobourg": { "population": 20000, "population_2016": 19000, "growth_pct_annual": 1.02, "source": "Stats Canada 2021 Census" } }` |
| `missing_rent_data.json` | Tracks which cities are missing commercial or residential rent data so the menu can prompt the user to fill them in. |

---

## Menu Reference

```
  1  List all properties
  2  View analysis for a property
  3  Add a new property
  4  Edit a property
  5  Delete a property
  6  Open investment report in browser
  c  Open city opportunity report
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

A separate sub-editor tunes the **city opportunity** formula, whose 15 factors (weights must sum to 1.0) feed the city report's "Score contributions" breakdown:

- **Active listings** (still for sale): cap rate, cash-on-cash, IRR, DSCR, annual cash flow, price drop from original list, days on market, and active volume (deal-flow count).
- **Sold listings** (inactive — treated as sold): cap rate, absorption (sold share = demand signal), and price trend (active asking vs sold = appreciation signal).
- **Cross / structural**: active-vs-sold cap-rate trend and the single best deal score in the city.
- **Demographics** (where available): population (log-scaled) and annual population growth.

The final score is the weighted raw sum (0–100) blended with a prior by a confidence factor `n / (n + k)`: `opportunity = raw · conf + prior · (1 − conf)`. The model is **market-depth focused** — `confidence_k` (default 12) demands real listing volume before a city's own metrics are trusted, and `opportunity_prior` (default 40, just below the typical-city score) anchors thin, unproven markets so a single great listing can't outrank a deep, consistent market. Both are tunable in `json/score_weights.json`.

**HTML reports (options 6 / c)**
Option 6 opens a property report in your browser — sortable by any column, showing score breakdowns and the target adjustments needed to reach a near-perfect score. Option `c` opens a city opportunity ranking ordered by confidence-adjusted opportunity score, with an accurate per-factor score breakdown and sold/off-market comparables (inactive listings are treated as sold).

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
| **IRR** | Internal Rate of Return — annualised return over the hold period accounting for all cash flows and exit proceeds. Solved via Newton-Raphson. |
| **Equity Multiple** | Total Return ÷ Cash Invested. A value of 2.0× means you doubled your money over the hold period. |
| **GRM** | Gross Rent Multiplier — Asking Price ÷ Annual Gross Rent. Lower is better. |
| **CELOC** | Cash Equity Left Over on Close — (Exit Equity − Cash Invested) ÷ Cash Invested. |
| **RevPAR** | Revenue Per Available Room — ADR × Occupancy Rate. Hotel-specific. |
| **CPOR** | Cost Per Occupied Room — Total Operating Cost ÷ Occupied Room-nights. Hotel-specific. |
| **Price Drop** | (Original Price − Asking Price) ÷ Original Price. A higher discount signals motivated seller and negotiating room. |
| **DOM** | Days on Market — from listing date to today. Longer time on market increases seller motivation. |
