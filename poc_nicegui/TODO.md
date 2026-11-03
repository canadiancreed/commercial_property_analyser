# Desktop App — Roadmap / TODO

**Version point of truth:** `version.py` (`__version__`) at the repo root. Keep the
README title and the top `changelog.md` entry in sync with it.

**Convention:** each completed step below is a **minor** bump (4.1.0, 4.2.0, …);
**major** only for a storage/architecture break; **patch** for fixes.

**Current — v4.0.0:** SQLite data layer (properties + commercial_rents +
residential_rents tables behind the unchanged `DataStore` API, guarded JSON→DB
migration) + a NiceGUI desktop app (`poc_nicegui/`) with Portfolio, type-aware Add
form, all 7 reports embedded, rate editing, and global settings — packaged as a
standalone Windows `.exe` over a persistent per-user database.

---

## Planned steps (roughly in order)

### 4.1.0 — Property edit & delete
- Load an existing record into the type-aware form, save changes in place.
- Delete with confirmation. Wire to `store.update_property` / `store.delete_property`
  (both index-based — use a stable key lookup, not a grid row index, in the UI).

### 4.2.0 — Stage A: shared service layer
- Extract `_record_to_prop`, `_build_report_row`, and the report orchestration out of
  `ui/menu.py` into a service module; delete the COPIES in `poc_nicegui/app.py` and have
  both the CLI and the desktop app call the service. (Removes the only real code
  duplication introduced by the POC.)

### 4.3.0 — Re-analysis on data change
- After a rate or financing edit, re-analyze affected stored properties (mirror the CLI
  `_reanalyze_city` / `_reanalyze_all`) so stored results don't go stale.
- Add a "Re-analyze all" action to the desktop app.

### 4.4.0 — Full add/edit field surface + validation
- Wire the remaining per-type inputs into the saved record (commercial rent semantics,
  NNN lease, exit/market cap, construction cost, commercial lease expiry, industrial
  rates). Add inline validation + required-field errors.

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
- **Copied helpers:** `record_to_prop` / `build_report_row` in `poc_nicegui/app.py` are
  verbatim copies from `ui/menu.py` (so the exe doesn't import the CLI → Playwright).
  Retire them in 4.2.0.
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
