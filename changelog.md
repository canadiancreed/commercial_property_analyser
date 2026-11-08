# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [5.1.5] — 2026-11-08

_The database lives in the project's `db/` folder, not in `%LOCALAPPDATA%`._

### Changed

- **The SQLite database now lives in a `db/` folder inside the project** — beside the executable
  when packaged, and at the repo root in dev — instead of
  `%LOCALAPPDATA%\CommercialPropertyAnalyser` (packaged) or `poc_nicegui/_data` (dev). On first
  launch the app relocates an existing database from the old location into `db/` automatically
  (a copy, leaving the old file as a backup), so the full property set carries over and no data is
  lost.

---

## [5.1.4] — 2026-11-08

_Rates province dropdown, dark-mode contrast, and city deletion in City data._

### Added

- **Delete a city from the City data tab.** The Distances and Demographics editors each gained a
  "Delete city" button (shown once an existing city is selected), mirroring the Rates tab's delete.
  It drops that city's distance / demographics row and refreshes the Status dashboard.

### Changed

- **Province is a dropdown on the Rates → "Add a city" dialog**, matching the property form (the
  13 province / territory codes) instead of a free-text field.

### Fixed

- **Dark mode: accent / status text is legible again.** Blue / red / green / amber text (section
  headers, the delete action, grade colours) used the `-600`/`-700` shades, which were too dark on
  the navy background; they're now brightened to the `-400` variants under dark mode only.

### Verified (no change needed)

- Adding a property for a brand-new city still stubs blank rates / demographics / distances rows
  and shows the "data needed" notice. Portfolio search remains case-insensitive (matches address or
  city). The cap rate is computed correctly — it is a **market-rent (stabilised) cap rate**, so a
  cheaply-priced but long-vacant building (e.g. 100 Herzberg Rd: $33/sq ft market office rent on a
  $131/sq ft ask ≈ 12.5%) legitimately reads high; the existing Cap Rate Risk Check already flags it.

---

## [5.1.3] — 2026-11-08

_The property-report Google map locates the property again._

### Fixed

- **Property report → Google map now reads all three address fields.** The map query was built
  from the `address` field alone, but that field stopped carrying the city/province (stripped in
  4.11.4), so a bare street was ambiguous and the map broke. The query now combines
  `address`, `city`, and `province` into one string (e.g. "77 Brae St, Almonte, ON"), so the map
  and the "Open in Maps" link resolve to the correct location again.

---

## [5.1.2] — 2026-11-07

_The Demographics editor has its Save button back._

### Fixed

- **City data → Demographics: added the missing "Save demographics" button.** The editor built
  its fields and a working save routine but never rendered a button to trigger it, so there was no
  way to commit a population/source edit. Added the button (matching the Distances editor), so
  entering a city's demographics now saves to the database.

---

## [5.1.1] — 2026-11-07

_The City-data Status dashboard refreshes to reflect edits._

### Fixed

- **City-data Status dashboard now updates after you edit a city.** It was rendered once when the
  City data tab opened, so changes made afterwards (a distance or demographics entry in the
  sibling sub-tabs, or rates on the Rates tab) didn't show until a full reload. The dashboard now
  re-queries the database whenever it's viewed — when you switch to the Status sub-tab, and when
  you return to the City data tab — so a just-saved city immediately shows its updated ✓/✗ status.

---

## [5.1.0] — 2026-11-07

_A Database tab to explore the SQLite structure and data._

### Added

- **Database explorer tab.** A new top-nav **Database** tab for browsing the SQLite database the
  app now runs on: pick a table to see its schema (columns, types, primary key) and row count,
  page through the rows, and click any row to inspect the full values (JSON columns — `config`,
  `app_data`, the property `data` blob — are pretty-printed). It also has a **read-only query box**
  (a single SELECT / WITH / PRAGMA / EXPLAIN statement). Everything here is strictly read-only:
  the query guard (`form_logic.is_readonly_sql`) rejects any write/DDL/multi-statement input and
  the query runs under `PRAGMA query_only`, so nothing in this tab can modify the database.

---

## [5.0.0] — 2026-11-07

_Everything moves into the database — no JSON files at runtime._

### Changed (storage / architecture break)

