# Desktop App — Roadmap / TODO

**Version point of truth:** `version.py` (`__version__`) at the repo root. Keep the
README title and the top `changelog.md` entry in sync with it.

**Convention:** each completed step below is a **minor** bump (4.1.0, 4.2.0, …);
**major** only for a storage/architecture break; **patch** for fixes.

**Current — v4.4.0:** SQLite data layer (properties + commercial_rents +
residential_rents tables behind the unchanged `DataStore` API, guarded JSON→DB
migration) + a NiceGUI desktop app (`poc_nicegui/`) with Portfolio, type-aware
Add/Edit form (**edit & delete done in 4.1.0**), all 7 reports embedded, rate editing,
and global settings — packaged as a standalone Windows `.exe` over a persistent
per-user database.

---

## Planned steps (roughly in order)

### ✅ 4.1.0 — Property edit & delete (DONE)
- Edit loads a record into the type-aware form (reshaped + prefilled), re-runs the
  analyzer on save, updates in place (removes the original first so a key change can't
  duplicate). Delete confirms then removes. Report iframes cache-busted.
- NOTE: edit/delete currently key off the load-order **index** (fine for single-user;
  revisit with a stable key if concurrency is ever added).

### ✅ 4.2.0 — Stage A: shared service layer (DONE)
- `record_to_prop` + `build_report_row` now live in `analysis/report_builder.py`, imported
  by both `ui/menu.py` (re-exposed as `PropertyMenu._record_to_prop` / `_build_report_row`)
  and `poc_nicegui/app.py`. The POC's verbatim copies are gone. (Report-orchestration
  loops — `_rows_simple` / `_rows_with_targets` and the CLI `_open_*` — are still per
  front-end; a fuller service is optional later.)

### ✅ 4.3.0 — Re-analysis on data change (DONE)
- `reanalyze_properties()` in `analysis/report_builder.py` (headless, predicate-filterable).
- "Re-analyze all" action on the Portfolio tab (threaded + spinner). Rate saves
  auto-re-analyze the affected city; financing save nudges to Re-analyze all.

### ✅ 4.4.0 — Full add/edit field surface + validation (DONE)
- Added construction cost + commercial lease expiry; commercial-rent-user-entered flag;
  inline validation (price > 0, sq ft ≥ 0) + save-time guards. All per-type fields now
  wired + prefilled on edit.

### 4.5.0 — Remaining CLI features
- CSV import and realtor.ca URL import.
- Deeper scoring sub-editors: city opportunity weights, city distances, demographics.

### 4.6.0 — Scraper (the hard packaging one, "Stage E")
- Bundle Playwright + Firefox into the `.exe`; wire the realtor.ca price-check sweep with
  a progress UI. Expect real trial-and-error here — bundling a headless browser is the
  fiddliest part of shipping the exe.

### 4.7.0 — Packaging & robustness polish
- App icon; `--onedir` build option (faster startup than onefile); an installer.
- DB `user_version` pragma + a schema-migration path for future changes.
- Optionally move missing-cities / price-check progress into the DB.

---

## Known gaps / notes for whoever picks this up
- **Shared helpers:** `record_to_prop` / `build_report_row` live in
  `analysis/report_builder.py` (done in 4.2.0), imported by both the CLI and the POC — so
  the exe still doesn't import the CLI (→ Playwright), and there's no duplication.
- **Report performance:** the two target-solving reports (Investment, Negotiation) run
  `solve_targets` per property and are slow at full scale — they run in a background
  thread with a spinner.
- **No POC tests yet:** the domain/engine is fully covered (1401 tests), but the
  `poc_nicegui/` UI code itself has none.
- **Data locations (writable):** `%LOCALAPPDATA%\CommercialPropertyAnalyser\` for the exe,
  `poc_nicegui/_data/` in dev — each holds `properties.db` plus writable copies of
  `config/` and `json/`, seeded once from the bundle/worktree.
- **Build:** `python -m PyInstaller … poc_nicegui/app.py` (nicegui-pack needs PyInstaller
  on PATH; calling PyInstaller as a module avoids that). Gotchas already solved: the
  `@ui.page` requirement for onefile, the `sys.argv[0]` base_uri fix after chdir, and the
  multiprocessing `freeze_support()` guard.
