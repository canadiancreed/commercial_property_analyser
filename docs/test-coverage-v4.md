# Test-coverage audit — v4.0.0 → v4.10.0

A per-release map of every feature shipped since the v4 line began to the unit test(s)
that cover it. Produced for **v4.10.0**, whose goal was to verify that all v4 work has
valid unit tests and to close the gaps.

**Suite:** `python -m pytest -q` → **1452 passing**.

Status key: **✅ covered** · **🆕 added in 4.10.0** · **🖥 UI-only** (NiceGUI rendering /
button wiring / boot — validated by the `CPA_WEB=1` boot smoke-test, not unit tests; the
underlying logic is extracted and unit-tested, see 4.10.0).

| Release | Feature | Tests | Status |
|---|---|---|---|
| **4.0.0** | SQLite data layer; one-time JSON→DB migration | `test_data_store.py`, `test_data_store_sqlite.py` (`test_import_from_json`, `test_ensure_migrated_runs_once`, `test_import_leaves_json_untouched`) | ✅ |
| **4.1.0** | Desktop edit & delete; form→record save mapping | engine via `test_edit_rent_flags.py`, `test_analysis_analyzer.py`; mapping via `test_form_logic.py::build_property_input` | ✅ / 🆕 |
| **4.2.0** | Service layer (`record_to_prop`, `build_report_row`) | `test_reanalyze_city.py`, `test_integration_city_report.py`, reporting tests | ✅ |
| **4.3.0** | `reanalyze_properties` | `test_reanalyze_city.py`, `test_reanalysis_stale_residential.py`, `test_reanalysis_zero_annual_rent.py`, `test_reanalyze_error_logging.py` | ✅ |
| **4.4.0** | Construction cost; commercial lease expiry; save validation | construction/lease: `test_analysis_analyzer.py`, `test_metrics_*`, `test_models.py`; validation: `test_form_logic.py::validate_property_form` | ✅ / 🆕 |
| **4.5.0** | City-opportunity editor; City-data (distances/demographics) editors | config via `test_scoring_city_ranker.py`; the editor widgets | ✅ / 🖥 |
| **4.6.0** | realtor.ca URL scraper import (lazy) | `test_realtor_scraper_query.py`; the lazy-import app wiring | ✅ / 🖥 |
| **4.7.0** | DB schema versioning + migration scaffold; build script; icon | `test_data_store_sqlite.py` (`test_fresh_db_stamped_current`, `test_old_db_upgraded_in_place`) | ✅ |
| **4.7.1** | Portfolio address search | `test_form_logic.py::filter_rows` | 🆕 |
| **4.7.2** | Full-field edit; prefill provenance; `created_at`/`notes` carry-through | prefill/provenance: `test_form_logic.py` (`prefill_*`, `rent_prefills`); `created_at`: `test_analysis_analyzer.py`, `test_edit_rent_flags.py`; `notes` omitted by engine: `test_v410_coverage_gaps.py` | ✅ / 🆕 |
| **4.8.0** | Bank of Canada base-rate feed; base+spread pricing | `test_rate_feed_wiring.py` (11) | ✅ |
| **4.9.0** | Config DB table; per-asset-class financing editor | `test_config_store.py` (9); field coercion: `test_form_logic.py::coerce_financing_field` | ✅ / 🆕 |
| **4.9.1** | Build crash fix (worktree-depth guard); Makefile/make.ps1 | build-path logic (guard) | 🖥 |
| **4.9.2** | DB is the single source of truth (no JSON seed on boot) | `test_data_store_sqlite.py` migration guards; boot wiring | ✅ / 🖥 |
| **4.9.3** | Build outputs exe to repo root | build script | 🖥 |
| **4.9.4** | Hold period global (off form); type-switch keeps entered data | hold global: `test_form_logic.py::build_property_input`, `test_v410_coverage_gaps.py`; draft preservation: `test_form_logic.py` (`prefill_*`, `rent_prefills`) | 🆕 |
| **4.10.0** | Extract desktop logic → `form_logic.py`; this audit | `test_form_logic.py` (26), `test_v410_coverage_gaps.py` (3) | 🆕 |

## What remains UI-only (🖥)

These are validated by booting the app (`CPA_WEB=1 python poc_nicegui/app.py`) and clicking
through, not by unit tests, because they are NiceGUI rendering / wiring with no extractable
pure logic left:

- The type-aware form **rendering** (which field groups appear per property type) and the
  dialogs (report view, delete confirm).
- Button wiring and tab switching (Save / Re-analyze / Edit / Delete, the editors' Save
  buttons), notifications.
- The realtor.ca URL import flow (opens a real browser; 4.6.0) and the boot sequence
  (DB open, schema migrate, config seed, base-rate refresh thread; 4.0.0/4.7.0/4.8.0/4.9.2).

Their **pure logic** was extracted into `form_logic.py` in 4.10.0 and is unit-tested above;
what's left is the thin UI shell.
