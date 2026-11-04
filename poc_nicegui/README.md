# Desktop UI — proof of concept (NiceGUI)

A throwaway prototype that proves the commercial property analyser can become a
modern **desktop `.exe`** that reuses the existing analysis engine and HTML reports.
It is **not** production code — see the caveats below.

## What it proves

1. **Modern look** — NiceGUI (Quasar/Material), not a Windows-98 widget toolkit.
2. **Type-aware dynamic form** — pick a property type and the form reshapes to show
   only the relevant field groups (hotel fields for a hotel, unit mix for
   residential, dock doors for industrial, …). Driven by `TYPE_GROUPS`, which
   mirrors how the engine already branches on type.
3. **It ships as a real desktop app** — `ui.run(native=True)` opens a standalone
   window (no browser), and PyInstaller packages it into one double-click `.exe`.
4. **Existing logic reused untouched** — the scorer, analyzer and `PropertyReport`
   HTML are the project's own code, imported directly.
5. **It reads AND writes the live SQLite database** via the project's `DataStore`.
   On first run it migrates the bundled seed into a persistent per-user DB; adding a
   property through the form persists it and the portfolio refreshes.
6. **All seven reports** (Investment, City opportunity, Deal watchlist, Negotiation,
   Vacancy, Price-drop, Benchmark) open inside the app, each reusing its existing
   generator's `render()` — no report logic rewritten.
7. **Rate editing** — a Rates tab edits the commercial ($/sq ft) and residential
   ($/mo) rents in the DB (`save_commercial_city` / `save_residential_city`).
8. **Global settings** — a Settings tab edits the financing defaults
   (`config/financing.json`) and the scoring weights & thresholds
   (`scorer.load_config`/`save_config`).

## Tabs

Portfolio · Add / Edit Property · Reports · Rates · Settings.

## Where the data lives

The app runs from a **writable per-user data dir** (seeded once from the bundle), so
config/rate edits never touch the read-only `.exe` bundle or the tracked repo files:

- **Packaged exe:** `%LOCALAPPDATA%\CommercialPropertyAnalyser\` — holds `properties.db`
  plus writable copies of `config/` and `json/`. Persists across restarts and updates.
- **Dev run:** `poc_nicegui/_data/` (gitignored), seeded from the worktree's `config/` +
  `json/` and the live repo-root `properties.json`.

## Run it (dev)

```bash
pip install nicegui pywebview
python poc_nicegui/app.py        # opens the native window
```

## Build the .exe

```bash
pip install pyinstaller
# from the project root, with the project on PYTHONPATH:
python -m PyInstaller --name CommercialPropertyAnalyser --onefile --windowed \
  --add-data "<site-packages>/nicegui;nicegui" \
  --add-data "json;json" --add-data "config;config" \
  --add-data "properties.json;." \
  poc_nicegui/app.py
```

Output: `dist/CommercialPropertyAnalyser.exe` (~100 MB; onefile is slow to first-start).

## Caveats (why this is a POC, not the product)

- **The form saves core fields + runs the real analyzer**, but it's add-only — no
  in-place edit/delete UI yet, and a few commercial inputs are captured but not all
  wired into the record. The full 44-field edit surface is Stage-D work.
- **No Playwright/scraper.** Deliberately excluded so the exe stays importable and
  small; bundling the realtor.ca scraper + a headless browser is separate Stage-E work.
- **Report helpers are copied** from `ui/menu.py` so the exe doesn't import the CLI.
  In the real build these move into a shared service layer (Stage A of the plan).