- **The SQLite database is now the single source of truth for all data.** Every remaining
  file-based dataset moved into the DB, and the `json/` and `config/` directories were removed:
  - **New DB tables / documents:** config documents for `screener`, `underwriting`,
    `industrial_size_bands`, `industrial_premiums`, `vacancy_rates`, `geographic_crosswalk`
    (alongside the existing `financing` / `score_weights`); a new `app_data` table for runtime
    state (missing-city reports, price-check progress, the fetched interest-rate cache); and new
    `city_demographics` / `city_distances` tables. Schema `user_version` → 3.
  - **Embedded seed (`data/seeds/`):** the former shipped JSON/config content is now data-as-code,
    populated into the DB on first run (`DataStore.ensure_seeded`). A fresh install needs no JSON.
  - **Every loader reads the DB:** the vacancy resolver, screener/underwriting/industrial config,
    the scorer's demographics/distances, and the interest-rate feed now resolve through the store
    (with `set_store` injection, mirroring `financing_config`); a store-less caller falls back to
    the embedded seed.
  - **Fetch scripts write the DB:** `scripts/fetch_interest_rates.py`, `fetch_vacancy_rates.py`,
    and `fetch_geographic_crosswalk.py` now persist to the database (pass `--db` for a packaged
    install's path) instead of writing JSON.
  - **Packaging:** the PyInstaller build (`poc_nicegui/build.py`) no longer bundles the removed
    `json/` + `config/` directories; it force-collects the `data/seeds` package (lazily imported)
    so the embedded defaults ship in the `.exe`.
  - Existing databases gain the new tables on connect and seed any missing rows in place; no data
    is lost. (The only remaining file reference is the dormant one-time `properties.json` legacy
    importer.)

---

## [4.12.8] — 2026-11-07

_Dark / light mode toggle in the header._

### Added

- **Dark / light mode toggle** (top-right of the header). Switches the whole desktop UI between
  the existing light theme and a new dark theme — page, cards, tables (AG Grid), and text all
  adapt; light mode is unchanged. The choice is **persisted in the database** (a `ui_prefs` config
  doc) so it survives a reload. Implemented with NiceGUI's `ui.dark_mode()` plus a dark stylesheet
  layered into Quasar's own cascade layer so it reliably overrides the fixed light utilities.

---

## [4.12.7] — 2026-11-07

_City data tab opens on a status dashboard of what each city is missing._

### Added

- **City-data status dashboard.** The City data tab now opens on a new **Status** sub-tab: a
  table of every city (drawn from your properties and the rate tables) showing how many
  properties depend on it and whether its commercial rates, residential rates, distance, and
  demographics are on file (✓/✗), with a plain-language "Missing" column. Most-incomplete cities
  sort to the top, so gaps are obvious at a glance. Backed by `form_logic.city_data_status`
  (unit-tested).

---

## [4.12.6] — 2026-11-07

_Adding a property for a new city stubs all its reference data and says what's needed._

### Changed

- **A brand-new city is now stubbed across every reference store.** Saving (or URL-importing) a
  property whose city had no data already created blank rate rows; it now also creates blank
  **demographics** and **distance** stubs, so the city shows up (blank, "needs data") in every
  City data editor and the status dashboard instead of being silently absent. The save notice
  now spells out exactly what's blank (e.g. _"That city is new — its rates, demographics and
  distance are blank. Fill it in on the City data and Rates tabs…"_). Backed by
  `store.ensure_city_reference_data` + `form_logic.city_data_needed_message` (unit-tested).

---

## [4.12.5] — 2026-11-07

_Delete a city's rates from the Rates tab, with a view of what's linked first._

### Added

- **Delete a city in the Rates tab.** Select a city row and click **Delete city** to remove its
  entry from both the commercial and residential rate tables. The confirmation first lists the
  properties linked to that city (count + addresses) and warns they keep their last report but
  lose the market rate until rates are re-added or they're re-analyzed. Both rate grids refresh
  together. Backed by `store.delete_city_rates` + `form_logic.properties_for_city` (unit-tested).

---

## [4.12.4] — 2026-11-07

_The edit form again shows the rent the last analysis calculated._

### Fixed

- **Editing a property now shows what the rent was calculated as.** When a property is saved
  without an owner-entered rent, the analyzer resolves a market-estimated figure and stores it,
  but the Add / Edit form deliberately keeps those fields blank so re-editing never freezes an
  estimate as owner-entered. That left the desktop form hiding the computed rent, which the old
  command-line edit view used to show as each field's "current" value. A read-only caption now
  appears beneath the Commercial, Residential, and Direct-total rent inputs — e.g. _"Last analysis
  used $120,000/yr (market estimate)."_ — restoring that visibility without changing what gets
  saved. Backed by `form_logic.resolved_rent_caption` (unit-tested).

---

## [4.12.3] — 2026-11-07

_The Add / Edit form validates numeric input end-to-end._

### Added

- **Full numeric validation on the Add / Edit form.** Every money/size/count field now
  rejects negative values, percent ratios (expense ratio, vacancy, occupancy, market/exit
  cap rate) are bounded 0–100%, NOI growth is bounded −100–100%, and Floors must be at
  least 1. Each field shows the error inline as you type, and `save_property_from_form`
  re-checks the same rules through `form_logic.validate_property_form` (unit-tested) so
  invalid data can never be saved. Blank optional fields still pass. Verified live.

---

## [4.12.2] — 2026-11-07

_Province is now a dropdown instead of free-form text._

### Changed

- **Province is a dropdown** of the 13 province/territory codes (AB, BC, MB, NB, NL, NS,
  NT, NU, ON, PE, QC, SK, YT) instead of free-form text, so it can't be mistyped. It's
  blank on a new entry and type-to-filter / clearable; an edited record whose stored value
  isn't one of the standard codes keeps that value as an option so editing never drops it.
  Backed by a new ordered `PROVINCE_CODES` constant (`models/constants.py`).

---

## [4.12.1] — 2026-11-07

_Fix: the Add / Edit Property type dropdown no longer defaults to the last-used type, and a type is now required to save._

### Fixed

- **New entries start with a blank property type.** The type dropdown used to carry over
  the last type entered, so a new property silently inherited it. A new entry (and the
  form after any save or reset) now defaults the type to blank.
- **A property type is required to save.** Saving a property with no type selected is
  blocked with a "Select a property type to save." notice — the whole analysis keys off
  the type, so a blank type can't be analysed. Validated in
  `form_logic.validate_property_form` (unit-tested); verified live in the running app.

---

## [4.12.0] — 2026-11-07

_Feature: a property's detail view now shows a Price & Status History timeline._

### Added

- **Price & Status History section** in the property detail view (built into the HTML
  report, so it also appears in exported/printed and CLI reports). It shows a seeded
  **"Listed"** baseline — the listing date and original list price — followed by any
  dated price changes (▼ reduced / ▲ increased) and status changes (went inactive /
  reactivated).
- **History is recorded going forward.** The data model never snapshotted a dated
  history, so a dated entry is now appended whenever a property is **edited/saved** and
  its asking price (beyond $1) or status actually changes. Re-analysis re-reads the same
  stored values, so it never adds a spurious entry; the realtor.ca price-check is
  unchanged. Records are carried on `price_history` / `status_history`; existing listings
  show just the "Listed" baseline until their next recorded change.
- Pure logic in `history_logic.py` (`record_price_change`, `record_status_change`,
  `build_timeline`), unit-tested. The capture wiring (`to_record` /
  `build_partial_record` appending on a real change, and adding nothing on re-analysis)
  and the report rendering (timeline round-tripping into the page JSON) have dedicated
  integration tests too; also verified live in the running app.

---

## [4.11.5] — 2026-11-06

_Fix: the Add / Edit Property tab stayed stuck on the last record loaded for editing._

### Fixed

- **Clicking "Add / Edit Property" now always starts a fresh add.** Loading a property via
  the report's **Edit** button left the form in edit mode; if you then switched to another tab
  without saving or cancelling, reopening "Add / Edit Property" still showed that record instead
  of a blank form for a new entry. The tab now resets to a blank add form when it is opened while
  a record is loaded for editing. A half-entered **new** property is preserved (only a lingering
  *edit* is cleared), and the Edit button's own jump to the form still loads its record. Decision
  logic in `form_logic.should_reset_form_on_tab` (unit-tested); verified live in the running app.

---

## [4.11.4] — 2026-11-06

_Fix: legacy imported records had the city + province baked into the address field._

### Fixed

- **Addresses cleaned to the street only.** Old imports stored the full "street, city,
  province" in the `address` field, duplicating the separate City/Province columns. A
  one-time, guarded migration (`DataStore.normalize_addresses`, run on boot) strips a
  trailing ", city" / ", province" from each address **only when it matches the record's own
  city/province** — so a street whose listing town differs from the City field (e.g. "…,
  Brockton, ON" with City "Walkerton") keeps that town, nothing is over-stripped, and an
  already-clean address is untouched. It updates in place by row id and skips any change that
  would collide with another record's key. Pure logic in `form_logic.clean_address`
  (unit-tested); verified on real data (928/932 cleaned, 0 collisions).

---

## [4.11.3] — 2026-11-06

_Fix: Floors can now be entered for every building type._

### Fixed

- **Floors field for all types.** The `Floors` input only appeared in the residential unit-mix
  group, so office / retail / industrial / hotel properties had nowhere to enter it. Floors is
  a building-wide attribute, so it now lives in **Core details** (shown for every type). The
  desktop save also no longer drops it: a `UnitMix` (carrying `floors`) is always built — even
  for unit-less types — matching the re-analysis path, so floors persists for commercial
  buildings too instead of being lost.

---

## [4.11.2] — 2026-11-06

_Fix: the edit form sometimes opened blank even though the right property was selected._

### Fixed

- **Edit form now always populates.** Opening a property whose type differed from the form's
  current type blanked every field (the "Editing" badge showed the right address, but the
  inputs were empty). `load_for_edit` sets the type dropdown programmatically, and its
  `on_change` was snapshotting the old/empty form into the carried draft — which then
  overrode the record's prefill. That snapshot is now suppressed during the programmatic
  set, so the form fills from the record. (Fixes the "sometimes blank when editing" case;
  complements 4.11.1's correct-property fix.)

---

## [4.11.1] — 2026-11-06

_Fix: clicking or editing a property could open the wrong property — or a blank one._

### Fixed

- **Selecting/editing now always opens the clicked property.** The portfolio grid identified
  a row by a cached positional index, but the load order shifts whenever a record is
  edited/added (moved to the end) or deleted (renumbered), so a stale index could map to a
  *different* property (e.g. "442-446 Olive" opening "45 Cambria") or out of range (a blank
  edit form). Selection now resolves the property by its stable `(address, listing_date)`
  key — the table's UNIQUE key — at click time, and Edit/Delete re-resolve the same way, so
  they can't act on the wrong or a missing row. New `form_logic.resolve_row_index`
  (unit-tested).

---

## [4.11.0] — 2026-11-05

_The Rates tab is now an editable table of every city's rents, not a one-city-at-a-time form._

### Changed

- **Rates tab → editable table.** Each sub-tab (Commercial $/sq ft/yr, Residential $/mo) now
  shows **all cities as rows** with a column per rate type/unit, so coverage is visible at a
  glance and rates are edited in place. **Save changes** persists only the cities whose cells
  changed and re-analyzes just those; **Add city** appends a new one. The residential
  "unknown" unit rate is still auto-set to the average of the entered rents. Replaces the
  previous "City to edit" dropdown form.
- Pure table logic lives in `form_logic.py` (`rate_rows_to_grid`, `grid_row_to_rates`,
  `residential_with_unknown`, `changed_rate_rows`) and is unit-tested; the grid is the thin UI.

This makes it easy to fill the rent gaps behind "—" cap rates (a city with no market rent
can't produce a cap rate; add one here and Re-analyze).

---

## [4.10.2] — 2026-11-05

_Portfolio search now matches the city too, not just the street address._

### Fixed

- **Search by city works.** The Portfolio search box matched only the `address` field, so a
  property was unfindable by its city when the city differed from the address text (e.g.
  address "326 Durham St E, Brockton, ON" but City "Walkerton"). `filter_rows`
  (`form_logic.py`) now matches the `address` **or** `city` (case-insensitive), and the box
  placeholder reads "Search by address or city…".

---

## [4.10.1] — 2026-11-05

_Re-analyze all now shows which properties were skipped or errored, and why._

### Added

- **Re-analyze detail.** After **Re-analyze all**, if any property didn't update, a dialog
  lists each one — errors first (need attention), then skips (usually a city with no market
  rent rates yet) — with its address, city/type/MLS, and the reason. `reanalyze_properties`
  (`analysis/report_builder.py`) now returns an `issues` list ({address, mls, city,
  property_type, kind, reason}) alongside the existing counts; a blank skip reason falls back
  to "No market rent rate for this city yet." The summary notification is unchanged.

---

## [4.10.0] — 2026-11-05

_Test-coverage audit of all v4 work: the desktop app's logic is now unit-tested._

### Added

- **`form_logic.py`** — the desktop app's pure, UI-free logic (portfolio search filter,
  draft-over-record prefill + type-switch preservation, rent prefill provenance, percent /
  financing-field coercion, save validation, and the form→`PropertyInput` mapping) extracted
  from `poc_nicegui/app.py` so it can be unit-tested without the app's boot side-effects.
  It's a top-level module (bundled into the exe like the other engine packages).
- **`tests/test_form_logic.py`** (26) + **`tests/test_v410_coverage_gaps.py`** (3) — cover
  the desktop-layer behaviours shipped across v4.1–v4.9 (edit/save mapping, validation,
  address search, prefill provenance, financing-field coercion, hold-period-is-global,
  type-switch draft) plus two engine gaps (`to_record` omits `notes`; `hold_years` is global
  for every type). Full suite: **1452 passing**.
- **`docs/test-coverage-v4.md`** — a per-release map of every v4.0.0→v4.10.0 feature to the
  test(s) that cover it, and the small remaining UI-only surface (validated by the boot
  smoke-test).

### Changed

- **`poc_nicegui/app.py` delegates to `form_logic`** (behaviour-preserving) — the portfolio
  filter, form prefill, `_pct`, the save mapping, and the financing-editor coercion now call
  the extracted functions. No user-visible change.

---

## [4.9.4] — 2026-11-05

_Add/Edit form: hold period is global (removed from the form), and changing property type no longer wipes what you entered._

### Fixed

- **`Hold years` is no longer editable per property.** It's a house-wide setting
  (`config/financing.json` defaults, edited on the **Settings** tab) applied to every
  property — like down payment, interest rate, and amortization. The stray `Hold years`
  input on the Add/Edit form was removed, and saving now always uses the global value, so
  every listing is underwritten on the same hold period.
- **Changing the property type no longer destroys entered data.** The type-aware form
  reshapes on a type change (different fields per asset class); it now snapshots the current
  inputs into a draft first and re-applies them, so shared fields (address, price, rents,
  etc.) keep their values. The draft is cleared on reset, when loading a record to edit, and
  after a successful save.

---

## [4.9.3] — 2026-11-05

_The build writes the exe straight to the project root, so the copy you launch is always the latest._

### Changed

- **`build.py` outputs the exe to the project root** (`--distpath` = repo root) instead of
  `dist/`, and sends PyInstaller's scratch (work dir + `.spec`) to the system temp. A build
  now leaves nothing in the repo except `CommercialPropertyAnalyser.exe` at the root — the
  exact file you double-click — so a stale `dist/` copy can't diverge from the latest build.
  (`make build` / `.\make.ps1 build` are unchanged; they call `build.py`.)

---

## [4.9.2] — 2026-11-05

_The database is the single source of truth: no more auto-seeding property records from `properties.json`._

### Changed

- **The app no longer imports `properties.json`.** It opens the SQLite database and shows
  whatever records it contains (empty on a brand-new DB). The guarded one-time
  `ensure_properties_migrated` seed was removed from both the desktop app
  (`poc_nicegui/app.py`) and the CLI (`main.py`), and the build no longer bundles
  `properties.json`. Importing data is now an explicit, separate action (future feature),
  not a silent startup step — so a reverted or stale `properties.json` can never again
  replace your real data. (Rent rates and scoring/financing **config** still seed once from
  the bundled `json/` + `config/` reference files; those are reference/config, not your
  property records.)

### Notes

- Existing databases are unaffected — your records already live in the DB. The desktop
  app's DB persists at `%LOCALAPPDATA%\CommercialPropertyAnalyser\properties.db`.

---

## [4.9.1] — 2026-11-05

_Fix: the app/build crashed when run from a normal checkout; plus a dev task runner._

### Fixed

- **`build.py` and `app.py` no longer crash outside a git worktree.** Both derived the
  live repo-root `properties.json` with `…parents[2]`, which assumed the code lived at
  `<repo>/.claude/worktrees/<name>` (three levels deep). Run from a normal checkout —
  `python poc_nicegui/build.py` or `python poc_nicegui/app.py` from the repo root — that
  overflowed with `IndexError: 2`. The climb is now guarded: it only walks up to the real
  repo root when actually inside a worktree, otherwise it uses the checkout root.

### Added

- **Dev task runner.** A `Makefile` (Git Bash / Unix) and a `make.ps1` shim (Windows
  PowerShell, no install needed) with targets `run`, `web`, `build`/`compile`, `test`,
  `fetch-rates`, `fetch-vacancy`, and `clean`. E.g. `make build` or `.\make.ps1 build`.

---

## [4.9.0] — 2026-11-05

_All Settings config moves into a DB table, and every financing value is editable in-app._

### Added

- **`config` DB table.** A new generic `config` table (one JSON document per logical
  name) in the SQLite store, with `DataStore.read_config(name, seed_path)` /
  `write_config(name, cfg)`. Financing (`config/financing.json`) and scoring + city
  config (`json/score_weights.json`) now live here as the **live source**; the JSON
  files remain the **shipped defaults**, seeding a missing row once on first read
  (migration-on-read). Schema version bumped 1 → 2 (the table is created with
  `IF NOT EXISTS`, so existing databases gain it on connect).
- **Per-asset-class financing editor (Settings).** Edit every lending rule — per-type
  Max LTV, rate band (with a live "bps over base" readout), amortization, DSCR floor,
  fixed-expense fraction, the CMHC Standard/Select sub-blocks, and the base-rate anchor.
  Plus an **Advanced — full financing config (raw JSON)** editor (parsed + validated on
  save) so genuinely every value, including nested CMHC point-tiers and conditional
  rules, is editable. `analysis/financing_config.py` gained `set_store` / `get_raw_config`
  / `save_raw`.

### Changed

- `scoring/scorer.py` `load_config`/`save_config` now route through the `config` table
  (the city-opportunity weights/knobs ride inside the same document). The desktop app
  and CLI inject the store on boot (`financing_config.set_store(store)`); tests and any
  store-less caller keep the JSON-file path unchanged.

---

## [4.8.0] — 2026-11-05

_Interest rates are now sourced from a live Bank of Canada feed instead of hand-typed estimates._

### Added

- **Bank of Canada base-rate feed.** The one number behind every mortgage rate — the
  Government of Canada 5-year benchmark bond yield — is now fetched from the Bank of
  Canada Valet API (open, no key), not guessed. `scripts/fetch_interest_rates.py` writes
  `json/interest_rates.json`; `analysis/rate_feed.py` holds the shared, offline-safe fetch
  logic. The desktop app auto-refreshes it on boot (throttled to once/day, off-thread) and
  the **Settings → Global financing** card shows the live base rate with a **Refresh base
  rate (Bank of Canada)** button.
- **Base + spread pricing.** Every per-type rate is now `live GoC 5-year yield + an
  asset-class credit spread`. The per-type bands in `config/financing.json` are anchored to
  a recorded base (`rate_base`); the resolver shifts every band in parallel by
  `(fetched yield − anchor)`. Only the base is sourced; the spreads remain documented
  lender-credit estimates. The Add/Edit form label now names the live base rate.

### Changed

- **No score churn on wire-up.** The anchor is set to the GoC 5-year yield on the day the
  feed was wired (3.49%, 2026-11-03), so with the feed at that level the adjustment is
  exactly 0 and every rate is unchanged from the prior verified values. Rates only move once
  the yield moves; **re-analyze** to push new rates into stored results — same as the
  vacancy pipeline.

### Fixed

- **Settings "Save financing" no longer drops config.** Saving the global defaults now
  preserves every other top-level key (`property_types`, `rate_base`,
  `residential_covenant_dscr`, the source notes) instead of rebuilding a stripped file.

---

## [4.7.2] — 2026-11-04

_Add/Edit form: every per-property input is now editable (plus two edit-path data-loss fixes)._

### Added

- **Full field editing.** The type-aware Add/Edit form now exposes every per-property
  input the analysis pipeline honors, not just the core subset: `MLS #`, `Original / list
  price`, `Hold years`, a direct `Residential rent $/yr` override, and a new **Income &
  assumptions (overrides)** card with `Direct total rent`, `Expense ratio`, `Vacancy rate`,
  `NOI growth`, and free-text `Notes`. Each override is blank by default and falls back to
  the model's resolver when empty. Down payment / interest rate / amortization stay global
  (Settings tab) and are shown read-only on the form so nothing looks missing.

### Fixed

- **`created_at` no longer reset on edit.** Saving an edit now passes the original record
  as `existing` to the analyzer, so the creation date (and other carried provenance) is
  preserved instead of being stamped to today — matching the re-analysis path.
- **Notes no longer dropped on edit.** `notes` isn't part of the analysis record, so the
  form value is now carried through explicitly on save (a blank field clears the note).
- **Rent prefills respect provenance.** Editing a record no longer silently "freezes" a
  market-estimated commercial/residential rent as owner-entered; those fields prefill only
  when the record flags them as user-entered.

---

## [4.7.1] — 2026-11-04

_UI: a live address search on the Portfolio tab._

### Added

- **Portfolio address search.** A "Search by address…" box above the portfolio grid filters
  the table live as you type — case-insensitive, matching anywhere in the address. It filters
  a cached copy of the rows (no per-keystroke database re-query), the clearable **✕** restores
  the full list, and a save / re-analyze still refreshes the grid while respecting the current
  search term.

---

## [4.7.0] — 2026-11-03

_Packaging polish: a database schema-version + migration scaffold, a reproducible build
script, and an app icon. (A Windows installer and bundling the Firefox browser binary
into the exe remain.)_

### Added

- **DB schema versioning.** The SQLite database now carries a `user_version` (baseline = 1),
  and `DataStore` applies any pending forward migrations on connect (`SCHEMA_VERSION` +
  `_MIGRATIONS`), so a future schema change can upgrade an old database in place instead of
  breaking it. Pre-versioning databases are stamped to the current version on next open.
- **`poc_nicegui/build.py`** — a single reproducible build command (onefile by default,
  `--onedir` for faster startup) that bundles NiceGUI, the json/ + config/ + properties
  seed, the Playwright driver, and the app icon.
- **App icon** (`poc_nicegui/icon.ico`), wired into the build.

### Remaining (environment-heavy)

- A Windows **installer** (e.g. Inno Setup / NSIS) — needs a packaging toolchain.
- Bundling the **Firefox browser binary** into the exe, so scraping needs no separate
  `python -m playwright install firefox` on the target machine.

## [4.6.0] — 2026-11-03

_Scraper: realtor.ca URL import in the desktop app (lazy-loaded), and Playwright now
bundles into the exe. The multi-hour price-check sweep stays a CLI feature for now, and
bundling the Firefox browser binary itself is left to packaging (4.7.0)._

### Added

- **Add from realtor.ca URL** (Portfolio toolbar): paste a listing URL → it opens Firefox,
  reads the listing, and saves an incomplete record (mirrors the CLI `_add_from_url`), to
  be completed via Edit. The scraper is imported **lazily**, so the app still starts
  without Playwright, and a missing / blocked scraper degrades to a friendly message
  rather than crashing.
- The onefile exe now bundles the Playwright driver (`--collect-all playwright`) and still
  starts cleanly (~145 MB). Live scraping needs a system Firefox
  (`python -m playwright install firefox`) and may require solving a CAPTCHA in the browser
  window it opens.

### Deferred

- The realtor.ca **price-check sweep** (every stored property's current price) — a
  multi-hour, interactive, bot-detection-prone operation — stays in the CLI for now.
- Bundling the Firefox **browser binary** into the exe (so no separate install) is 4.7.0
  packaging work.

## [4.5.0] — 2026-11-03

_Scoring sub-editors in the desktop app. (CSV import is intentionally omitted — it's a
deprecated path; realtor.ca URL import moves to 4.6.0 with the scraper it depends on.)_

### Added

- Settings: a **City opportunity** editor — the 14 city-ranker signal weights plus the
  model knobs (depth weight / reference, outlier cap-rate / CoCR ceilings), saved through
  the scorer config.
- A new **City data** tab with two editors: **Distances** (nearest regional centre + km,
  which drives the Location score) and **Demographics** (2021 + 2016 census population →
  auto-computed annualised growth, which feeds the city-opportunity ranker). Both write to
  the per-user data dir, never the tracked repo files.

## [4.4.0] — 2026-11-03

_Fuller add/edit form + input validation (desktop app)._

### Added

- The Add/Edit form now captures **construction cost** (core group) and **commercial
  lease expiry** (commercial group), and flags a commercial rent you type as
  user-entered (advertised/actual, not a market estimate). All are wired into the saved
  record and prefilled when editing.
- **Validation:** inline rules (asking price must be > 0, sq ft can't be negative) plus
  a save-time guard that blocks saving without an address or with a non-positive asking
  price.

## [4.3.0] — 2026-11-03

_Re-analysis on data change (desktop app) — edits to rates or financing no longer leave
stored results stale._

### Added

- **`reanalyze_properties(store, resolver, analyzer_cls, predicate=None)`** in
  `analysis/report_builder.py` — a headless re-run of analysis for stored properties
  (record → PropertyInput → analyzer → `to_record(existing)` → `update_property`),
  mirroring the CLI `_reanalyze_all` core loop; `predicate` limits it to a subset
  (e.g. one city). Returns updated / skipped / error counts.
- Desktop app: a **Re-analyze all** action on the Portfolio tab runs it in a background
  thread with a spinner and reports the counts. Saving a commercial or residential rate
  now **auto-re-analyzes that city's** properties and refreshes the portfolio; the
  financing-defaults save prompts the user to run Re-analyze all.

## [4.2.0] — 2026-11-03

_Stage A: shared service layer — the record↔model and report-row mappings now live in
one place instead of being duplicated across the CLI and the desktop app._

### Changed

- Extracted `record_to_prop` and `build_report_row` into **`analysis/report_builder.py`**,
  the single source used by both front-ends. `ui/menu.py` exposes them as
  `PropertyMenu._record_to_prop` / `_build_report_row` (staticmethod class attributes, so
  the existing API — including the tests and the instance monkeypatch — is unchanged), and
  `poc_nicegui/app.py` imports them instead of keeping verbatim copies. Pure refactor, no
  behaviour change; all 1401 tests pass.

## [4.1.0] — 2026-11-02

_Desktop app: property edit & delete._

### Added

- **Edit & delete** in the NiceGUI desktop app. The report dialog gains Edit and Delete
  actions. **Edit** loads the record into the type-aware form (reshaped to its property
  type and prefilled), re-runs the analyzer on save, and updates in place — removing the
  original first so an address / listing-date change can't create a duplicate. **Delete**
  asks for confirmation, then removes the record from the database.
- Report iframes are cache-busted (`?t=…`) so a reused report slot always renders the
  current record's HTML rather than a stale cached file.

## [4.0.0] — 2026-11-02

_Database-backed storage and a desktop application. Property and rent data move out of
single JSON files into a SQLite database (behind the unchanged `DataStore` API), and a
NiceGUI desktop proof-of-concept — packaged as a standalone Windows `.exe` — reuses the
whole analysis engine and HTML reports. Major version bump: the storage layer changed
and the app gained a graphical front end alongside the CLI._

### Added

- **SQLite data layer.** Property records now live in a `properties` table and rent data
  in dedicated `commercial_rents` + `residential_rents` tables, replacing the
  fully-rewritten-on-every-save JSON files. Each property is stored losslessly as a JSON
  blob with a few mirrored, indexed columns (city / province / status / type / price).
  A single save is now one row write instead of rewriting the whole file.
- **Transparent one-time migration.** On first run the app imports the legacy
  `properties.json` and the rent JSON into the database (`ensure_properties_migrated` /
  `ensure_rates_migrated`), guarded so it never re-runs or clobbers later edits, and
  never modifies the source JSON. Rate lookups trigger it lazily; `main.py` runs it at
  startup.
- **Editable rate views** — `DataStore.load_commercial_rate_rows()` /
  `load_residential_rate_rows()` return city + province + per-type/unit values for
  editing UIs.
- **Desktop application (proof-of-concept)** under `poc_nicegui/` — a NiceGUI app packaged
  into one double-click Windows `.exe` (PyInstaller), running as a native window and
  reading/writing a persistent per-user SQLite database. Tabs: Portfolio (searchable
  grid), type-aware Add form, all seven reports embedded (reusing each generator's
  `render()`), commercial/residential rate editing, and global settings (financing
  defaults + scoring weights). See `poc_nicegui/README.md`.
- **Tests** — `tests/test_data_store_sqlite.py` (persistence, lossless nested round-trip,
  mirrored columns, insertion order, migration guard, rate tables).

### Changed

- `DataStore` property + rate methods are reimplemented on SQLite while keeping their
  public signatures and return shapes identical — no other module changed. Missing-cities
  and price-check progress remain JSON (read-mostly / scratch data).
- `PROPERTIES_PATH` default is now `properties.db`; the legacy `properties.json` becomes
  a one-time migration seed.

## [3.7.0] — Unreleased

_Regional vacancy pipeline. The hardcoded per-type vacancy constant is replaced by a
region-keyed lookup resolved through an always-terminating 4-tier fallback chain,
sourced from two scripted, versioned downloads (CMHC Rental Market Survey vacancy +
StatCan Geographic Attribute File crosswalk). Zero hand-entry; refresh = re-run the
fetch scripts. Requires a re-analysis (menu `r`) to persist the resolved rates + source
stamps into stored records._

### Added

- **Regional vacancy resolver** (`analysis/vacancy_resolver.py`) —
  `resolve_vacancy(city, province, property_type)` walks a 4-tier chain (first hit
  wins): **region** (CSD maps to a directly-surveyed CMHC centre) → **parent_cma** (CSD
  sits in a surveyed CMA/CA) → **provincial_avg** (provincial average) →
  **constant_floor** (nothing resolved — tier-4 alarm). The join is code-to-code after
  one unavoidable city-name → CSD-code hop.
- **Type awareness.** CMHC RMS measures residential vacancy, so residential asset
  classes (multi-family, residential, mixed-use residential component) draw tiers 1-3
  from the survey; commercial classes resolve to their per-type `VACANCY_RATE_DEFAULTS`
  constant through the same resolver under a distinct `type_default` stamp (an expected
  baseline, never an alarm) — commercial numbers do not regress, and a commercial
  regional feed can slot into tiers 1-3 later with no resolver change.
- **Conservative floor** — **only tier 4** (no real data / pipeline break) floors at
  `max(type constant, national)`; tiers 1-3 report their real CMHC figure raw, including
  a provincial average below the 3% constant (flooring it would overwrite genuine
  sub-constant provinces — e.g. BC ~1.9% — and re-create the blanket constant this
  pipeline removes).
- **Source stamp + CMHC reliability code on every record** (`vacancy_source`,
  `vacancy_reliability`, `vacancy_region`, `vacancy_tier`, `vacancy_normal`,
  `vacancy_demoted_from`) — the per-property Vacancy Rate row shows its tier / region /
  reliability, and the batch re-analysis prints the source mix (`ui/menu.py`).
- **Reliability demotion is visible, not silent** — a caution-graded figure is skipped for
  the next tier, and the skipped region + grade are kept in `VacancyResolution.demoted_from`,
  persisted as `vacancy_demoted_from`, appended to the Vacancy Rate row (`· demoted from
  Kingston CMA (rel. d)`), and broken out as their own line in the batch source-mix — so a
  demoted deal is distinguishable from a genuine no-regional-data one. Reliability is the
  published statistical-quality grade on the vacancy figure alone; it never touches listing
  data, prices, rents, or the income estimate. The reachable StatCan channel carries
  StatCan's `E`/`F` flags (not CMHC's a/b/c/d, which are HMIP-only); the resolver demotes on
  `d`/`e`. No current live region is flagged-with-value, so demotion is unit-tested but has
  not yet fired on production data.
- **Tier-3 provincial is honestly labeled as a derived, unweighted average** — there is no
  official provincial CMHC-RMS cut, and the RMS rental universe (unit count per centre)
  needed for a stock-weighted mean is not published on the reachable StatCan WDS channel
  (HMIP-only), so tier 3 is the **unweighted** mean of a province's surveyed centres. The
  Vacancy Rate row now carries `· derived: unweighted avg of surveyed centres` inline
  (`analysis/vacancy_resolver.VacancyResolution.provenance`), not only in the data-file
  `_meta`, so a user leaning on a tier-3 number sees the caveat. Universe-weighting was
  investigated against the live WDS tables and confirmed not possible from this source.
- **Tier-4 tripwire** — a residential deal that falls all the way through to the
  constant floor (`normal=False`) is counted and surfaced after re-analysis. Every
  property has a province, so tier 3 always resolves in healthy operation; nonzero
  tier-4 is the "go look" signal that the fetch/join broke.
- **Two scripted fetches** (`scripts/fetch_geographic_crosswalk.py`,
  `scripts/fetch_vacancy_rates.py`), run for real against live government data:
  `json/geographic_crosswalk.json` (StatCan 92-151-X — 5,161 CSDs / 153 CMA/CAs, with the
  996–999 "metropolitan influenced zone" pseudo-codes excluded) and `json/vacancy_rates.json`
  (real CMHC RMS, October 2025 — 140 surveyed regions across 11 provinces). CMHC's HMIP
  portal blocks programmatic access (HTTP 403) and no `cmhc` PyPI wrapper exists, so the
  vacancy fetch pulls the **identical CMHC series republished by Statistics Canada's WDS**
  (tables 34-10-0127/128/129, joined to the crosswalk by the DGUID's CMA/CA code). That
  channel carries StatCan's quality flag (`E`/`F`), not CMHC's a/b/c/d letters, and no
  provincial cut — so provincial/national tiers are the unweighted mean of surveyed centres,
  labeled as such. Both fetches are stdlib-only and leave the existing file untouched on any
  failure (never a partial write). Real end-to-end result: 218 deals resolve to regional
  (`parent_cma`) data, 180 to raw provincial, 0 tier-4 alarms.
- **CMHC attribution** — the required "Adapted from Canada Mortgage and Housing
  Corporation, Rental Market Survey, <reference date>" string surfaces in the property
  report footer and the vacancy-sensitivity report.

### Changed

- **`_resolve_vacancy_rate` is now region-keyed** (`analysis/analyzer.py`) — it returns
  a `VacancyResolution` (rate + provenance) instead of a bare `VACANCY_RATE_DEFAULTS`
  lookup, which is retained as the per-type constant floor. The mixed-use residential
  component vacancy now comes from the resolver (was the fixed
  `component_vacancy.residential` 0.04); a Testville/ON fixture resolves to the ON
  provincial floor (0.03), shifting the mixed-use golden values accordingly.

### Fixed

- **Firefox persistent-context launch now self-heals** (`scraping/firefox_launcher.py`,
  wired into `scraping/realtor_scraper.py`) — the realtor.ca scraper could fail at
  startup with `BrowserType.launch_persistent_context: Failed to launch the browser
  process` after Firefox exited **0** (started, couldn't open the profile, quit cleanly).
  The launch is now wrapped in an escalating recovery routine: **(1)** launch as-is →
  **(2)** clear stale lock files (`parent.lock` / `.parentlock` / `lock`) left by a killed
  run → **(3)** kill only the `firefox.exe` processes whose command line names *this*
  profile, clear locks, relaunch → **(4)** rename the profile aside (`.broken-<stamp>`,
  never delete) and relaunch once; if all fail it raises with the profile path and the
  last underlying error.
- **Proactive revision quarantine** — the profile carries a `.playwright_firefox_revision`
  marker; on startup a marker that disagrees with the installed Playwright build's
  `firefox-<n>` (the `compatibility.ini` mismatch that makes Firefox exit 0 silently) is
  quarantined *before* a launch attempt is spent on it. On this machine the marker/log
  showed the installed build had moved `firefox-1522` → `firefox-1532` — the exact cause
  this guard catches.
- **Never blanket-kills Firefox** — process matching is by the specific profile path in the
  command line (via `psutil` when present, else a PowerShell `Get-CimInstance Win32_Process`
  query — never the removed `wmic`), so the user's ordinary browsing session is left open.
  Verified live: 2 profile-owned processes killed while 24 unrelated stock-Firefox
  processes stayed running.
- **Reset is opt-out** — resetting the profile discards realtor.ca cookies / cleared
  bot-check state, so it is renamed (recoverable) not deleted, logged at WARNING, and a new
  `RealtorScraper(allow_profile_reset=False)` flag makes the routine raise instead of
  resetting for callers where losing that state is worse than failing.

---

## [3.6.7] — 2026-07-25

_CMHC MLI financing correction. Every listing is an existing-building acquisition,
so the model now scores on realistically-obtainable MLI terms, not best-case
construction figures. Parameters verified July 2026 against CMHC primary
(cmhc-schl.gc.ca) + corroborating broker/lender sources; each constant is marked
with source and status in `config/financing.json` and `docs/scoring-design.md`.
Requires a re-analysis (menu `f`) to persist into stored records._

### Changed

- **Acquisition LTV capped at 85%** (was 95% MLI Select). 95% is loan-to-*cost* for
  new construction / the published 100-point existing-property ceiling — never
  thrown by real acquisition DSCR, so lenders advance to ~85% (effective-advance
  practice). Both MLI Standard and Select are scored at 85%; 95% is retained only as
  labelled, unmodelled upside. Moved the **49** five-plus multifamily that had been
  scored at 95% down a mean **−5.5** (largest −22.4: 61 Brookfield Rd 70→48).
- **5+ multifamily ranks on MLI Standard** (85% LTV / 40yr / DSCR 1.20 — the
  no-points certainty floor), replacing the old conventional-below-$1M /
  MLI-Select@95%-at-or-above-$1M split. DSCR floor corrected 1.30 → 1.20 (CMHC).
- **Mixed-use CMHC eligibility via the 30% non-residential rule** — mixed-use was
  previously excluded from CMHC entirely. Commercial gross-floor-area share is
  computed as **1 ÷ floor count** (equal-plate convention: ground-floor commercial,
  upper floors residential) and gated at a **flat 30%**; a mixed-use building with
  commercial share ≤30% (4+ floors) **and** ≥5 residential units is MLI-eligible and
  ranks on MLI Standard, else conventional. **11** mixed-use become eligible.
- **Small-balance carve-out (uniform, all MLI-routed types)** — a deal whose 75%-LTV
  loan (`price × 0.75`, not price) is under the ~$1M CMHC practical floor finances
  conventionally (75% LTV / 25yr), not MLI: an MLI lender declines a sub-floor
  balance regardless of asset type. **48** deals revert (42 multifamily + 6
  mixed-use); the minimum 75%-LTV loan among all MLI-routed deals is now $1.05M.
  Conventional LTV is held at **75%** (the conservative end of the 75–80% range).
- **MLI Select amortization is point-tier-dependent** — 40yr at 50 pts, 45yr at 70
  pts, 50yr at 100 pts (50yr is the 100-point reward, limited recourse). The Select
  score is modelled at 70pt/45yr, never a blanket 50yr.

### Added

- **Dual scoring — MLI Standard (ranking) + MLI Select (upside) + gap.** MLI-eligible
  deals are ranked on the Standard score and carry a Select upside score plus the gap
  (`analysis/analyzer.py` runs a second debt-side pass → `select_results`;
  `scoring/scorer.py` scores the Select variant against the 1.10 Select covenant).
  Because LTV is capped at 85% for both programs, equity/loan are identical, so the
  Select edge is amortization (45 vs 40yr) + the lower DSCR floor, not leverage — the
  gap is small by construction. The card shows "MLI Select N (+gap)" with the
  "95% LTV requires 100pts + DSCR≥1.20 + lender advance" caveat.
- **Per-type CMHC source/verification metadata** in `config/financing.json`
  (`acquisition_ltv_cap`, `unverified_max_ltv`, `amort_by_points`,
  `modeled_amort_years`, the mixed-use `cmhc_conditional` 30%-rule block) plus a
  constant-by-constant source/status table in `docs/scoring-design.md`.

### Fixed

- **MLI panel renders iff the deal is MLI-routed** (`analysis/deal_financing.py`) — no
  MLI rows on any conventional deal (small-balance multifamily, 1–4 unit residential,
  non-eligible mixed-use); the panel now also renders correctly for MLI-routed
  mixed-use, and the stale "MLI Eligible: No" row on conventional deals is gone.
- **MLI panel display drift** — the Select row would have shown the pre-correction
  95% LTV / 50yr; it now shows the 85% acquisition cap, modelled 45yr (up to 50yr @
  100 pts), and the 95%-is-unverified-upside note.

---

## [3.6.6] — 2026-07-25

_Scoring engine redesign. Seven structural fixes plus a financing-robustness
factor and a covenant gate, validated on the live 639-property / 109-city data
set and documented in full in `docs/scoring-design.md`. Config/code changes
require a re-analysis (menu `f`) to persist the new results into stored records._

### Added

- **Financing Robustness — a new scored factor** (`analysis/metrics/financing_robustness.py`).
  Measures how much rate and amortization stress a deal absorbs before its per-type
  DSCR covenant is breached and before cash flow hits zero, reported as **two
  separate readings** — rate risk is scheduled/certain (the term matures and renews
  at market), amortization risk is conditional on a forced refinance — plus the
  spread between the covenant-breach and cash-flow-zero points. Rate margin is
  weighted more heavily (0.7 / 0.3). The 0–100 sub-score takes the scoring weight
  vacated by DSCR and Cash Flow (see Changed); its reference denominators (250 bps,
  10 yr) live in `config/underwriting.json`. Output reads, e.g., "covenant breach
  +158bps · cash flow zero +441bps · amortization tolerance +6.3yr".
- **Break-even financing diagnostic** (same module) — the financing terms a deal
  needs to reach positive cash flow and DSCR ≥ its covenant (e.g. "DSCR≥1.25 up to
  7.71% · cash-flow-positive up to 10.54% at 25yr"), with a verdict flagging deals
  that fail under **all** realistic terms as a distinct category from those that
  merely miss current assumptions.
- **Covenant score cap** — a post-hoc gate: a property whose current (unstressed)
  DSCR is below its per-type covenant cannot score above `covenant_score_cap`
  (`json/score_weights.json`, default 60). Covenant compliance is a gate, not a
  factor strong projected returns can average away. The cap resolves the covenant
  from config, floors nothing (it only lowers), and skips records with no numeric
  DSCR (no-debt / pending) so a missing value never triggers a false cap.
- **Per-type covenant DSCR** (`config/financing.json`): each asset class carries a
  `covenant_dscr` (= its lending `dscr_floor`; residential 1-4 uses the new
  top-level `residential_covenant_dscr` fallback, 1.10), shared by the robustness
  margins and the covenant cap so the two configurations stay consistent.
- **"Pending re-analysis" marker.** A stored record analysed before the robustness
  factor existed has no stored value; it now reads as *pending* — the factor is
  dropped and the remaining factors renormalize to their original relative weights
  — instead of silently scoring a real 0 and docking the deal ~20%. The marker
  rides on the property card, the city view's Deal Score card, and the detail
  modal's score breakdown.
- **New design document** `docs/scoring-design.md` — records every change, the
  rejected alternative, the score-interpretation impact, and the deliberate,
  non-standard choices.

### Changed

- **City metric factors normalize per-listing, then average** (`scoring/city_ranker.py`).
  Previously the raw metric was averaged across active listings and only the single
  city mean was normalized — but the normalization ramp's clamp is non-linear, so
  average-then-normalize erased real signal (Jensen's inequality): a Kingston
  listing at 8.19% IRR scored 0 because the market mean (5.8%) sat below the floor.
  Normalizing each listing first fixes it. Cities scoring exactly 0 on the collinear
  factors fell sharply — CoCR 71→36, IRR 66→44, DSCR 68→57, Cash-Flow 69→27 of 109.
- **Scoring floors extended into negative territory.** CoCR ramp `[0,12]` →
  `[-10,15]`; Cash Flow is rebased from absolute dollars (`[0,50000]`) to **% of
  asking price** on `[-6,8]`, removing the deal-size bias where a $20M deal
  trivially cleared a fixed-dollar bar a $5M deal never could. Rank order is now
  preserved below break-even (a −0.8% CoCR sorts above a −50% one). **A negative
  CoCR remains a failing deal** — the floors only restore ranking resolution.
- **Modelled hold shortened 30 → 10 years** (`config/financing.json`; matches ARGUS
  and major-brokerage underwriting). Equity Multiple had been pinned near 100/100
  for almost every deal (a 30-yr hold makes 3× trivial — 10% of scoring weight
  acting as a constant); a 10-yr hold restores its discrimination (median EM
  8.45× → 1.96×, factor σ 5.1 → 36.9). IRR shifts with the horizon, so the IRR ramp
  was recalibrated `[4,20]` → `[0,18]` (property and city `act_irr`).
- **CoCR / DSCR / Cash Flow de-collinearized.** These are three views of the same
  NOI-minus-debt-service relationship. The model now **scores CoCR** and makes
  **DSCR and Cash Flow display-only** (weight 0), freeing 0.20 of weight for the
  robustness factor. DSCR and Cash Flow are still computed and shown on the card —
  just no longer triple-counted; covenant compliance is enforced by the cap above.
- **Card and city labels reconciled to the scoring ramps** (`reporting/property_report.py`,
  `reporting/city_report.py`). The cards had advertised "≥7% cap strong / ≥10% CoCR
  / ≥15% IRR / ≥1.5 DSCR" while the engine scored on entirely different boundaries;
  metric colours and captions now track the actual ramp (green at/above the ceiling,
  red below the floor, amber on the ramp).

### Fixed

- **`solve_targets` now carries the recomputed robustness sub-score** through each
  bisection step (`scoring/scorer.py`), so the "what would make this a 100/100"
  lever search reflects financing fragility instead of a stale value.

---

## [3.6.5] — 2026-07-20

_Based on 3.6.3 (per-type financing). 3.6.4 is reserved for the pending
re-analyze error-logging patch, which merges independently._

### Fixed

- **Mixed-use NOI was materially overstated when a listing carried a net/NNN lease tag.**
  The engine applied one lease-derived expense ratio building-wide, but under the Ontario RTA
  (2006) residential maintenance obligations are non-waivable and can't be passed to residential
  tenants — a net/NNN tag can only describe the *commercial* lease. Mixed-use now uses a
  **per-component income/expense engine** (`analysis/metrics/income.py::MixedUseComponents`): the
  commercial expense ratio is looked up by lease type (NNN → the NNN default; gross → the gross
  commercial default) while the **residential component always uses the residential default,
  regardless of the tag**. EGI, opex, NOI, cap, DSCR, cash flow, BEO, and all financing math derive
  from the component rollups; Vacancy Rate and Expense Ratio now display the blended effective
  values (the latter labeled "(blended)"). On the Bayside NNN regression this cut NOI from an
  overstated $88,240.88 to $69,870.40 (~21%). Applies to property type `mixed_use` **only**; every
  other type keeps its existing single-ratio behavior byte-for-byte.
- **A net/NNN lease tag no longer collapses a pure residential property's expense ratio to the
  ~0.08 NNN default** (`PropertyInput.__post_init__`) — same non-waivable-obligations principle;
  residential/multi-family keep their residential default whatever the tag says.
- **The card no longer prints internal config prose.** Config blocks that surface on a card now
  carry a card-facing `display` key alongside internal `notes`; the renderer reads `display` only
  and renders nothing when it's absent (never falls back to `notes`). Fixes the MLI small-balance
  flag, which had been printing routing instructions and the internal `min_practical_loan` variable
  name. New copy: "Loan under $1M — CMHC costs/timeline rarely pencil at this size; shown as
  secondary option."

### Added

- **New mixed-use card fields** (`Components` section): `Commercial Share of GPR`, a
  commercial-majority warning when that share exceeds `commercial_majority_threshold` (config,
  default 0.50 — "lenders may classify and price this as commercial, not mixed-use"), and
  `Commercial Lease Expiry` (a passthrough field, never fetched; renders "unknown ⚠" when absent,
  since an unknown single-tenant term is itself a binary-vacancy signal).
- **`Refi Headroom`** on the card for any DSCR-floor type whose **LTV** constraint binds:
  `DSCR Max Loan − Max Supportable Loan` — the additional debt income supports at the current NOI.
  Omitted when DSCR binds or there's no DSCR floor. Purely derived from existing fields.
- **New config** (`config/screener_config.json`): `component_vacancy` (residential 0.04 /
  commercial 0.125, mixed-use only), `mixed_use_commercial_gross_expense_ratio` (0.40), and
  `commercial_majority_threshold` (0.50). A `commercial_lease_expiry` passthrough field on
  `PropertyInput` / the record.

### Changed

- The single NOI Growth Assumption blends two regimes on mixed-use (guideline-capped residential
  vs. contractual commercial escalations) — documented in-code as acceptable for a screener and
  flagged for a future per-component growth pass. No card change.
## [3.6.4] — 2026-07-20

### Changed

- **Re-analyze all (menu `r`) now surfaces its errors instead of swallowing them.** Previously
  `_reanalyze_all` caught every non-`ValueError` exception as a bare `errors += 1` count with no
  message, traceback, or log — so a run reporting "20 errors" gave no way to see *which* properties
  failed or *why*. It now prints a one-line summary per failed property (address · MLS · type ·
  exception) to the console and writes full tracebacks to `json/reanalyze_errors.log`. A clean run
  clears any stale log so it can't mislead. (`ValueError`/missing-rate cases are still counted as
  "skipped", unchanged — that path already has an obvious cause.) (`ui/menu.py`.)

## [3.6.3] — 2026-07-19

### Added

- **Per-property-type financing** — the same logic [3.6.2] applied to make financing global now
  refines it by asset class, because one down-payment / rate / amortization across office, hotel,
  and multifamily would be as wrong as one expense ratio. `config/financing.json` gains a second
  layer: `defaults` (the four house-wide scalars, unchanged, still edited via menu `f`) plus an
  optional `property_types` map. `analysis/financing_config.py::get_financing(property_type, units,
  loan_estimate)` shallow-merges the resolved type block over `defaults`, deriving down payment from
  `max_ltv`, interest rate from the `rate_low`/`rate_high` midpoint, and amortization from
  `amort_years`. `hold_years` stays house-wide. **All routing lives in this module**: the
  `retail_office → office` alias, the multi-family 1-4/5+ split by unit count, and the
  multi_family_5plus small-balance decision (below `min_practical_loan`, conventional is primary and
  CMHC is flagged secondary; at or above it, CMHC MLI Select is primary). An absent/empty
  `property_types` map reproduces pre-per-type behavior exactly (asserted by a regression test).
- **Financing analysis on the card** (new `analysis/deal_financing.py`, additive alongside the
  type-agnostic `MortgageCalculator`): LTV-constrained and DSCR-constrained loan ceilings, which one
  binds (`Binding Constraint: LTV | DSCR | n/a (GDS/TDS)`), per-door economics (`Units`,
  `Price / Door`, `Avg Rent / Door`), and a CMHC / MLI Select panel for 5+ unit multifamily
  (eligibility, 85%/95% LTV loan sizes, up-to-50-yr amortization, small-balance flag). Rendered in
  new **Mortgage & Financing** and **Units & CMHC** sections of the report modal.
- **Rent-line provenance tags** — every rent-detail line now carries `[A]` (advertised/in-place
  from the listing) or `[M]` (market-rate placeholder). Any `[M]` dollars count as *estimated* in
  the Income verified/estimated split, fixing the bug where a `$/sqft` or city-average rent could
  display as 100% verified.
- **Price-drop-velocity read** — the Deal Context "Read" now fires a motivated-seller signal on a
  fast cut (≥10% off at ≤60 days on market, regardless of staleness) and reads monthly seller bleed
  to distinguish circumstantial motivation (low carrying-cost pressure) from financial distress. It
  fires independently of, and alongside, the existing staleness read.
- **`config/screener_config.json`** (loaded via `analysis/screener_config.py`, hard-fail on missing
  key) holds all new thresholds: break-even-occupancy display cap / 85% warning, and the
  price-drop-velocity trigger (10% / 60 days / $1,000 monthly bleed).

### Changed

- **Break-even occupancy** now uses a fixed/variable expense split
  (`fixed_expense_fraction` per type): `BEO = (ADS + f·opex) / (GPR · (1 − ((1−f)·opex / EGI)))`,
  capped at 100% with a `⚠` marker above 85%. The old formula assumed *all* expenses scale with
  occupancy, understating break-even. (`analysis/metrics/cash_flow.py::DebtMetrics`; the two BEO
  unit tests were rebaselined to the new formula.)
- Financing resolution is per-type at a single layer (`_record_to_prop` and `_prompt_property`);
  `PropertyInput`, `MortgageCalculator`, and the returns math are untouched — they still receive
  resolved scalars, so the calculator never learns property types exist. Scoring weights and
  formulas are unchanged; score *outputs* shift where financing inputs shifted (per-type LTV/rate
  and the corrected verified-income split).

## [3.6.2] — 2026-07-19

### Changed

- **Down payment, interest rate, amortization, and hold period are now global settings**, not
  per-property fields. In practice every property in the portfolio carried the identical values
  (20% down / 4.5% / 25-yr amortization / 30-yr hold), so entering them on each add/edit was
  redundant. They now live in one file, `config/financing.json`, loaded via
  `analysis/financing_config.py` (same hard-fail-on-missing-key philosophy as `underwriting.json`).
  - New main-menu option **`f` — Global financing defaults** edits the four values and offers to
    re-analyze all properties so the change flows into every mortgage, cash-flow, and return
    figure. (`ui/config_editor.py::_edit_financing_defaults`.)
  - `_record_to_prop` now sources these four values from the global config, ignoring any stale
    per-record copies — so a global change propagates to every property on the next re-analysis,
    exactly like NOI growth and the other house assumptions. Stored records still keep a snapshot
    of the values used at their last analysis (for display), refreshed on re-analysis.
  - The Add (option 3), realtor.ca URL importer (`u`), and CSV import (option 9) paths no longer
    prompt for these; they inherit the global values. The Add and Edit screens show the current
    global financing for reference. The per-property Down payment / Interest rate / Loan term /
    Hold years rows were removed from the Edit menu (remaining fields renumbered).
  - No changes to `PropertyInput`, `MortgageCalculator`, or the returns math — the globalization
    happens at the UI/record layer, so all existing analysis and scoring behaviour is unchanged.
- **Expense ratio removed from the per-property Edit menu.** It is *not* a flat global (that
  would be wrong: NNN ≈ 8%, hotel ≈ 63%, multi-family ≈ 45%). It is already set globally **by
  property type and lease** via `models/constants.py::EXPENSE_RATIO_DEFAULTS`, so exposing it as a
  per-listing editable field was misleading. It now always derives from type/lease (and still
  re-derives automatically when a property's type or lease is changed). Existing stored values are
  preserved until such a change; no property's expense ratio is silently altered by this release.

---

## [3.6.1] — 2026-07-04

### Fixed

- **Cap rate was double-counted in the confidence path** (`scoring/scorer.py`). A flagged cap
  rate previously reduced the score twice: once via its direct confidence haircut, and again
  by proxy — `is_high_income_conf` required *both* verified income above threshold *and* an
  unflagged cap rate, so a lone cap-rate flag forced income confidence to read "low" and opened
  the DOM/Price Drop amplifier even when income itself was 100% verified. `is_high_income_conf`
  now keys on verified income only. The amplifier's engage condition is now explicit and
  config-driven: it fires when income confidence is genuinely low
  (`low_income_conf_always_engages_amplifier`), or when at least `amplifier_engage_min_signals`
  independent risk signals (e.g. flagged cap rate *and* thin market) are present together — a
  lone cap-rate flag no longer opens it. Verified against the two reference properties: 40
  Lindsay St S, Lindsay (100% verified income, 11.01% cap) rises from 82.1 to 96.5 now that its
  clean income is no longer punished twice; 827 2nd Avenue E, Owen Sound (30.86% verified) still
  engages the amplifier via its own low income confidence.
- **High-cap-rate haircut was a binary cliff** (`analysis/metrics/income.py`,
  `IncomeConfidenceMetrics`). A cap rate one basis point over `cap_rate_risk_threshold_pct` took
  the full haircut; one basis point under took none, and every cap rate above the threshold took
  the *same* haircut regardless of how far above it sat. Replaced with a graduated haircut: zero
  at/below the threshold, growing linearly at `cap_rate_risk_slope` per point above it, capped at
  `cap_rate_risk_max_haircut` so no cap rate — however extreme — can annihilate the score. Tuned
  so an 11% cap rate continues to land close to the old fixed 0.97 factor (continuity), while
  827 2nd Avenue E's 12.74% cap now takes a materially larger haircut (0.082) than 40 Lindsay St
  S's 11.01% (0.030) — previously identical at 0.03. Confirmed smooth scaling at 9.9/10.1/11/
  12.74/15/20% cap rates and that no property in the portfolio (522 scored) falls through the
  score floor.
- Replaces the removed `cap_rate_risk_confidence_factor` config key with
  `cap_rate_risk_slope` / `cap_rate_risk_max_haircut`, and adds `amplifier_engage_min_signals` /
  `low_income_conf_always_engages_amplifier`. All new values are config-driven, not hardcoded.
  Structural rows (DSCR, cap rate, NOI, IRR) unchanged.

---

## [3.6.0] — 2026-07-04

### Added

- **Market/listing-signal confidence axis** (`scoring/scorer.py`). DOM ("Market Staleness") and
  Price Drop % previously carried a fixed positive weight in the raw score (`json/score_weights.json`),
  treating a long time-on-market or a big price cut as unconditionally good. Both signals actually
  carry no fixed sign — the same listing can mean "motivated seller, negotiating room" or "something's
  wrong, verify before you buy" depending on the rest of the deal. Both weights are now **0** in
  `json/score_weights.json` — they never move the score on their own. Instead, new helpers
  `_dom_band`, `_drop_band`, and `_liquidity_band` classify DOM (normal/aging/stale), Price Drop
  (none/modest/large/severe), and market liquidity (liquid/moderate/thin — a config-weighted proxy
  from `city_distances.json` distance-to-major-centre and `city_demographics.json`
  population/growth). A stale or steeply-discounted listing **amplifies** the existing
  `confidence_multiplier` haircut (bounded by `market_signal_confidence_floor`), but only when the
  deal isn't already high-confidence (verified income, cap rate in range) *and* liquid — a clean,
  fully-verified, liquid deal with the same signals scores exactly as it would without them.
  Verified with targeted unit tests and against the live report: a high-confidence/liquid
  stale+discounted property scores identically to a normal one; a low-confidence/thin-market
  property with the same signals gets a deeper, floor-bounded haircut.
- **"Deal Context" panel** (`reporting/property_report.py`). Every property's report modal now
  shows a neutral, factual panel: Days on Market (with band), Price Change (with band), Market
  liquidity band, Income verification %, and a "Read" line that states what the signals imply
  without recommending for or against the deal — no buyer-appetite bias anywhere in the scoring
  path (confirmed by a grep-based test).
- **`config/underwriting.json` gains eighteen new keys** for the axis above: `dom_normal_days`,
  `dom_stale_days`, `drop_modest_pct`, `drop_large_pct`, `drop_severe_pct`,
  `market_signal_verified_income_threshold_pct`, `dom_stale_confidence_factor`,
  `price_drop_confidence_factor`, `joint_signal_confidence_factor`,
  `thin_market_confidence_factor`, `market_signal_confidence_floor`,
  `liquidity_distance_reference_km`, `liquidity_population_reference`,
  `liquidity_weight_distance`, `liquidity_weight_population`, `liquidity_weight_growth`,
  `liquidity_liquid_threshold`, `liquidity_thin_threshold`.

### Fixed

- **Price/Sq Ft labeling ambiguity** (`analysis/metrics/pricing.py`, `reporting/property_report.py`).
  A mixed-use property showed two different real Price/Sq Ft numbers under the same generic label:
  the graded row used the ground-floor commercial area as the denominator (much higher $/sqft),
  while the report modal's client-side figure used the whole building. Both were correct for what
  they measured, but neither was labeled with its scope, so they looked like conflicting numbers
  for the same metric. Now labeled explicitly — `"Price/Sq Ft (Mixed-Use, Ground Floor)"` when the
  ground-floor-only denominator is used, and `"Price / Total Sq Ft"` for the whole-building figure
  in the modal. Neither calculation changed.

### Docs

- Documented that **Seller Bleed** and **CELOC Speed Score** (`analysis/metrics/returns.py`,
  `MarketMetrics`) are informational listing-economics rows computed from live per-property
  inputs each analysis run — confirmed neither metric name is read anywhere in `scoring/scorer.py`,
  so neither feeds the score.
- `README.md` updated for the new config keys, the market-signal confidence axis, the Deal Context
  panel, and corrected metrics glossary entries for CELOC (was documenting the wrong formula),
  Price Drop, and DOM (removed the fixed-sign "higher discount/longer DOM = better" framing).

### Tests

- **`tests/test_scoring_scorer.py`** — `test_config_weights_sum_to_1` updated for the intentional
  Price Drop/DOM zero-weighting; new `TestMarketSignalConfidence` class covers the high-confidence/
  liquid no-penalty case, the low-confidence/thin-market amplified case, the "signals alone don't
  move the score" invariant, and the appetite/bias grep check.
- **`tests/test_scoring_scorer_branches.py`** — `_poor_record()` fixture updated with
  `verified_income_pct`/`confidence_multiplier` so the pre-existing `solve_targets` bisect-lever
  tests (which predate this feature and don't model income confidence) aren't penalized by the new
  axis for a missing field a real analyzed property always sets.
- Full suite (1291 tests) passes; coverage 95%.

---

## [3.5.6] — 2026-07-04

### Added

- **Data-confidence axis: `IncomeConfidenceMetrics`** (`analysis/metrics/income.py`,
  `analysis/rent_resolver.py`). Income is no longer treated as uniformly trustworthy: `RentResolver`
  now tags each resolved income line as verified (stated in the listing, or tied to the property's
  own measured attributes — sqft, unit count) or imputed (a residential unit priced at a city-wide
  bedroom-type average — the existing "Unknown" unit-type bucket, or the rarer missing-rate
  fallback average). Imputed lines carry the coefficient of variation of the *same* city rent
  sample used to build that average — a measured spread, not an invented risk premium. New report
  rows: "Income Verification" (verified % / estimated %), an estimated-income $ range using the
  measured spread instead of a false-precision point value, and a "Confidence Multiplier" row. The
  multiplier is applied to the **overall property score only** (`scoring/scorer.py`, which now also
  returns `raw_score` alongside the adjusted `score`); every existing graded row (DSCR, cap rate,
  NOI, IRR, equity multiple) is unchanged. Verified against the live portfolio: a property with
  ~31% verified / 69% imputed income (Owen Sound, 2-bed "Unknown" residential units) gets a small,
  bounded haircut (0.96×); a fully-verified property gets exactly 1.0×; the worst case across the
  full 539-property portfolio is 0.93× — confirming the haircut stays small in practice.
- **High-cap-rate soft flag** (`analysis/metrics/income.py`). A cap rate above
  `cap_rate_risk_threshold_pct` (config, default 10%) no longer reads as pure upside: a new
  "Cap Rate Risk Check" row flags it as a market signal of illiquidity/vacancy/value-erosion risk
  the structural metrics can't see. It does not fail the deal or touch the Cap Rate grade itself —
  it feeds a small, bounded, config-driven reduction (`cap_rate_risk_confidence_factor`) into the
  same data-confidence multiplier above. Verified against real listings: Lindsay (11.01% cap) and
  Owen Sound (12.74% cap) both raise the flag; a normal ~5.5% cap property does not.
- **`config/underwriting.json` gains six new keys**: `stress_rate_bump`, `stress_min_dscr`,
  `confidence_uncertainty_start`, `confidence_steepness`, `confidence_floor`,
  `cap_rate_risk_threshold_pct`, `cap_rate_risk_confidence_factor` — every threshold and shape
  parameter introduced by the two features above lives in config, matching the existing
  house-assumption pattern (`analysis/underwriting_config.py`, required-keys hard error on a
  missing file/key).

### Changed

- **Stress test bump and pass threshold moved out of hardcoded Python defaults into config**
  (`analysis/metrics/cash_flow.py`, `analysis/analyzer.py`). `DebtMetrics` previously defaulted
  `stress_rate_bump` to a class constant and graded PASS/FAIL against a literal `1.20`; both now
  come from `config/underwriting.json` via `analyzer.py`, consistent with the "every risk constant
  lives in config" rule. The underlying stress-test calculation itself (re-pricing the mortgage
  payment at `interest_rate + stress_rate_bump` via `amortization_payment()`) was already correct —
  verified against real properties (Owen Sound: $280k loan, 4.5%→6.5%, payment $18,596.69→
  $22,506.08, a +21.0% increase, matching an independent hand-calc exactly) — so no behavioural
  regression, only the config wiring changed. Confirmed the new config values are load-bearing:
  raising `stress_min_dscr` from 1.20 to 2.0 drops the portfolio PASS count from 143 to 37.

### Tests

- **`tests/test_metrics_income.py`** — `test_rows_count` updated for the new "Cap Rate Risk Check"
  row (8 metric rows instead of 7).
- Full suite (1287 tests) passes unchanged otherwise; no existing metric, score, or report output
  changed for any property that has no imputed income and a normal cap rate.

---

## [3.5.5] — 2026-07-04

### Changed

- **A cash-flow stream with no real IRR now reports "IRR not meaningful" instead of a −100% floor**
  (`analysis/metrics/returns.py`). When `numpy_financial.irr` returns `nan` (e.g. an underwater exit
  whose flows never turn positive) there is no honest rate to print, so `irr` is `None` and the report
  row reads `IRR not meaningful` with a WARN grade — never NaN, 0, blank, or a substitute number
  dressed up as a real return. The zero-hold / no-equity branch reports the same instead of −100%.
  `PropertyScorer` keeps the unparseable IRR as `None` (scoring contribution 0, as before) and the
  deal-watchlist/property reports render it as "—" via their existing null formatting; previously a
  missing IRR could surface as a fake `0`. No live property is affected numerically: all 234
  capital-call deals in the current 539-record portfolio still resolve to a finite `npf.irr` root.
- **Guardrail also fires when IRR is missing in the no-capital-call regime.** A single outflow at t0
  plus non-negative later flows has exactly one sign change, so a real IRR must exist there; `irr is
  None` in that regime now raises `IRR/EM mismatch` instead of being skipped silently.
- **NOI growth is now a single flat house-standard assumption, not per-city population growth**
  (`analysis/analyzer.py`). `_resolve_noi_growth` no longer reads `growth_pct_annual` from
  `json/city_demographics.json` — that field is 2016→2021 census population growth, not rent growth,
  and was modeling shrinking-population towns (e.g. Owen Sound, −0.32%) as having shrinking rents for
  30 years, which is false: rents track inflation regardless of local population trend. Priority is
  now explicit per-property `noi_growth_rate` override → `noi_growth_default` from the new
  `config/underwriting.json` (ships at 2%, matching how institutional underwriters apply one flat rate
  to every deal and let local variation show up in Year-1 NOI and cap rates instead).
  `city_demographics.json` itself is untouched — `scoring/city_ranker.py` still uses it for city
  opportunity depth. On the live 504-property portfolio, Owen Sound's Equity Multiple rose from 9.89×
  to 19.64× and its IRR from 21.23% to 25.91%; no property's NOI growth assumption is negative anymore.
- **All underwriting assumptions now live in one config file, not hardcoded literals.** New
  `config/underwriting.json` holds `noi_growth_default`, `exit_cap_spread_bps` /
  `exit_cap_aging_bps_per_year` (previously the hardcoded `MARKET_DRIFT_BPS`/`AGING_BPS_PER_YEAR` in
  `ExitCapEstimator`), and `inflation_rate` (now drives the NOI Growth Assumption's grading band,
  previously a hardcoded 1%–3%). New `analysis/underwriting_config.py` loads and caches it; a missing
  file or required key raises `UnderwritingConfigError` instead of silently falling back to a buried
  literal. Changing a value in `config/underwriting.json` moves every property's returns on the next
  analysis with no code edit.
- **NOI Growth Assumption is graded like every other metric** in the property report, using the
  configured `inflation_rate` ±1pt band (GOOD at or above the top of the band, FAIR within it, POOR
  below).

### Added

- **`selling_costs` parameter on `ReturnMetrics`** (default 0): net sale proceeds are
  `exit_price − outstanding_loan_balance_at_year_N − selling_costs`, so records that carry selling
  costs can deduct them from the exit flow. No caller passes a value yet (the property record has no
  such field), so live numbers are unchanged.

## [3.5.4] — 2026-07-04

### Fixed

- **IRR and Equity Multiple are computed independently from one shared cash-flow array**
  (`analysis/metrics/returns.py`). Neither metric is derived from the other. `ReturnMetrics` builds a
  single period vector — `cash_flows[0]` = −equity invested, `cash_flows[1..N-1]` = operating cash
  flow each year (NOI escalates at the growth rate, mortgage fixed), `cash_flows[N]` = operating cash
  flow + **net** sale proceeds — and reads both metrics off it.
- **Equity Multiple uses NET sale proceeds, not gross** (BUG 1). The sale component is
  `exit_price − outstanding_loan_balance_at_sale` (the amortized balance at year N, 0 once the loan is
  fully paid off before the modeled sale), so the loan payoff is deducted before the investor is
  credited. `equity_multiple = sum(cf for cf in cash_flows if cf > 0) / equity_invested`.
- **IRR is computed with `numpy_financial.irr` over the shared array, not back-derived** (BUG 2). The
  prior release had set `irr = equity_multiple**(1/years) − 1`, which discards cash-flow timing; that
  is reverted. IRR now reflects when cash actually arrives — across the live 522-property portfolio it
  lands both above the multiple's compound rate on front-loaded deals and below it on leveraged
  (capital-call) deals, and matches `numpy_financial.irr` to full precision. `numpy_financial` is a
  new runtime dependency (added to `requirements.txt`). `npf.irr` returning `nan` on an underwater
  exit floors IRR to `−100%` so it is always a real number.
- **Guardrail asserts IRR ≥ the multiple's implied rate — where that premise holds.** After computing,
  `implied_rate = equity_multiple**(1/N) − 1`; a shortfall means the shared array is wrong, so it
  raises (`"IRR/EM mismatch — recheck cash-flow array"`) rather than silently setting `irr =
  implied_rate`. The premise "cash during the hold lifts IRR to at or above the implied rate" only
  holds when there are **no interim capital calls**; a leveraged deal whose mortgage exceeds NOI in
  early years injects cash mid-hold, which legitimately pulls IRR below the implied rate. Applying the
  assertion unconditionally raised on **195 of 539** live properties (all with negative early cash
  flow), so the assertion runs in the regime where its premise applies (all post-entry flows
  non-negative). New regression tests in `tests/test_metrics_returns.py` cover independence from the
  multiple, net-vs-gross proceeds, timing sensitivity, the guardrail firing on a forced-broken array,
  and capital-call / underwater deals computing rather than crashing.

## [3.5.3] — 2026-07-03

### Added

- **Cross-metric consistency test suite** (`tests/test_consistency_invariants.py`): 64 checks that
  drive a matrix of Canadian property configurations through the real `CommercialPropertyAnalyzer`
  and assert the independently-computed metric groups agree with each other — the class of check
  that catches silent arithmetic regressions a single-formula unit test misses. Asserts, among
  others: annual debt service == monthly payment × 12; `exit_price × exit_cap == terminal NOI`; the
  origination identity `loan/price + down_payment_pct == 1`; `price_per_sqft × denominator == cost
  basis`; and cap rate reconstructs NOI. It also **locks the Canadian semi-annual compounding
  convention** (Interest Act s. 6, `(1 + rate/2)^(1/6) − 1`) and confirms the payment lands below
  the naive US-monthly figure, so a regression to `annual_rate/12` fails the suite. The matrix is
  entirely Canadian (Ontario + BC) — no US/monthly-compounding data.

### Changed

- **Canadian compounding now recognizes every jurisdiction in any form**
  (`analysis/mortgage.py`). `compounding_for_province` previously matched only 2-letter codes, so a
  spelled-out province name ("Ontario", "Québec") would have silently fallen through to the
  US/monthly branch. It now normalizes full names via `PROVINCE_NAME_TO_CODE` before checking
  membership, so all 10 provinces + 3 territories reach the semi-annual branch (Interest Act s. 6)
  whether recorded as a code or a name. Semi-annual compounding is federal and uniform across
  jurisdictions — there is no per-province formula split — and the US/monthly branch is untouched as
  the fallback for anything not recognized as Canadian. New tests assert every jurisdiction (by code
  and by full name, including accented "Québec") compounds semi-annually and that all 13 remain in
  the set.

- **Metrics no longer emit silent fallbacks** (`analysis/metrics/pricing.py`, `income.py`,
  `cash_flow.py`, `returns.py`, `analysis/analyzer.py`). Broken or missing mandatory inputs used to
  render a plausible-looking value (e.g. a fabricated GRM of cost basis ÷ 1, a `0.00%` return, or a
  bare `inf` DSCR); now:
  - **Mandatory data fails loudly.** A missing/zero square footage or a zero exit cap rate raises
    `ValueError`. Menu callers already catch this and route the property to a partial "no analysis"
    record, so batches don't crash — the bad field is surfaced instead of faked. The
    `annual_rent if annual_rent else 1` stand-in in `analyzer.py` was removed.
  - **Legitimate edges are flagged, not faked.** GRM shows `N/A (no rent)` for a property whose city
    has no rent data yet (the tested partial-analysis path is preserved); DSCR and the stress test
    show `N/A (no debt)` for an all-cash deal; CoCR, Equity Multiple, and CELOC show
    `N/A (no cash invested)`. The underlying `inf`/`0` attributes are unchanged, so no existing math
    or downstream consumer regresses — only the rendered rows gained flags.

## [3.5.2] — 2026-06-30

### Changed

- **The four remaining focused reports are now interactive**, matching the Deal Watchlist
  (`reporting/negotiation_report.py`, `reporting/vacancy_report.py`,
  `reporting/price_drop_report.py`, `reporting/benchmark_report.py`). Each now embeds its data as
  JSON and renders client-side, so **every column is click-to-sort** (click a header, click again
  to reverse) and each carries the filters that fit it:
  - **Negotiation Targets** — Min Score, Min Cap Rate, and Min Room % (how far the target price
    sits below today's asking); a sortable "Room" column was added.
  - **Vacancy Sensitivity** — Min Score and a "cash-flow positive at [occupancy]" filter that
    keeps only deals that stay in the black at the chosen 100/85/75/60% level.
  - **Price Drop Alerts** — Min Drop % and a Status filter (all / active / inactive).
  - **Cap-Rate & $/sqft Benchmarking** — a Verdict filter (underpriced / at market / overpriced)
    and Min Comps, so weak one- or two-comp benchmarks can be hidden.

  The per-report compute helpers stay server-side and unchanged (`vacancy_grid`,
  `benchmark_rows`); only the rendering moved into the page. Row escaping is client-side (`esc()`).
  The report tests were reworked to assert on the embedded data set and the interactive machinery.

## [3.5.1] — 2026-06-30

### Changed

- **Deal Watchlist is now interactive** (`reporting/deal_watchlist_report.py`, `ui/menu.py`): the
  report changed from a static, server-rendered table to a client-side one that embeds the deal
  data as JSON and renders in the browser, so that:
  - **every column is click-to-sort** (click a header to sort by it, click again to reverse, with
    ▲/▼ indicators; default Score ↓), and
  - the list **filters live** by minimum score, minimum cap rate, and minimum price drop (Min Score
    seeded to 55; Apply/Reset).

  The report now embeds **active listings only** (the watchlist is about deals still actionable),
  so the redundant Status column was dropped and `_open_watchlist_report` no longer prompts for a
  score — filtering happens in the page. Row escaping moved client-side (an `esc()` helper) since
  rows render in JavaScript. The watchlist tests were reworked to assert on the embedded data set
  (active + scored only) and the interactive machinery rather than on pre-filtered server output.

## [3.5.0] — 2026-06-30

### Added

- **Five focused HTML reports, each as its own standalone generator + menu option**
  (`reporting/deal_watchlist_report.py`, `reporting/negotiation_report.py`,
  `reporting/vacancy_report.py`, `reporting/price_drop_report.py`,
  `reporting/benchmark_report.py`, `ui/menu.py`). Each is built from the same scored property
  set (`PropertyMenu._build_report_row`), renders a server-side table in the shared palette (the
  `price_check_report.py` pattern), and opens in the browser. The existing Investment Report
  (option 6) and City Rankings (option `c`) are unchanged and reused, not duplicated.
  - **Deal Watchlist** (menu `w`): scored deals at or above a score threshold (prompted, default
    55), sorted best-score first, showing cap rate, cash-on-cash, IRR, annual cash flow, DSCR,
    days-on-market and price drop.
  - **Negotiation Targets** (menu `n`): for each active, scored deal, the single lever
    (price / rent / interest rate / down payment) that alone would lift it to a perfect score,
    with the gap from today's asking. Uses the scorer's `solve_targets`.
  - **Vacancy Sensitivity** (menu `v`): cap rate and annual cash flow for every income property
    at 100 / 85 / 75 / 60% occupancy, holding debt service constant. Debt service is taken from
    the province-aware `MortgageCalculator` (semi-annual Canadian compounding), not a
    reimplemented formula. The per-occupancy grid is a pure `vacancy_grid(row)` helper.
  - **Price Drop Alerts** (menu `d`): listings whose current asking has fallen below their
    original list price (`original_price`), ranked by the largest percentage cut. A 0.1% epsilon
    screens out rounding noise; inactive listings are included.
  - **Cap-Rate & $/sqft Benchmarking** (menu `b`): each property's price-per-sqft and cap rate
    against the average of comparable listings, preferring the tightest comp set available
    (city+type → province+type → type-wide) and excluding the property from its own average. The
    basis used is shown so comp strength is visible; each row is flagged underpriced / at market /
    overpriced (±10% from peers). Comparison logic is a pure `benchmark_rows(rows)` helper.
- **70 tests** across the five new report modules
  (`tests/test_deal_watchlist_report.py`, `tests/test_negotiation_report.py`,
  `tests/test_vacancy_report.py`, `tests/test_price_drop_report.py`,
  `tests/test_benchmark_report.py`), covering filtering, sorting, metric/verdict thresholds, the
  vacancy occupancy math, the benchmark peer-group fallback and self-exclusion, and HTML escaping.

## [3.4.0] — 2026-06-30

### Changed

- **City opportunity model rebuilt around "good deals AND enough of them"**
  (`scoring/city_ranker.py`, `json/score_weights.json`, `reporting/city_report.py`,
  `ui/config_editor.py`): the old model averaged a city's metrics then shrank the result toward
  a hardcoded `50` anchor scaled by `n / (n + k)`, which clustered cities and let large markets
  with mediocre deals rank near the bottom. Opportunity is now the weighted **geometric mean**
  of two 0–1 axes — `opportunity = 100 · quality^quality_exp · depth^depth_exp`:
  - **Quality** is the renormalised weighted blend of the deal/market factors, independent of
    city size, and drives the report's "Deal-quality contributions" breakdown.
  - **Depth** grows log-scaled with active listing count (`opportunity_depth_ref`); its weight
    is `opportunity_depth_exp` (default 0.4, quality gets the rest).

  Because it's multiplicative, neither axis can carry the other: a huge market of weak deals
  scores low (Ottawa, −3.9% CoCR, sits mid-pack despite max depth) and a single great listing
  scores low (one-listing towns sink). Listing volume is no longer a quality factor (it *is*
  the depth axis); `confidence_k` is display-only now (the report no longer claims it scales
  the score); the stale `opportunity_prior` was removed.

- **Implausible estimated rents are screened from city averages** (`scoring/city_ranker.py`,
  `json/score_weights.json`): an estimated rent can imply an impossible cap rate or
  cash-on-cash (e.g. a 27% cap or 100%+ CoCR — most often on large industrial listings). Such
  listings are now kept in the inventory count but excluded from the city's income averages
  (the same treatment as `LOW`-confidence income), governed by `outlier_max_cap_rate` (12%)
  and `outlier_max_coc` (25%). Previously they inflated a city's mean and could vault it to the
  top (Trenton was the example).

- **City opportunity shows the honest raw score** (`reporting/city_report.py`): the displayed
  number is the raw geometric score (top ~58), not rescaled — if few markets are strong, the
  scores and grades say so (grade bands Excellent ≥75, Good ≥55, Fair ≥35). The grade/colour is
  computed on the same rounded value shown, so the number and label can no longer disagree
  (a 54.7 no longer displayed "55 · Fair").

### Fixed

- **Price-range filter no longer hides cities that have in-range listings**
  (`reporting/city_report.py`, `scoring/city_ranker.py`): the filter matched on the city's
  *average* active price, so a city was hidden whenever its average fell outside the range even
  if individual listings fit (e.g. Cornwall, avg $713k, has listings at $325k–$350k). `CityRanker`
  now emits each city's `active_prices`, and the filter keeps a city if **any** active listing
  falls within the range.

- **City report "Score contributions" no longer misrepresents the model**
  (`reporting/city_report.py`, `scoring/city_ranker.py`): the breakdown was a hardcoded
  JavaScript copy of the weights that had drifted out of sync — it used the wrong weights
  (summing to 110%), silently omitted 6 of the 15 scoring factors (IRR, DSCR, Cash Flow,
  absorption, price trend, best score — ~35% of the score), and carried a mislabeled legend.
  `CityRanker` now emits each factor's actual contribution (`points = normalised × weight ×
  100`, summing to the raw score) and the report renders those directly. The breakdown always
  matches `json/score_weights.json`, and editing the weights now moves the bars.
- **Genuine zeros no longer render as "missing"** (`reporting/city_report.py`,
  `scoring/city_ranker.py`): `fp()`/`fi()` treated `0` as falsy and printed `—`, conflating
  "no price reductions" / "listed today" with absent data. They now show `—` only for
  `null`/`undefined`. `CityRanker` emits `None` (not `0`) for `active_days_on_market` and
  `cap_trend` when there is nothing to average/compare, so the report shows `—` there and
  `0.0%` / `0d` for real zeros. Scoring inputs are unchanged (the missing case still scores
  as a neutral 0).
- **City opportunity colour now matches its grade** (`reporting/city_report.py`): a city
  scoring 55–64 was labelled "Good" but coloured amber. `oppColor` now turns green at the
  same 55 boundary as the "Good" grade.

### Changed

- **Descriptive names for the city result fields** (`scoring/city_ranker.py`,
  `reporting/city_report.py`): the cryptic `act_*` / `inact_*` output keys are now
  self-describing — e.g. `act_cap` → `active_cap_rate`, `act_dom` → `active_days_on_market`,
  `inact_cap` → `inactive_cap_rate`. The `json/score_weights.json` weight/threshold keys are a
  separate persisted config namespace and were intentionally left unchanged.
- **Inactive listings modelled as transacted** (`scoring/city_ranker.py`,
  `reporting/city_report.py`, `ui/config_editor.py`): status is binary (active vs inactive) and
  an off-market listing is treated as sold for the demand/appreciation signals — absorption
  ("Absorption (Inactive Share)") and price trend ("Price Trend (Ask vs Inactive)"). The UI
  labels everything "inactive" (not "sold"); the config-editor descriptions match and now cover
  all 15 factors (previously 9).
- `CityReportGenerator` no longer reads `json/score_weights.json` for thresholds — the
  breakdown comes entirely from the emitted factor data.

### Tests

- Updated `tests/test_reporting_generators.py`, `tests/test_integration_city_report.py`, and
  `tests/test_integration_industrial.py` for the renamed fields and the real-factor contract;
  replaced the obsolete threshold-injection tests with ones asserting the report consumes
  `c.factors`. Added regression guards for the zero-vs-missing rendering, the grade/colour band
  alignment, and the `None`-vs-`0` field semantics.

---

## [3.3.0] — 2026-06-24

### Added

- **Import a property from a realtor.ca URL** (`ui/menu.py`, `scraping/realtor_scraper.py`,
  `models/constants.py`): new menu option `u` — paste a realtor.ca listing URL and the app
  parses the basic data realtor.ca reliably exposes and saves it as an **incomplete,
  un-analyzed record** (empty `results`, `analyzed_on: None`, shown as `—` in the list).
  Units, unit type, and property type can't be read reliably, so they're deliberately left
  blank for the user to complete via Edit (option 4), which then triggers analysis. An
  auto-note records the source URL and lists what to verify.
- **`RealtorScraper.fetch_listing(url)` + `ListingData`** — opens a pasted listing URL
  (reusing the existing persistent-Firefox context, overlay-dismissal, and block/not-found
  detection) and parses: address, asking price, MLS #, storeys → floors, annual property
  taxes, square footage, and listing date. Uses the same manual-CAPTCHA warm-up flow as the
  price check.
- **Listing-detail parsers** (pure, unit-tested, label-based for durability against layout
  changes): `_parse_mls`, `_parse_storeys`, `_parse_taxes`, `_parse_sqft`,
  `_parse_time_on_realtor`, `_clean_listing_address`. Notable rules:
  - **Square footage** — midpoint when given as a range (`A - B`); falls back to
    `DEFAULT_SQFT` (5000) when no area is posted.
  - **Listing date** — derived from "Time on REALTOR.ca": hours → today; days/weeks/months
    counted backwards from today (weeks×7, months×30).
  - **Address** — postal code stripped; spelled-out province normalised to its 2-letter code
    so the result parses cleanly through `_parse_city_province`.
- **`PROVINCE_NAME_TO_CODE`** in `models/constants.py` — maps spelled-out province/territory
  names (as realtor.ca shows them, e.g. "Ontario") to the 2-letter codes the app stores.

### Tests

- Added cases to `tests/test_realtor_scraper_query.py` covering every new pure parser,
  including one that confirms a cleaned address flows correctly through
  `_parse_city_province` (city + province).

## [3.2.1] — 2026-06-16

### Fixed

- **Adding a commercial property for a city with no rate data lost the entry and the city**
  (`ui/menu.py`, `ui/csv_handler.py`, `analysis/analyzer.py`): `RentResolver` raises
  `ValueError` when no market rate exists for a city (Office/Retail/**Industrial**/Mixed-Use/
  Retail-Office). `PropertyMenu._add` caught that, printed an error, and returned **before**
  `save_property` or `ensure_city_in_rates` — so the property was discarded and the city was
  never registered for rate entry. `_add` now mirrors the CSV import: it saves a partial record
  (no analysis results, `analyzed_on: None`) and registers the city via `ensure_city_in_rates`,
  so the user can add rates (option 7/8) and re-analyze.
- **Shared partial-record builder** — extracted `build_partial_record(prop)` in
  `analysis/analyzer.py`; both `_add` and the CSV import now use it. The CSV path's hand-rolled
  partial dict had drifted (missing `construction_cost`, `vacancy_rate`, `noi_growth_rate`,
  `income_confidence`, `income_size_band`) and never registered the city — both fixed by the
  shared builder.
  
## [3.2.0] — 2026-06-14

### Fixed

- **Vacancy rate frozen after first save** — `PropertyInput.__post_init__` was filling
  `vacancy_rate` from `VACANCY_RATE_DEFAULTS` on construction, so `to_record()` always
  persisted a resolved number. On reload that stored value was treated as an explicit
  override and `VACANCY_RATE_DEFAULTS` was never consulted again. Any future update to the
  constants would be silently ignored for all previously saved records, and it was
  impossible to distinguish a user-set value from a frozen default in the stored data.

- **`__post_init__` no longer mutates `vacancy_rate`** — the field stays `None` unless a
  caller explicitly supplies a value. Resolution is now performed by `_resolve_vacancy_rate()`
  in `analysis/analyzer.py` (mirrors the existing `_resolve_noi_growth()` pattern), which
  reads from `VACANCY_RATE_DEFAULTS` at analysis time and passes the result explicitly into
  `IncomeMetrics` and `MarketMetrics`.

- **`to_record()` now stores `None` for auto-resolved vacancy rates** — only an explicit
  caller-supplied value will be persisted. On every re-analysis the rate is re-derived from
  the current constants, so any update to `VACANCY_RATE_DEFAULTS` propagates immediately to
  all existing records.

### Added

- **`DataStore.migrate_vacancy_rate_to_null()`** — idempotent one-time migration that clears
  all frozen `vacancy_rate` values in `properties.json` to `null`. Called automatically at
  startup in `main.py`; returns the count of records updated (0 once the migration is
  complete and on every subsequent run).

### Tests

- Updated three `test_metrics_income.py` tests to assert `prop.vacancy_rate is None` after
  construction (no more `__post_init__` fill) and to test `_resolve_vacancy_rate()` directly
  rather than the now-removed side-effect.
- Added `test_to_record_stores_null_when_vacancy_not_set` — verifies `to_record()` serialises
  `None` when no explicit vacancy rate is provided.
- Renamed `test_to_record_persists_vacancy_rate` →
  `test_to_record_persists_explicit_vacancy_rate` to clarify it covers the override path only.
- Added `test_vacancy_rate_roundtrip_picks_up_updated_default` — patches
  `VACANCY_RATE_DEFAULTS`, round-trips a record through `to_record()` and reconstruction,
  and asserts the updated constant propagates into `IncomeMetrics.vacancy_rate`.
- Extended `test_prop_not_mutated_by_analyzer` to also assert `prop.vacancy_rate` is
  unchanged after analysis.
- Updated `test_type_switch_vacancy_reset.py` docstring and assertion message to reference
  `_resolve_vacancy_rate()` instead of `__post_init__`.

---

## [3.1.1] — 2026-06-14

### Tests

- **`analysis/industrial_config.py` raised to 100% coverage** (was 88%). Added tests for
  the defensive fallback and error paths that the feature tests didn't exercise: `_read`
  on a missing file, `load_size_bands`/`load_premiums` falling back to module defaults when
  the JSON is absent, `load_premiums` skipping malformed (non-dict / value-less) entries, the
  no-match branch in `resolve_size_band` (falls back to the last band), the multi-tenant
  override firing when no `small-bay` band exists to reclassify into, and the invalid-level
  guard in `_downgrade_level`.

---

## [3.1.0] — 2026-06-14

### Fixed

- **Industrial income calculation was circular and ignored building details**
  (`analysis/analyzer.py`, `analysis/metrics/property_types.py`,
  `analysis/rent_resolver.py`): `RentResolver` produced a flat `rate × total_sq_ft`, the
  analyzer back-calculated the rate, and `IndustrialMetrics` re-multiplied it — so clear
  height, dock/drive-in doors, office and yard had **zero effect** on income or score. A basic
  shed and a modern logistics facility of the same size and city produced identical income.
  `IndustrialMetrics` is now built from the size-adjusted market rate **before** the income
  metrics; when building details are present, its `total_income` becomes the rent input that
  flows into NOI, cap rate, and the score. When details are absent, the flat estimate stands
  but is flagged as a low-confidence approximation.

- **Dead door constants now contribute income** — `DOCK_DOOR_ANNUAL` ($1200) and
  `DRIVE_IN_DOOR_ANNUAL` ($600) were defined but never referenced, so doors had no effect even
  on the (previously decorative) `total_income`. Door income is now folded into `total_income`.

- **User-entered / explicit rent is never overridden** — the detail-driven override is gated on
  `market_resolved` (`annual_rent is None`, not `commercial_rent_user_entered`, market base rate
  present), so a user-supplied `commercial_rent` (or explicit `annual_rent`) on an industrial
  property is always honoured and carries no estimate-confidence grade.

### Added

- **Industrial size-band multiplier** (`analysis/industrial_config.py`,
  `json/industrial_size_bands.json`): a sourced multiplier applied to the city Industrial rate,
  keyed off `total_sq_ft` — small-bay (<25k, ×1.08), mid-size (25k–100k, ×0.95), big-box
  (>100k, ×1.00). The relationship is non-monotonic (Colliers: small-bay highest, big-box
  second, mid-size trough). A **multi-tenant override** reclassifies a large footprint toward
  small-bay (and lowers confidence) when door density or office ratio signals it is multi-tenant
  product. Band boundaries and multipliers live in JSON with source citations.

- **Component premiums externalised to sourced config**
  (`json/industrial_premiums.json`): clear-height (capped to avoid double-counting the big-box
  tier), office, yard, and door premiums moved out of hardcoded class constants into JSON, each
  badged `HEURISTIC` (no published $ basis found). Class constants remain as fallbacks.

- **Income confidence model** — `income_confidence = f(rate Src/Est tag, details)` graded
  HIGH / MED / LOW, surfaced in `to_record`, the property report (confidence badge), and the
  rent breakdown. `LOW` (undetailed industrial on an estimated rate) is **excluded from city
  averages** in `CityRanker` but kept in inventory; an `act_score_na` flag distinguishes an
  empty active-scored set from a genuine zero. `DataStore.load_commercial_sources` /
  `CommercialRentLoader.get_rate_source` expose the per-city `Src:`/`Est:` provenance tag.

### Tests

- New `tests/test_industrial_config.py` (size bands, multi-tenant override, confidence matrix)
  and `tests/test_integration_industrial.py` (end-to-end through the real DataStore / resolver /
  analyzer / scorer / ranker stack: detail-driven income, size multiplier, confidence grading,
  LOW excluded from city averages, user-entered rent preserved). Existing tests updated for door
  income and the size multiplier.

---

## [3.0.1] — 2026-06-12

### Fixed

- **Canadian mortgage compounding convention was wrong** (`analysis/mortgage.py`,
  `analysis/metrics/cash_flow.py`): the monthly rate was computed as `annual_rate / 12`
  (US monthly-compounding convention). Canadian fixed-rate mortgages compound
  **semi-annually** under the *Interest Act* (s. 6); the correct effective monthly rate is
  `(1 + annual_rate / 2)^(1/6) − 1`. Every payment was overstated by ~1–2%, with the error
  flowing through DSCR, annual/monthly cash flow, CoCR, loan balance at exit, IRR, the stress
  test, and scores. On a $1 M loan at 6% over 25 years the payment was overstated by ~$45/month
  (~$540/year).

- **Stress-test payment was a duplicate of the base formula** — `DebtMetrics` re-implemented the
  amortization formula inline, so the two paths could drift independently. The stress-test block
  is now a call to the shared `amortization_payment()` helper; it also carries the same fix.

- **Duplicate province set in `ui/menu.py`** (`ui/menu.py`): `parse_city_province` defined an
  inline `PROVINCES = {"AB","BC",…}` that was an exact copy of the set now centralised in
  `models/constants.py`. The inline set has been replaced with the imported `CANADIAN_PROVINCES`
  constant.

### Added

- **`CANADIAN_PROVINCES` in `models/constants.py`** — single source of truth for the 13
  Canadian province/territory codes; consumed by the mortgage compounding logic and the
  address parser, so both always agree.

- **Shared amortization helpers in `analysis/mortgage.py`**:
  - `effective_monthly_rate(annual_rate, compounding)` — `"semi-annual"` uses the Canadian
    formula; `"monthly"` uses `rate / 12`.
  - `amortization_payment(loan, annual_rate, n_payments, compounding)` — single payment formula
    called by both `MortgageCalculator` and `DebtMetrics`.
  - `remaining_balance(loan, annual_rate, n_payments, payments_made, compounding)` — loan
    balance at exit, consistent with the payment formula.
  - `compounding_for_province(province)` — maps a province/state code to `"semi-annual"` for
    Canadian provinces, `"monthly"` for everything else.

- **`MortgageCalculator` accepts a `province` parameter** — compounding convention is determined
  automatically from the property's province. Defaults to `"ON"` (semi-annual). The compounding
  convention is now surfaced as a `"Compounding"` row in the mortgage section of the analysis
  report.

- **`DebtMetrics` accepts a `compounding` parameter** — passed through from
  `CommercialPropertyAnalyzer` so the stress test always uses the same convention as the base
  payment.

- **`_parse_city_province` extracted to module level** in `ui/menu.py` — was a nested function
  inside `_prompt_property`, making it unreachable by tests. Now a module-level
  `_parse_city_province(addr)` function.

### Tests

- **`tests/test_analysis_mortgage.py`** — rewritten with correct Canadian amortization
  expectations; new test classes for `compounding_for_province`, `effective_monthly_rate`,
  `amortization_payment`, and `remaining_balance`; `TestMortgageCalculator` extended with
  Canadian vs. US payment comparison tests and compounding label assertions; parametrized over
  `CANADIAN_PROVINCES` so tests stay in sync automatically if the constant ever changes.

- **`tests/test_menu_parse_city_province.py`** — new file, 38 tests for `_parse_city_province`:
  both address formats (`"City, ON"` and `"City ON"`), all 13 provinces/territories, case
  normalisation, multi-word city names, and all failure paths (no comma, unknown province, empty
  string, `None`).

---

## [2.7.1] — 2026-06-12

### Fixed

- **`DebtMetrics.be_ratio` still graded GOOD for negative-NOI properties**
  (`analysis/metrics/cash_flow.py`): the zero-NOI sentinel added in 2.7.0 only caught
  `est_noi == 0`; a *negative* NOI produced a negative ratio, which the grader read as
  "well below the 75% threshold" and awarded **GOOD**. The sentinel condition is now
  `est_noi > 0`, so any non-positive NOI hits the `float('inf')` worst-case path, grades
  **POOR** on both Break-Even NOI rows, and displays `"N/A"`.
- **`DataStore._write` had no rollback copy** (`data/store.py`): the atomic
  temp-file-plus-`os.replace()` write added in 2.7.0 protects against crashes mid-write, but
  not against successfully writing bad data. Before promoting the new content, the previous
  file is now copied to a `.bak` sibling (copy, not rename, so the live file always exists).
  `*.json.bak` / `*.json.tmp` added to `.gitignore`.

### Tests

- **`tests/test_metrics_cash_flow.py`** — 3 new tests: negative-NOI `be_ratio` is `inf`,
  grades POOR on both Break-Even NOI rows, and displays `"N/A"`.
- **`tests/test_data_store.py`** — 3 new tests: first write creates no `.bak`, a rewrite
  preserves the previous content in `.bak`, and a failed write leaves both the live file and
  the `.bak` untouched.

---

## [2.7.0] — 2026-06-12

### Fixed

- **`DebtMetrics.be_ratio` sentinel was wrong-direction for zero-NOI properties**
  (`analysis/metrics/cash_flow.py`): when `est_noi` is zero the break-even NOI ratio was set to
  `1`, which the grader interpreted as "debt service is 1% of NOI" and awarded a **GOOD** grade.
  The sentinel is now `float('inf')`, which correctly grades **POOR** on both Break-Even NOI rows.
  The `Break-Even NOI %` display renders `"N/A"` rather than `"inf%"` when NOI is zero.
- **`DataStore._write` was not crash-safe** (`data/store.py`): the method opened the target file
  with `"w"` (truncate) before writing, leaving `properties.json` empty or partially written if
  the process was interrupted mid-write. Writes now go to a `.tmp` sibling file first and are
  promoted to the live path via `os.replace()`, which is atomic on both POSIX and Windows (same
  drive). The original file is never touched until the new content is fully flushed.

### Tests

- **`tests/test_metrics_cash_flow.py`** — 4 new tests: zero-NOI `be_ratio` is `inf`, grades POOR
  on both Break-Even NOI rows, and displays `"N/A"` on the percentage row.
- **`tests/test_data_store.py`** — 2 new tests: no `.tmp` file is left behind after a successful
  write, and an overwrite produces the correct final content.

---

## [2.6.0] — 2026-06-12

### Fixed

- **Optional-field edit crash on non-numeric input** (`ui/menu.py`): typing a non-numeric value
  (e.g. `"abc"`) into any optional `float` field during property editing — fields 7 (Commercial
  rent), 16 (Residential rent), 18 (Construction cost), 30–32 (Industrial sqft components), and
  35–37 (Industrial rates/height) — raised an unhandled `ValueError` that terminated the process.
  The `"optional"` branch in `PropertyMenu._edit` is now wrapped in `try/except ValueError`,
  matching the guard already present in every sibling branch (`pct`, `unit`, `nodec`, `hotel`,
  `standard`). Bad input now prints `"Invalid number."` and re-prompts instead of crashing.
- **Vacancy rate ratchet when switching property type** — changing a property's type via the edit
  menu (field 6) reset `expense_ratio` to `None` but left `vacancy_rate` untouched. The old type's
  rate (e.g. Office's 14%) would persist silently through any subsequent type change, causing
  effective gross income to be understated for the new type. `vacancy_rate` is now also reset to
  `None` on type change so `__post_init__` re-derives the correct market default for the new type.

### Tests

- **`tests/test_type_switch_vacancy_reset.py`** — 103 new tests covering the regression directly
  (store write, in-memory dict) and every cross-type switch where the vacancy default differs,
  asserting both `vacancy_rate` and `expense_ratio` are cleared on each transition.

---

## [2.5.0] — 2026-06-12

### Fixed

- **Stress test was ~10× too lenient** — `DebtMetrics` previously computed the stressed debt
  service as `annual_mortgage × 1.02`, treating the 2% shock as a 2% increase in the *payment
  amount* rather than a 200 bp increase in the *interest rate*. On a 25-year loan at 5%, a genuine
  +200 bp shock raises the payment by ~21%, not 2%. Properties that would have failed a real rate
  shock were incorrectly shown as PASS.
- **`TestStressTestScalesWithLoan` did not catch the bug** — the test only asserted that the shock
  was proportional across loan sizes (which the flat ×1.02 trivially satisfied) and never verified
  that the shock magnitude was realistic.

### Changed

- **`DebtMetrics` now recalculates the stressed payment from first principles** — accepts
  `loan_amount`, `interest_rate`, and `term_years`; applies the standard amortization formula at
  `interest_rate + stress_rate_bump` to derive the true shocked annual debt service.
- **Stress rate bump is configurable** — `DebtMetrics.__init__` accepts a `stress_rate_bump`
  parameter (default `0.02`). The row label (`Stress Test (+2%)`) reflects whatever value is
  passed. `analyzer.py` passes the actual loan parameters so the calculation is always exact.
- **`TestStressTestScalesWithLoan` strengthened** — tests now supply proportional loan amounts and
  include a new `test_stress_shock_magnitude_is_realistic` assertion that the payment increase for
  a +200 bp shock falls between 15% and 30% (the correct range near 5% / 25-year), which the old
  ×1.02 formula would have failed.
  
## [2.4.0] — 2026-06-12

### Fixed

- **CSV import silently erased `property_type` for Hotel rows** — the local `COMMERCIAL_TYPES`
  set in `csv_handler.py` omitted `"hotel"`, so any row with `property_type=Hotel` was treated as
  non-commercial and `prop_type_field` was set to `None`. The rent resolver's hotel branch
  (which requires `ptype == "hotel"`) never fired even with `hotel_rooms`, `hotel_adr`, and
  `hotel_occupancy` present; the resolver raised a `ValueError`; and the fallback record saved
  `property_type: None`. Added `"hotel"` to the local set and added three regression tests in
  `tests/test_csv_hotel_import.py`.
  
## [2.3.0] — 2026-06-12

### Fixed

- **NOI growth rate frozen after first save** — `to_record()` persisted the resolved NOI growth
  rate (from city demographics or the 2% default) into `properties.json` under `noi_growth_rate`.
  On reload, that stored value was passed back into `PropertyInput.noi_growth_rate`, causing
  `_resolve_noi_growth()` to treat it as a manual override and skip the demographics lookup
  entirely. Any subsequent update to `city_demographics.json` was silently ignored for all
  previously saved properties.
- **`to_record()` now saves `None` for auto-resolved NOI growth rates** — only an explicit
  user-set value (when a UI for that field exists) will be persisted. On every re-analysis the
  rate is re-derived from the current demographics file, so city-level data updates propagate
  automatically.
- **463 existing records in `properties.json` had their baked-in auto-resolved rates cleared to
  `null`** — all stored values were resolver-derived (no manual-entry UI exists for this field),
  so all were reset to allow fresh resolution against the current demographics data.

---

## [2.2.0] — 2026-06-12

### Fixed

- **Single `rent_manually_entered` flag could not distinguish which component a user entered** —
  the previous boolean flag was property-level, not component-level. A mixed-use property with a
  manually-entered commercial rent and a resolver-derived residential rent could not express that
  state: setting the flag `True` froze both components, setting it `False` re-derived both. Any
  re-analysis after a rate update either left the user's figure intact and silently kept the stale
  residential rent, or wiped the user's figure by re-deriving everything.
- **`_reanalyze_city` was defeated for any property carrying `rent_manually_entered=True`** —
  the method exists specifically to propagate market-rate updates to stored records, but the
  short-circuit in `RentResolver.resolve()` returned the stored values immediately, making the
  method a no-op for any manually-entered property regardless of which component had changed.
  With the two-key design, `_reanalyze_city` now correctly re-derives only the resolver-derived
  component while leaving the frozen one untouched.
- **`rent_manually_entered` was never written to the JSON for any of the 476 existing records** —
  the field was added to `to_record()` after all records had been saved; no re-analysis had been
  run since. All records therefore loaded with the flag defaulting to `False`, meaning any
  previously manually-entered commercial rent would have been silently overwritten on the next
  `_reanalyze_city` run. Replaced by the two-key design and a one-time backfill (see below).

### Added

- **`commercial_rent_user_entered` and `residential_rent_user_entered` on `PropertyInput`** —
  two `bool` fields (both default `False`) replace the single `rent_manually_entered` flag.
  Each controls exactly one rent component. `rent_manually_entered` is retained as a computed
  property (`commercial_rent_user_entered or residential_rent_user_entered`) for backward
  compatibility with any code that reads it.
- **Component-level freeze in `RentResolver.resolve()`** — four tiers now:
  (1) both flags `True` → full short-circuit, no market lookups at all;
  (2) only `commercial_rent_user_entered=True` → stored commercial used directly, residential
  re-derived from current market rates (market lookup skipped for the commercial component);
  (3) only `residential_rent_user_entered=True` → stored residential used directly, commercial
  re-derived (market lookup skipped for the residential component);
  (4) both `False` → full re-derive from market rates (existing behaviour for all legacy records).
  All four tiers are integrated into each resolution path (mixed-use, residential-only,
  retail-office, pure commercial, hotel) so that market lookups are genuinely skipped rather than
  called and then overridden.
- **Backward compat: old single-flag records load correctly** — `_record_to_prop` reads
  `commercial_rent_user_entered` and `residential_rent_user_entered` first; if absent it falls
  back to the legacy `rent_manually_entered` key, applying its value to both component flags.
  Records with neither key present default both to `False`.
- **One-time backfill script (deleted after run)** — compared stored `commercial_rent` and
  `residential_rent` against what the resolver would derive today from current market rates.
  Records where stored ≠ derived (and stored ≠ 0) were flagged as manually entered for that
  component. Result: 19 of 476 records flagged (12 commercial, 7 residential), 457 confirmed
  resolver-derived. The 8 records with no market data for their city were also flagged if they
  carried a stored rent value. Both new keys written to every record; legacy
  `rent_manually_entered` key removed.
- **28-test suite `tests/test_rent_manually_entered_flag.py` rewritten for two-key design** —
  covers: both flags default `False`; `rent_manually_entered` computed property (`False`, `True`
  from comm only, `True` from res only, `True` from both); full short-circuit with no market
  lookups; stale stored rents ignored when both flags `False`; partial freeze — comm frozen /
  res derived; partial freeze — res frozen / comm derived; market lookups confirmed skipped for
  each frozen component; `needs_residential_recalc` overrides res freeze when no stored value
  exists; `to_record()` writes both flags correctly for all three flag states; `_record_to_prop`
  reads two-key flags; missing flags default to `False`; legacy single flag `True` fans out to
  both keys; legacy `False` fans out to both `False`; new keys take precedence over old flag when
  both present; `_reanalyze_city`-shaped resolver calls confirm derived-component updates and
  frozen-component preservation at the resolver level.
- **10-test suite `tests/test_reanalyze_city.py`** — tests `_reanalyze_city` end-to-end through
  the full call chain (store load → `_record_to_prop` → resolver → `to_record` →
  `store.update_property`), covering: resolver-derived commercial rent updates when rate changes;
  records from other cities and provinces skipped; manually-entered commercial rent not
  overwritten; commercial market lookup not called when frozen; manually-entered residential rent
  not overwritten; residential market lookup not called when frozen; mixed-use partial freeze
  (comm frozen → res updates; res frozen → comm updates); both flags written back correctly to
  the saved record after re-analysis.

### Changed

- **`_prompt_property` sets two-key flags on new property entry** — `commercial_rent_user_entered`
  is set to `True` when the user fills in the Commercial rent field; `residential_rent_user_entered`
  is set to `True` when the user fills in the Residential rent field. Properties where those fields
  are left blank receive `False` for the corresponding flag.
- **`to_record()` writes `commercial_rent_user_entered` and `residential_rent_user_entered`**
  instead of the legacy `rent_manually_entered` key.
- **Existing tests updated** — `test_explicit_rent_inputs.py`, `test_reanalysis_stale_residential.py`,
  `test_retail_office_floor_loss.py`, and `test_floor_preservation_all_types.py` updated to pass
  the two-key flags. The `_prop` helper in `test_explicit_rent_inputs.py` auto-sets both flags
  from the presence of `commercial_rent` / `residential_rent`, matching the menu behaviour.

### Fixed (edge cases — same session)

- **`_edit` never set the provenance flags when a rent was changed or cleared** — fields 7
  (Commercial rent / year) and 16 (Residential rent / year) went through the `"optional"` branch
  at `menu.py` which wrote the value but left `commercial_rent_user_entered` /
  `residential_rent_user_entered` unchanged. The post-edit re-analysis immediately re-derived from
  market rates and overwrote whatever the user had just typed. The optional branch now writes the
  flag atomically with the value in the same `update_property` call: entering a value sets the
  flag `True`, clearing (Enter with no input) sets it `False`.
- **Clearing a rent in `_edit` re-froze the resolver-derived replacement** — clearing left a
  stale `user_entered=True` flag; the resolver re-derived (value is `None`), but `to_record()`
  persisted the flag verbatim next to the freshly resolved value, stamping it as user-entered and
  freezing the market-derived figure on every subsequent re-analysis. Fixed by the same change:
  clearing now explicitly writes `False`.
- **CSV import never set the provenance flags** — `csv_handler.py` collapsed explicit CSV rents
  into `annual_rent` on `PropertyInput` and never populated `commercial_rent_user_entered` /
  `residential_rent_user_entered`, so any rent provided in a CSV row was silently overwritten by
  the next `_reanalyze_city` pass. The import path now passes `commercial_rent` and
  `residential_rent` as component fields with the correct flags set, matching the behaviour of the
  interactive add form. The partial-save fallback (no resolver data available) also writes both
  flags.
- **9-test suite `tests/test_edit_rent_flags.py`** — covers all three write paths: `_edit` sets
  `commercial_rent_user_entered=True` when a commercial rent is typed; `_edit` sets
  `residential_rent_user_entered=True` when a residential rent is typed; clearing commercial rent
  sets the flag `False`; clearing residential rent sets the flag `False`; cleared flag allows
  re-analysis to re-derive from market rates; CSV import with explicit commercial rent sets flag
  `True`; CSV import with no explicit rent leaves both flags `False`; CSV import with explicit
  residential rent sets flag `True`; CSV-imported user rent survives subsequent `_reanalyze_city`
  unchanged.

---

## [2.1.0] — 2026-06-12

### Fixed

- **Market-resolved rents frozen permanently after first analysis** — `RentResolver.resolve()`
  opened with a short-circuit that fired whenever `commercial_rent` or `residential_rent` was
  non-`None` on the `PropertyInput`, regardless of how that value got there. Because
  `to_record()` always writes both rent fields to the JSON record and `_record_to_prop` always
  reads them back, any rent resolved from market rates on a first analysis was treated as an
  explicit user entry on every subsequent re-analysis. Updating city rate tables, changing
  market assumptions, or running a batch re-analysis had no effect on already-stored commercial
  properties — the old figure was returned verbatim with no warning. The resolver now only
  short-circuits when `PropertyInput.rent_manually_entered` is `True`, meaning the value came
  directly from a user input field rather than a prior market resolution.

### Added

- **`rent_manually_entered` flag on `PropertyInput`** — new `bool` field (default `False`) that
  distinguishes a user-typed rent figure from a market-resolved one stored in a prior analysis.
  The flag is never shown to or entered by the user; it is set automatically by the code that
  collects rent input.
- **Flag set on new and edited properties** — `_prompt_property` in `ui/menu.py` sets
  `rent_manually_entered=True` when the user fills in the Commercial rent or Residential rent
  field during the Add Property form. Properties where those fields are left blank (delegating
  to market-rate resolution) receive `False`.
- **Flag persisted and round-tripped through JSON** — `analyzer.to_record()` writes
  `rent_manually_entered` to the property record. `_record_to_prop` reads it back on load
  (`p.get("rent_manually_entered", False)`). Legacy records that pre-date this field receive
  `False` on load, causing their rents to be re-resolved from current market rates on next
  analysis rather than remaining frozen at a stale stored value.
- **15-test regression suite** — `tests/test_rent_manually_entered_flag.py` covers: flag
  default (`False`) and explicit `True`; manual-entry short-circuit for commercial-only,
  residential-only, and both-rents combined (verifying no market lookup occurs); stale stored
  commercial rent with `flag=False` re-resolves from market rates; stale stored residential
  rent with `flag=False` re-resolves from unit mix; stale mixed-use rents both re-resolve;
  breakdown message accuracy (manual says "directly", market does not); `to_record()` persists
  `True` and `False` correctly; `_record_to_prop` restores `True`, restores `False`, and
  defaults missing key to `False` for legacy records.

### Changed

- **Existing tests updated to reflect manual-entry semantics** — tests across
  `test_explicit_rent_inputs.py`, `test_reanalysis_stale_residential.py`,
  `test_retail_office_floor_loss.py`, and `test_floor_preservation_all_types.py` that relied
  on the old unconditional short-circuit now pass `rent_manually_entered=True` (or have their
  stored record fixtures updated) where the test intent is "user explicitly provided this
  rent." The `_prop` helper in `test_explicit_rent_inputs.py` auto-sets the flag when
  `commercial_rent` or `residential_rent` is supplied, matching the menu behaviour.

---

## [2.1.0-b] — 2026-06-12

### Fixed

- **Zero-filled rate stubs silently produced $0 rent for all property types** —
  `ensure_city_in_rates` in `data/store.py` wrote `{"Office": 0, "Retail": 0, …}` (commercial)
  and `{"bachelor": 0, "one_br": 0, …}` (residential) as sentinels for "rate not yet fetched."
  Every guard in `RentResolver` that should have caught a missing rate checked
  `if rate is None`, so `0` passed through as a valid rate. The result was `$0/sq ft × sqft =
  $0` annual rent: no `ValueError`, no `log_missing` call, and no user-visible warning. The
  analyzer received `annual_rent = 0`, treated it as "no rent available" (`_has_rent = False`),
  and produced a partial analysis record silently. Properties stored in any city whose data had
  never been filled — across Office, Retail, Industrial, Mixed-Use, Retail-Office, Residential,
  and Multi-Family types — were permanently affected. Hotel was immune (its revenue path never
  calls the rate loaders).
- **`_reanalyze_all` silently updated stub-city properties instead of skipping them** — because
  the zero rate never raised `ValueError`, the bulk re-analysis path incremented `updated`
  rather than `skipped` and wrote partial records with `$0` income back to disk on every run,
  making the corruption self-perpetuating.
- **`load_residential_rates` raised `TypeError` on `None`-valued stubs** — the comprehension
  `{k: float(v) for k, v in …}` called `float(None)` after the sentinel migration. Updated to
  `float(v) if v is not None else None`.
- **`_resolve_residential` used `None` per-unit values as `$0/month`** — the per-key lookup
  `elif unit_key in market` fired even when `market[unit_key]` was `None` or `0`, multiplying
  `None × count × 12` (crash) or `0 × count × 12` (silent zero). The guard is now
  `market[unit_key] is not None and market[unit_key] > 0`.
- **City average rate included `None` and `0` stubs** — `known_rates` was built with
  `isinstance(v, (int, float))`, which excluded `None` but passed `0`. A stub city with one
  real rate (e.g., `one_br = 1_200`) and five zeros averaged to `200/month` rather than
  `1_200/month`. Filter updated to `isinstance(v, (int, float)) and v > 0`.

### Added

- **`ensure_city_in_rates` migrates legacy on-disk zero stubs to `None`** — on every call the
  method now iterates all cities in both `commercial_rents.json` and `residential_rents.json`
  and replaces any `0`-valued type/unit entry with `null`. The migration is idempotent (a second
  pass touching only `None` values does nothing) and writes back only when a change was made, so
  the extra I/O on unchanged files is a single read with no write. Existing real rates (non-zero)
  are never touched.
- **`ResidentialRentLoader.get_rates` returns `None` for all-`None` stub cities** — after
  migration a stub city's residential dict contains only `null` values; the loader now returns
  `None` in that case so the existing `if market is None:` guard in `_resolve_residential` fires
  correctly, triggering `log_missing` and the "no rate" breakdown lines.
- **36-test regression suite** — `tests/test_zero_rate_stub_bug.py` covers five layers:
  (1) *Sentinel / migration* — new stubs write `None`; existing zeros are migrated; real rates
  are untouched; migration is idempotent; stub city keys appear in both indexes with `None`
  values; (2) *Loaders* — `CommercialRentLoader` returns `None` for each stub type; residential
  loader returns `None` for an all-`None` city and returns the dict for a partially-populated
  city; `load_residential_rates` does not raise on `None` values; (3) *Resolver — all property
  types* — Office, Retail, Industrial, and Retail-Office all raise `ValueError`; Mixed-Use skips
  the commercial component and logs missing; both-stubs-`None` Mixed-Use returns zero rent;
  residential-only stub logs missing; `log_missing` is called (not bypassed); a pre-fix `0`
  mock is included as a documented regression anchor showing `_has_rent = False`; (4)
  *`_resolve_residential` partial stubs* — `None` per-unit value falls through to city avg;
  `None` values excluded from avg; all-`None` market falls through to missing path; override
  wins over `None` in market; explicit `0` values excluded from avg computation; (5)
  *`_reanalyze_all` end-to-end* — stub-city property is counted as `skipped`, not `updated`;
  `0/1 updated` is confirmed in output; populated-city property is counted as `updated`; stub
  city does not produce income metrics (NOI, Cap Rate, Gross Rent Multiplier); a mixed batch of
  one stub + one real city produces `1/2 updated, 1 skipped`; parametrised over Office, Retail,
  Industrial, and Retail-Office stub types.

---

## [2.0.1] — 2026-06-11

### Fixed

- **Floor count destroyed on re-analysis for unit-less properties** — `_record_to_prop` in
  `ui/menu.py` only built a `UnitMix` when residential units existed, so any unit-less record
  loaded for re-analysis had `unit_mix = None` on the `PropertyInput`. `RentResolver` then fell
  back to `getattr(prop, "floors", 1)` — dead code, since `PropertyInput` has no `floors`
  field — and `to_record()` wrote `floors = 1` back, permanently destroying the stored value.
  Confirmed via data audit: 9 unit-less Retail-Office and 12 unit-less Mixed-Use records all
  showed `floors = 1` with a matching 2026-06-09 batch timestamp. `_record_to_prop` now builds
  a floors-only `UnitMix` (`total_units = 0`) for every unit-less property regardless of type,
  carrying the floor count through the pipeline. This object is behaviourally inert in the
  resolver and analyzer — it exists purely to preserve the value.
- **Retail-Office rent computed as single-floor when no saved rent exists** — with floors
  collapsed to 1 and no stored `commercial_rent`/`annual_rent` (e.g. a CSV row imported without
  rent, or a rent field cleared in the editor), the resolver priced the entire building at the
  ground-floor Retail rate across all square footage instead of splitting it into ground-floor
  Retail plus upper-floor Office. Records with a saved `commercial_rent` were shielded by the
  resolver's short-circuit (rent frozen, not inflated). Fixed by the floor preservation above.
- **`to_record()` no longer stomps floors to 1 when no unit mix is present** — both the
  top-level `floors` key and `unit_mix.floors` now fall back to the existing record's stored
  value (`(existing or {}).get("floors", 1)`) instead of a hardcoded `1`, so any future code
  path that builds a `PropertyInput` without a `UnitMix` preserves rather than destroys the
  stored floor count. The dead `hasattr(p, "floors")` fallback was removed.
- **CSV import dropped floors for unit-less rows** — `csv_handler.py` only built a `UnitMix`
  when residential unit counts were present, so any unit-less row lost its `floors` column on
  first import. A floors-only `UnitMix` is now built for all unit-less rows regardless of
  property type, including when rent is provided.
- **Dead `getattr(prop, "floors", 1)` fallback removed from `RentResolver`** — the attribute
  never existed on `PropertyInput`, so the expression silently always yielded 1 and masked the
  floor-loss bug. The resolver now reads floors from `unit_mix` or defaults to 1 explicitly.
- **First-time entry also lost floors for unit-less non-Retail-Office properties** — on a brand
  new record there is no existing saved record for the `to_record()` fallback to draw from, so
  a new 3-floor Office or unit-less Mixed-Use entered via the add form or CSV silently saved
  `floors = 1` from day one. The interactive add form now also builds a floors-only `UnitMix`
  for all unit-less properties, closing the gap across all three write paths: add form,
  re-analysis, and CSV import.
- **Stored `annual_rent = 0` froze rent at $0 permanently** — `_record_to_prop` coerces falsy
  `commercial_rent` and `residential_rent` to `None` ("not recorded — recompute from market
  rates") but passed a literal `annual_rent: 0` through unchanged. The resolver's short-circuit
  checks `prop.annual_rent is not None`, so `0` was returned as "rent provided directly", every
  income metric (NOI, cap rate, DSCR, IRR) was skipped, and `to_record()` wrote the `0` straight
  back — a self-perpetuating $0 record no re-analysis could heal, even after city rate data
  became available. `annual_rent` now receives the same `or None` coercion as the other two
  rent fields. A data scan confirmed no stored records currently carry a literal zero, so no
  migration was needed.

### Added

- **12-test regression suite for Retail-Office floor loss** — `tests/test_retail_office_floor_loss.py`
  covers four layers: (1) `_record_to_prop` — floors survive record → `PropertyInput` conversion,
  including fallback to the top-level `floors` key for older records, and all unit-less types
  now produce a floors-only `UnitMix`; (2) `RentResolver` — a 3-floor building prices as
  ground-floor Retail plus two upper Office floors, and a missing `UnitMix` defaults to one
  floor; (3) end-to-end — re-analysis preserves floors in both record keys, is idempotent, keeps
  the saved-rent short-circuit intact, recomputes cleared rent across all floors, and
  `to_record()` falls back to the existing record's floors when `unit_mix` is absent; (4) CSV
  import — a unit-less Retail-Office row persists its floors with and without a provided rent.
- **10-test regression suite for zero annual rent** — `tests/test_reanalysis_zero_annual_rent.py`
  covers three layers: (1) `_record_to_prop` — `annual_rent = 0` becomes `None`, `null` stays
  `None`, a positive value survives, and component rents still suppress `annual_rent`;
  (2) `RentResolver` — `None` falls through to the market-rate lookup while a provided non-zero
  rent short-circuits with no lookup; (3) end-to-end — a frozen $0 record recomputes from market
  rates, its income metrics (NOI, Cap Rate) reappear, recovery is idempotent, and a genuine
  provided rent is preserved verbatim.
- **83-test floor-preservation suite covering every property type** —
  `tests/test_floor_preservation_all_types.py` parametrises the full re-analysis round-trip
  (record → `_record_to_prop` → analyzer → `to_record()`) over all eight property types plus
  untyped records across four scenarios: unit-less and with-units re-analysis (single and
  double pass, matching the 2026-06-09 batch-run shape), legacy records missing the `unit_mix`
  dict, genuine `floors = 1` not being inflated, first-save of a brand-new property
  (`to_record(existing=None)`), `_record_to_prop` independently confirmed to carry floors for
  all unit-less types, and CSV import of unit-less rows for all eight named types. The exact
  `_record_to_prop(p)` → `to_record(existing=p)` call chain used by `_reanalyze_all` and
  `_reanalyze_city` was verified clean across all 18 type × unit-count combinations.
- **`find_affected_floor_loss.py`** — read-only diagnostic that scans `properties.json` and
  classifies every unit-less Retail-Office record by exposure: floors still intact (at risk),
  floors already at 1 (possibly destroyed), rent-corruption exposed (no saved rent), or rent
  already computed single-floor.

### Data repair

- **Nine Retail-Office records had their floor counts restored manually** — all nine unit-less
  Retail-Office records in `properties.json` were found at `floors = 1` (all last modified
  2026-06-09, consistent with a single batch re-analysis pass having stomped them). The original
  values were not recoverable from the data file, so the floor counts were re-checked against
  their MLS listings and re-entered by hand (six 2-floor, two 3-floor, one 4-floor). Their
  stored rents were unaffected throughout (all carry an explicit `commercial_rent` that predates
  any single-floor recomputation), and the floor-preservation fixes above now keep the
  re-entered values stable across future re-analyses.

---

## [1.6.1] — 2026-06-11

### Changed

- **Address helpers moved from root `utils.py` to `core/address.py`** — `_display_address` and
  `_parse_address_sort` were the only functions in a catch-all `utils.py` at the project root.
  Both are address-specific and are now co-located in `core/address.py`. Imports updated in
  `ui/menu.py`, `reporting/printer.py`, and `tests/test_utils.py`. `utils.py` deleted.

---

## [1.6.0] — 2026-06-10

### Fixed

- **City report Score mini-stat color now matches the opportunity score** — the Score value shown
  in each city row's mini-stats was colored via `gc('score', act_score)`, which applied green when
  the individual deal score averaged ≥ 70. The city-level opportunity number uses `oppColor`, which
  applies amber for scores between 35 and 65. A city could therefore display a green "Score 72"
  alongside an amber "50 / 100", creating a visually contradictory signal. The mini-stat span now
  uses `style="color:${barColor}"` (the same `oppColor` derivation as the opportunity number), so
  the two always share the same color.

### Tests

- **`TestIncomeMetrics` — 3 new tests for construction cost in cap rate** (`test_metrics_income.py`):
  verifies that `cap_rate` and `entry_cap` use `asking_price + construction_cost` as the cost basis,
  and that a non-zero construction cost produces a lower cap rate than the same property without one.
- **`TestConstructionCostPropagation` — 7-test class added to `test_analysis_analyzer.py`**: covers
  the full propagation of `construction_cost` through the analyzer — cost basis in pricing, cash
  invested in cash flow, cap rate reduction, IRR reduction, "Construction Cost" / "Total Cash In"
  mortgage rows appearing when cost > 0 and absent when 0, and persistence via `to_record()`.
- **`TestCityReportGenerator` — 2 new tests for Score mini-stat color** (`test_reporting_generators.py`):
  asserts the rendered HTML contains `style="color:${barColor}"` for the Score span, and that the
  old class-based `Score <span class="${gc(` pattern is absent.

---

## [1.5.0] — 2026-06-10

### Fixed

- **City opportunity score weights rebalanced to sum to 1.00** — addition of `absorption_rate`
  and `price_trend` as scoring factors had pushed the total weight to 1.05, allowing raw
  opportunity scores to exceed 100. Weights across all 15 city score factors have been
  redistributed in `json/score_weights.json` so they sum exactly to 1.00.
- **`act_irr`, `act_dscr`, and `act_cf` now contribute to city opportunity score** — these three
  metrics were averaged per city and included in the report output but were absent from the `raw`
  formula in `CityRanker.rank()`. They are now scored factors with weights and thresholds
  configurable via `json/score_weights.json`.
- **`best_score` now contributes to city opportunity score** — the highest individual property
  score within a city is now a scored factor, reflecting the peak deal quality available in that
  market.
- **`inact_cap` threshold ceiling raised from 9% to 10%** — brought into line with the `act_cap`
  ceiling; having different ceilings for the same metric on active vs. inactive listings was
  skewing `cap_trend` interpretation.
- **`act_cap` threshold ceiling raised from 9% to 10%** — cap rates above 9% are achievable in
  secondary markets; the previous ceiling was penalising high-yield cities unnecessarily.
- **`act_coc` threshold ceiling raised from 12% to 15%** — widens the scoring range for
  cash-on-cash return, giving stronger deals room to differentiate.
- **`act_dom` threshold floor raised from 0 to 30 days** — listings under 30 days on market
  receive no DOM score contribution; very fresh listings do not indicate seller motivation.
- **`_avg` helper no longer silently drops zero values** — the previous implementation excluded
  any entry where the metric value was `0`, treating it the same as `None`. Zero is a valid
  value for DOM (listed today) and price drop (no reduction); the helper now only excludes
  `None`. Zero-sentinel handling is now done via `or None` at the point of data collection.

---

## [1.4.0] — 2026-06-09

### Fixed

- **Residential rent silently zeroed on re-analysis for properties created before city data existed** —
  `RentResolver.resolve()` opened with an early-exit that fired whenever either `commercial_rent`
  or `residential_rent` was not `None` on the `PropertyInput`. Mixed-Use properties stored before
  residential rent data was available for their city had `residential_rent = 0.0` written to disk;
  on every subsequent re-analysis `_record_to_prop` converted that `0.0` to `None` (via `or None`),
  which still satisfied the `commercial_rent is not None` branch, causing the early-exit to return
  the commercial-only total and write `residential_rent = 0.0` back — permanently. The resolver
  now checks whether the property has residential units (`unit_mix.total_units > 0`) with no
  recorded residential income (`residential_rent` is `None` or `0.0`); when that condition holds
  the early-exit is bypassed and the full mixed-use calculation runs, correctly picking up the
  now-available city residential rates.
- **Six Midland Mixed-Use properties updated on disk** — as a one-time migration the stale records
  were re-analysed and saved with the correct residential rent components: 262 King St (+$37,200/yr),
  276 King St (+$24,600/yr), 290 King St (+$172,200/yr), 261 King St (+$37,200/yr),
  289 King St (+$49,200/yr), 253 King St (+$49,200/yr). 270 King St (Retail-Office, no residential
  units) was unaffected.

### Added

- **17-test regression suite for stale residential rent** — `tests/test_reanalysis_stale_residential.py`
  covers three layers: (1) `_record_to_prop` — verifies `residential_rent = 0.0` becomes `None`,
  `commercial_rent` is preserved, `unit_mix` is rebuilt, and `annual_rent` is suppressed when
  explicit rent fields are present; (2) `RentResolver` — verifies `None` and `0.0` both trigger
  recalculation while a positive `residential_rent` still short-circuits; (3) end-to-end pipeline —
  verifies `to_record()` writes the correct `residential_rent`, that re-analysis is idempotent
  (running twice produces identical output), that NOI improves after recalculation, and that a
  no-unit property is unchanged.

---

## [1.3.0] — 2026-06-08

### Fixed

- **Explicit commercial and residential rent now honoured on property add** — `commercial_rent`
  and `residential_rent` are now separate named fields on `PropertyInput` (previously the menu
  collapsed them into a single `annual_rent`, causing the resolver to treat residential rent as
  commercial rent and always write `residential_rent = 0` to the record). `RentResolver.resolve()`
  now checks these fields first (Mode 0) and returns immediately without touching city-data
  lookups; the existing annual_rent / city-data fallback chain is unchanged.
- **Unit mix (bachelor/1BR/2BR/…) now preserved when explicit rent is provided** — `_prompt_property`
  in `ui/menu.py` previously only built a `UnitMix` object when no explicit rent was given;
  entering unit counts alongside a rent figure silently discarded the counts. A `UnitMix` is now
  always constructed when `total_units > 0`, regardless of whether `commercial_rent` or
  `residential_rent` was also provided.
- **`_record_to_prop` passes explicit rent fields on re-analysis** — saved records that contain
  non-zero `commercial_rent` or `residential_rent` are now loaded back into `PropertyInput` via
  those fields instead of being collapsed into `annual_rent`, preserving the correct split on
  every re-analysis.
- **Expense ratio prompt removed from Add Property form** — `ask_pct("Expense ratio %", 40)` has
  been removed from `_prompt_property` in `ui/menu.py`; `expense_ratio=None` is now passed to
  `PropertyInput`, which resolves the correct type-specific default via `__post_init__` using
  `EXPENSE_RATIO_DEFAULTS` in `models/constants.py` (e.g. hotel → 0.63, NNN → 0.08). The
  previous prompt always defaulted to 40% regardless of property type.
- **`_record_to_prop` expense ratio fallback corrected** — the hardcoded `0.40` fallback when
  loading a saved record without a stored ratio has been replaced with `None`, so old records
  now receive the correct type-specific default on next load rather than a flat 40%.
- **Expense ratio reset when lease type or property type is edited** — editing either field in
  the edit form now writes `expense_ratio = None` to the store so it recomputes from the
  updated type on the next load, preventing a stale ratio from persisting after a type change.
- **CSV ingestion no longer defaults expense ratio to 40%** — `csv_handler.py` now passes `None`
  when the expense ratio column is blank, deferring to the type-specific default rather than
  hardcoding 40%.
- **Add Property form fields now loop until valid input** — four fields that previously returned
  `None` silently on blank input (dropping the user back to the main menu mid-entry) have been
  replaced with `while True` loops: Original price (required), MLS # (required), Annual property
  taxes (required), and Total sq ft (defaults to 5,000, shown in prompt). Hotel rooms now
  defaults to 0 instead of requiring explicit entry.

### Added

- **36-test suite for explicit rent inputs** — `tests/test_explicit_rent_inputs.py` covers all
  eight property types (Office, Retail, Industrial, Mixed-Use, Hotel, Retail-Office, Residential,
  Multi-Family) across: explicit rent bypasses city-data lookup, correct `_comm_rent`/`_res_rent`
  split, unit mix preservation, city-data fallback when no explicit rent is given, and breakdown
  message labelling.

---

## [1.2.0] — 2026-06-08

### Fixed

- **HTML modal Market Staleness row now renders** — `property_report.py` imports
  `METRIC_MARKET_STALENESS` from `analysis/metrics/returns.py` and interpolates it via a
  local `staleness_key` variable into the JS `SECTIONS` array. The previous template contained
  the literal string `"{METRIC_MARKET_STALENESS}"` which never matched any result key, making
  the Market Staleness row permanently invisible in the modal.
- **HTML modal Price/Sq Ft row now renders** — Pricing section key changed from the exact
  string `"Price/Sq Ft"` to the wildcard `"Price/Sq Ft (*"`, matching the dynamic
  `f"Price/Sq Ft ({property_type})"` label emitted by `PricingMetrics`. The row was never
  visible for any property type.
- **HTML modal Income section keys corrected** — four stale or missing keys fixed:
  `"Annual Rent"` → `"Gross Potential Rent"` (matching `IncomeMetrics` output);
  `"Entry Cap Rate"` removed (metric is no longer emitted); `"Effective Gross Income"` and
  `"Vacancy Rate"` added (both emitted but previously absent from the key list).
- **HTML modal Hotel NRevPAR rows now render** — the single key `"NRevPAR"` replaced with
  three explicit keys `"NRevPAR (low dist.)"`, `"NRevPAR (mid dist.)"`, and
  `"NRevPAR (high dist.)"`, matching the labels emitted by `HotelMetrics`. All three rows
  were previously invisible.
- **City ranker `n_active` weight corrected** — `city_score_weights.n_active` reduced from
  `0.20` to `0.15` in `json/score_weights.json`; weights now sum to exactly `1.00`. The
  previous total of `1.05` allowed the raw opportunity score to exceed 100.
- **Price/Sq Ft suppressed for non-sqft asset classes** — `PricingMetrics` now sets
  `_show_sqft = ptype not in {"hotel", "residential", "multi-family"}` and skips the
  Price/Sq Ft row for those types. Hotel, residential, and multi-family properties do not
  trade on a price-per-sqft basis and the metric was misleading.
- **Mixed-use Price/Sq Ft uses commercial floor area** — `PricingMetrics` accepts a new
  `comm_sq_ft` parameter; `CommercialPropertyAnalyzer` passes
  `getattr(rent_resolver, "_comm_sq_ft", None)`. For mixed-use properties the denominator
  is now the commercial floor area rather than total building sqft, which previously inflated
  the metric by including residential floors.
- **Mixed-use `city_rent_per_sqft` now populated** — `RentResolver.resolve()` sets
  `self._city_rent_per_sqft = comm_rate` and `self._comm_sq_ft = floor_sq_ft` inside the
  `is_mixed` branch when a commercial rate is found. Previously the attribute was only set
  in the pure-commercial branch, leaving mixed-use properties with static sqft thresholds.
- **DOM scorer uses shared constant** — `PropertyScorer.score_property()` now looks up the
  DOM metric via `METRIC_MARKET_STALENESS` (imported from `analysis/metrics/returns.py`).
  Any future rename of the label only requires updating the one constant.
- **Listing date prompted on first add** — `_prompt_property()` in `ui/menu.py` now prompts
  for the listing date (defaulting to today) so that properties with a historical listing
  date correctly compute Days on Market from the first save.

### Changed

- **Unknown-city Location score is intentionally zero** — `PropertyScorer` returns
  `Location = 0.0` when a city has no entry in `json/city_distances.json`. This is now
  documented as deliberate: an unknown location is treated as worst-case rather than neutral,
  to incentivise keeping the distances file current. The corresponding xfail tests were
  replaced with passing assertions that verify the zero value.

---

## [1.1.0] — 2026-06-08

### Added

- `INCOME_METRIC_NAMES` — canonical `frozenset` exported from `analysis/metrics/income.py`
  and imported by `scoring/scorer.py`, `ui/menu.py`, and `reporting/printer.py`; replaces three
  independent inline sets that contained stale metric names.
- `ExitMetrics` and `ReturnMetrics` now accept an explicit `noi_growth_rate` keyword argument,
  making the growth rate an injected dependency rather than a side-effect read from `prop`.
- `ReturnMetrics.__init__` now accepts `noi_growth_rate: Optional[float]` directly from the
  analyzer, removing the implicit coupling to `prop.noi_growth_rate`.
- `CommercialPropertyAnalyzer` stores the resolved NOI growth rate as `self._noi_growth_rate`
  and surfaces it via `to_record()`, replacing the previous mutation pattern.
- `to_record()` now persists `vacancy_rate` and `noi_growth_rate` to the saved JSON record so
  that re-analysis reproduces the same figures without re-querying demographics data.
- `_parse_listing_date()` helper in `ui/menu.py`; `_prompt_property` now prompts for the
  listing date with a default of today, allowing historical dates to be entered on first add.
- `city_score_weights` and `city_score_thresholds` sections added to `DEFAULT_SCORE_CONFIG` in
  `scoring/scorer.py`, making all city opportunity score weights and thresholds user-configurable
  via the scoring menu.
- `val_prefix()` inner helper in `PropertyScorer.score_property()` for prefix-based metric
  lookups.

### Changed

- **Exit price now uses terminal NOI** — `ExitMetrics` computes
  `terminal_noi = est_noi × (1 + g) ^ hold_years` before dividing by the exit cap rate.
  Previously used year-1 NOI, understating exit value by ~22% on a 10-year hold at 2% growth.
- **IRR cash flows now hold the mortgage constant** — `ReturnMetrics` builds yearly flows as
  `year1_noi × (1 + g) ^ (yr − 1) − annual_mortgage`, accepting `year1_noi` as a dedicated
  parameter. The previous implementation escalated the full `(NOI − mortgage)` bundle, inflating
  late-year cash flows.
- **IRR row label is now dynamic** — `ReturnMetrics.rows()` emits `f"IRR ({hold_years}-Yr)"`
  instead of the hardcoded `"IRR (5-Yr)"`.
- **Scorer IRR lookup is now prefix-based** — `val_prefix("IRR (")` replaces
  `val("IRR (5-Yr)")`, preventing the IRR contribution from silently zeroing out for any
  hold period other than five years.
- **Break-even occupancy formula corrected** — `DebtMetrics` second parameter changed from
  `est_expenses: float` to `expense_ratio: float`; BEO is now computed as
  `annual_mortgage / (annual_rent × (1 − expense_ratio))`, the standard variable-expense
  formulation. The previous formula mixed an EGI-adjusted numerator against a gross-rent
  denominator, producing an inconsistently scaled result.
- **`CommercialPropertyAnalyzer` no longer mutates `PropertyInput`** — NOI growth rate is
  resolved into `self._noi_growth_rate` and passed explicitly to `ExitMetrics` and
  `ReturnMetrics`. `prop.noi_growth_rate` is left unchanged by the analyzer.
- **`_view` partial-results advisory** now uses `COMMERCIAL_TYPES_LOWER` (imported from
  `models.constants`) instead of a hardcoded tuple that excluded `hotel` and `retail-office`,
  which caused those types to display the wrong advisory message and point to the wrong menu
  option.
- **City ranker weights refactored** — hardcoded float literals replaced with lookups against
  `cfg["city_score_weights"]`, making all nine city-score factors configurable at runtime.

### Fixed

- `IncomeMetrics.rows()` no longer emits an `"Entry Cap Rate"` row; the value was identical to
  `"Cap Rate"` (same formula, same result), producing a duplicate row in every analysis report.
- `IncomeMetrics.rows()` suppresses the `"Vacancy Rate"` row for hotel properties. Hotel revenue
  is modelled via `rooms × ADR × occupancy × 365`, so a `0.0%` vacancy figure was misleading
  alongside the `"Occupancy Rate"` row already shown by `HotelMetrics`.

### Removed

- `"Entry Cap Rate"` row from `IncomeMetrics.rows()` (see Fixed above).

---

## [1.0.0] — 2026-05-01

### Added

- Full object-oriented refactor of the analysis pipeline.
- `ui/menu.py` split into four modules using the mixin pattern:
  `PropertyMenu`, `RateEditorMixin`, `ConfigEditorMixin`, `CsvHandlerMixin`.
- `models/constants.py` — sourced benchmark defaults:
  `VACANCY_RATE_DEFAULTS`, `EXPENSE_RATIO_DEFAULTS`, `EXPENSE_RATIO_RANGES`,
  `PROP_SHORTCUTS`, `PROPERTY_TYPES`, `COMMERCIAL_TYPES`, `COMMERCIAL_TYPES_LOWER`.
- `PropertyInput.__post_init__` auto-resolves `expense_ratio` and `vacancy_rate` from
  `models/constants.py` when `None` is supplied.
- `IncomeMetrics` — models vacancy: `EGI = annual_rent × (1 − vacancy_rate)`;
  expenses and NOI derived from EGI.
- `ExitCapEstimator` — exit cap built from entry cap plus an aging spread
  (10 bps/yr, capped at 10 years) and a market drift spread (25 bps).
- `ReturnMetrics` — Newton-Raphson IRR; equity multiple accounts for principal
  paydown via `exit_equity = exit_price − loan_balance`.
- `MarketMetrics` — seller bleed scaled by `vacancy_rate`.
- `HotelMetrics` — three NRevPAR scenarios: low / mid / high distribution cost.
- `IndustrialMetrics` — per-component income breakdown with clear-height premium.
- `PricingMetrics` — per-type GRM thresholds; price/sqft thresholds derived from
  `GRM × city_rent_per_sqft` when a market rate is available.
- Per-type expense ratio range validation with contextual warning messages.
- NOI growth rate resolved from `json/city_demographics.json` with staleness detection;
  defaults to 2 % when no locale data is present.
- `METRIC_MARKET_STALENESS` constant shared between `returns.py` and `scorer.py`.
- `README.md` v1.0 — purpose of every file, directory, JSON schema, menu reference,
  metrics glossary, and quick-start guide.
- `pytest` suite with branch coverage; `fail_under = 90` enforced via `.coveragerc`.

### Fixed

- `FileNotFoundError` on `json/commercial_rents.json` when selecting menu option 7
  before any properties have been saved; replaced with a user-friendly message and
  graceful return to the main menu.

### Removed

- `htmlcov/` directory and `--cov-report=html` flag from `pytest.ini`; VS Code
  Coverage Gutters reads `coverage.xml` directly.
