"""
NiceGUI proof-of-concept for the Commercial Property Analyser desktop UI.

Proves the desktop path against the REAL data before committing to a full build —
  1. A modern, non-"Windows 98" look.
  2. A type-aware dynamic form (fields appear/disappear by property type).
  3. The existing HTML reports drop straight into the desktop shell with zero rework.
  4. It READS AND WRITES the live SQLite database via the project's DataStore — a
     persistent, per-user DB migrated once from the bundled seed data. Adding a
     property persists it and the portfolio refreshes.

All financial logic and storage are the project's production code, called directly.
"""

import os
import sys
import re
import time
import asyncio
import threading
import statistics
import tempfile
from pathlib import Path

# ── Locate the project + a WRITABLE data directory ────────────────────────────
WORKTREE = Path(__file__).resolve().parents[1]

if getattr(sys, "frozen", False):
    # Packaged (.exe): project code + reference/config seed are bundled read-only under
    # _MEIPASS (wiped on exit), so the live DB lives in a persistent, writable dir. Keep it
    # inside the project — a 'db' folder beside the executable — not buried in %LOCALAPPDATA%.
    BASE = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    APP_HOME = Path(sys.executable).resolve().parent
    _LEGACY_DATA_DIR = (Path(os.environ.get("LOCALAPPDATA") or Path.home())
                        / "CommercialPropertyAnalyser")
else:
    # Dev: run from source. The DB lives in the project's db/ folder.
    BASE = WORKTREE
    APP_HOME = WORKTREE
    _LEGACY_DATA_DIR = WORKTREE / "poc_nicegui" / "_data"

DATA_DIR = APP_HOME / "db"
sys.path.insert(0, str(BASE))  # import the project packages from the code location
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "properties.db"

# One-time relocation (5.1.5): bring an existing database over from the pre-5.1.5 location
# (frozen: %LOCALAPPDATA%\CommercialPropertyAnalyser; dev: poc_nicegui\_data) so moving the
# DB into the project folder never loses data. Copy, not move — the old file stays as a
# backup until the user removes it.
if not DB_PATH.exists():
    _legacy_db = _LEGACY_DATA_DIR / "properties.db"
    if _legacy_db.exists():
        import shutil as _shutil
        _shutil.copy2(_legacy_db, DB_PATH)
        print(f"[CPA] Relocated database {_legacy_db} -> {DB_PATH}")

# v5.0.0: all reference/config/runtime data lives in the DB, seeded from data/seeds — no
# config/ or json/ files are copied or read. We still chdir into the writable data dir so
# generated artifacts (reports) and any other relative paths resolve under a user-writable
# location rather than the read-only bundle (_MEIPASS).
# pywebview derives a default base_uri from sys.argv[0] AT IMPORT TIME; once we chdir into
# the data dir a relative argv[0] would no longer resolve, so pin it to an absolute path
# first (a frozen exe already has an absolute argv[0]).
if not getattr(sys, "frozen", False):
    sys.argv[0] = str(Path(__file__).resolve())

os.chdir(DATA_DIR)             # run from the writable data dir (reports, etc.)

from datetime import date

from data.store import DataStore, CommercialRentLoader, ResidentialRentLoader
from analysis.rent_resolver import RentResolver
from analysis.analyzer import CommercialPropertyAnalyzer, build_partial_record
from analysis.report_builder import record_to_prop, build_report_row, reanalyze_properties
import form_logic
from analysis import financing_config, screener_config, underwriting_config, industrial_config
from analysis import vacancy_resolver
from analysis.financing_config import (
    resolve_financing, mixed_use_commercial_gfa_share,
    load_financing_config, save_financing_config, base_rate_info,
    get_raw_config, save_raw,
)
from scoring.scorer import PropertyScorer
from scoring.city_ranker import CityRanker
from reporting.property_report import PropertyReportGenerator
from reporting.city_report import CityReportGenerator
from reporting.deal_watchlist_report import DealWatchlistReportGenerator
from reporting.negotiation_report import NegotiationReportGenerator
from reporting.vacancy_report import VacancyReportGenerator
from reporting.price_drop_report import PriceDropReportGenerator
from reporting.benchmark_report import BenchmarkReportGenerator
from models.property_input import PropertyInput, UnitMix
from models.constants import PROPERTY_TYPES, PROVINCE_CODES
from version import __version__

from nicegui import ui, app, native

# Persistent SQLite store. The DB is the single source of truth for property records —
# the app loads whatever the database contains (empty on a brand-new DB) and never seeds
# or imports from properties.json. Importing data is a separate, explicit action.
# (Rent rates + config still seed once from the bundled json/ + config/ reference files,
# below / via the config table — those are reference/config, not the user's property data.)
store = DataStore(properties_path=str(DB_PATH), seed=True)
store.ensure_seeded()   # populate config / app_data / rate + city tables from data/seeds
# One-time cleanup of legacy imports that stored 'street, city, province' in the address field.
store.normalize_addresses(form_logic.clean_address)

# Route every config/reference loader through the DB (v5.0.0: the DB is the single live
# source; data/seeds provides the shipped defaults). No .json file is read at runtime.
financing_config.set_store(store)
screener_config.set_store(store)
underwriting_config.set_store(store)
industrial_config.set_store(store)
vacancy_resolver.set_store(store)


# ── Live base-rate feed (Bank of Canada GoC 5yr) ─────────────────────────────
# Auto-refresh the sourced base rate on boot: one lightweight BoC Valet call,
# throttled to once/day, fully offline-safe. A failed fetch keeps the last good
# cached rate (the DB 'interest_rates' doc; the engine ultimately falls back to the
# authored anchor), so this never blocks or breaks startup. Runs off-thread.
def _refresh_base_rate_async():
    try:
        from analysis.rate_feed import refresh_interest_rates
        changed, _reason = refresh_interest_rates(max_age_hours=20, store=store)
        if changed:
            financing_config.reload_rate_feed()
    except Exception:
        pass

threading.Thread(target=_refresh_base_rate_async, name="boc-rate-refresh", daemon=True).start()

resolver = RentResolver(
    commercial_loader  = CommercialRentLoader(store),
    residential_loader = ResidentialRentLoader(store),
    data_store         = store,
)
scorer    = PropertyScorer(store)
ranker    = CityRanker(scorer)
prop_rpt  = PropertyReportGenerator()
city_rpt  = CityReportGenerator()
watch_rpt = DealWatchlistReportGenerator()
nego_rpt  = NegotiationReportGenerator()
vac_rpt   = VacancyReportGenerator()
drop_rpt  = PriceDropReportGenerator()
bench_rpt = BenchmarkReportGenerator()

# Static directory where rendered reports are served into an <iframe> — proving
# the existing report HTML renders intact inside the desktop shell.
REPORTS_DIR = Path(tempfile.gettempdir()) / "cpa_poc_reports"
REPORTS_DIR.mkdir(exist_ok=True)
app.add_static_files("/reports", str(REPORTS_DIR))


# record_to_prop / build_report_row are imported from analysis.report_builder — the
# single shared source used by both the CLI (ui/menu.py) and this desktop app.


# ── Field-group model: the single source of truth a dynamic form reads ────────
# This mirrors how the ENGINE already branches on property type (HotelMetrics,
# IndustrialMetrics, unit-mix resolution, mixed-use component engine). The form
# just renders whichever groups a type uses — nothing bolted on.
TYPE_GROUPS = {
    "Office":        ["commercial"],
    "Retail":        ["commercial"],
    "Retail-Office": ["commercial"],
    "Mixed-Use":     ["commercial", "residential"],
    "Industrial":    ["commercial", "industrial"],
    "Hotel":         ["hotel"],
    "Residential":   ["residential"],
    "Multi-Family":  ["residential"],
}
GROUP_LABEL = {
    "commercial":  "Commercial lease",
    "residential": "Residential unit mix",
    "hotel":       "Hotel operations",
    "industrial":  "Industrial building detail",
}


def _metric(record: dict, name: str) -> str:
    for r in record.get("results", []):
        if r.get("metric") == name:
            return r.get("value", "—")
    return "—"


def _has_analysis(record: dict) -> bool:
    return bool(record.get("results"))


# ── Shared styling ────────────────────────────────────────────────────────────
STAT_CARD = "flex-1 min-w-[150px] rounded-xl shadow-sm border border-slate-200 bg-white p-4"

# Cross-tab UI handles so a save on the form can refresh the portfolio list.
_ui = {}


def _dark_toggle_button():
    """Top-right dark/light switch. Flips NiceGUI's dark mode and persists the choice to
    the DB (ui_prefs config doc) so it survives a reload (4.12.8)."""
    dark = _ui.get("dark_mode")
    if dark is None:
        return

    def _toggle():
        dark.toggle()
        btn.props(f'icon={"light_mode" if dark.value else "dark_mode"}')
        try:
            store.write_config("ui_prefs", {"dark": bool(dark.value)})
        except Exception:
            pass

    btn = ui.button(icon=("light_mode" if dark.value else "dark_mode"),
                    on_click=_toggle).props("flat round dense color=white")
    btn.tooltip("Toggle dark / light mode")


def header():
    with ui.header().classes("items-center justify-between px-6 py-3 bg-slate-900 text-white shadow"):
        with ui.row().classes("items-center gap-3"):
            ui.icon("domain").classes("text-2xl text-blue-400")
            with ui.column().classes("gap-0"):
                ui.label("Commercial Property Analyser").classes("text-lg font-semibold leading-tight")
                ui.label("Desktop UI — proof of concept").classes("text-xs text-slate-400 leading-tight")
        with ui.row().classes("items-center gap-3"):
            ui.label(f"v{__version__} · live SQLite database").classes("text-xs text-slate-300")
            _dark_toggle_button()


def _load_rows() -> list:
    rows = []
    for i, p in enumerate(store.load_properties()):
        rows.append({
            "id": i,
            # Stable identity (the table's UNIQUE key) so a click maps to the right record
            # even after the load order shifts — a cached positional id can go stale.
            "_addr": p.get("address") or "",
            "_ld": p.get("listing_date") or "",
            "address": p.get("address") or "—",
            "city": (f"{p.get('city')}, {p.get('province')}"
                     if p.get("city") else "—"),
            "type": p.get("property_type") or "—",
            "asking": p.get("asking_price", 0),
            "sqft": p.get("total_sq_ft", 0),
            "cap": _metric(p, "Cap Rate"),
            "status": p.get("status") or "—",
            "analyzed": "✓" if _has_analysis(p) else "—",
        })
    return rows


def _apply_portfolio_filter():
    """Push the cached rows into the grid, narrowed to the live address search term."""
    grid = _ui.get("grid")
    if grid is None:
        return
    rows = form_logic.filter_rows(_ui.get("all_rows") or [], _ui.get("search_term"))
    grid.options["rowData"] = rows
    grid.update()


def refresh_portfolio():
    """Re-read the DB and refresh the stat tiles + grid (called after a save)."""
    if "stats" in _ui:
        _ui["stats"].refresh()
    _ui["all_rows"] = _load_rows()
    _apply_portfolio_filter()


def _show_reanalyze_issues(issues):
    """Dialog listing the properties a Re-analyze all did NOT update, with the reason —
    errors first (need attention), then skips (usually a city with no market rent yet)."""
    errs  = [x for x in issues if x.get("kind") == "error"]
    skips = [x for x in issues if x.get("kind") == "skipped"]
    with ui.dialog() as d, ui.card().classes("p-4 gap-2 w-[640px] max-w-full"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("rule").classes("text-blue-600")
            ui.label(f"Not re-analyzed — {len(errs)} error(s), {len(skips)} skipped").classes(
                "font-semibold text-slate-800")
        ui.label("Errors need attention; skips are usually a city with no market rent rates "
                 "yet (add the rate on the Rates tab, then Re-analyze).").classes(
            "text-xs text-slate-500")
        with ui.scroll_area().classes("w-full").style("height:min(50vh,420px)"):
            for title, items, color, icon in (
                    ("Errors", errs, "text-red-600", "error"),
                    ("Skipped", skips, "text-amber-600", "info")):
                if not items:
                    continue
                ui.label(f"{title} ({len(items)})").classes(
                    "text-xs font-semibold text-slate-500 mt-2")
                for x in items:
                    with ui.row().classes("w-full items-start gap-2 border-b border-slate-100 py-1"):
                        ui.icon(icon).classes(f"{color} text-base mt-0.5")
                        with ui.column().classes("gap-0 flex-1"):
                            ui.label(x.get("address") or "—").classes(
                                "text-sm font-medium text-slate-700")
                            _meta = " · ".join(p for p in (x.get("city"), x.get("property_type"),
                                                           x.get("mls")) if p)
                            if _meta:
                                ui.label(_meta).classes("text-xs text-slate-400")
                            ui.label(x.get("reason") or "").classes("text-xs text-slate-500")
        with ui.row().classes("w-full justify-end"):
            ui.button("Close", on_click=d.close).props("flat")
    d.open()


# ── Page 1: Portfolio list ────────────────────────────────────────────────────
def portfolio_tab():

    @ui.refreshable
    def stats():
        props = store.load_properties()
        prices = [p.get("asking_price", 0) for p in props if p.get("asking_price")]
        cities = {p.get("city") for p in props if p.get("city")}
        analyzed = sum(1 for p in props if _has_analysis(p))
        with ui.row().classes("w-full gap-3 mb-4"):
            for label, value in [
                ("Properties", f"{len(props):,}"),
                ("Cities", f"{len(cities):,}"),
                ("Analyzed", f"{analyzed:,}"),
                ("Median asking", f"${statistics.median(prices):,.0f}" if prices else "—"),
            ]:
                with ui.column().classes(STAT_CARD + " gap-1"):
                    ui.label(value).classes("text-2xl font-bold text-slate-900")
                    ui.label(label).classes("text-xs uppercase tracking-wide text-slate-500")

    stats()
    _ui["stats"] = stats

    _ui["all_rows"] = _load_rows()

    def on_search(e):
        _ui["search_term"] = e.value or ""
        _apply_portfolio_filter()

    with ui.row().classes("w-full items-center mb-2"):
        search = (ui.input(placeholder="Search by address or city…", on_change=on_search)
                  .props('clearable dense outlined input-class=text-sm')
                  .classes("w-full max-w-md"))
        _ui["search"] = search

    grid = ui.aggrid({
        "columnDefs": [
            {"headerName": "Address", "field": "address", "flex": 2, "filter": True},
            {"headerName": "City", "field": "city", "flex": 1, "filter": True},
            {"headerName": "Type", "field": "type", "width": 130, "filter": True},
            {"headerName": "Asking", "field": "asking", "width": 130,
             "valueFormatter": "'$' + (value||0).toLocaleString()",
             "type": "numericColumn"},
            {"headerName": "Sq Ft", "field": "sqft", "width": 110,
             "valueFormatter": "(value||0).toLocaleString()", "type": "numericColumn"},
            {"headerName": "Cap Rate", "field": "cap", "width": 110},
            {"headerName": "Status", "field": "status", "width": 100},
            {"headerName": "Rpt", "field": "analyzed", "width": 70},
        ],
        "rowData": _ui["all_rows"],
        "rowSelection": "single",
        "defaultColDef": {"sortable": True, "resizable": True},
        "pagination": True,
        "paginationPageSize": 25,
    }).classes("h-[62vh]")
    _ui["grid"] = grid

    async def on_reanalyze_all():
        note = ui.notification("Re-analyzing all properties…", spinner=True, timeout=None)
        try:
            res = await asyncio.to_thread(reanalyze_properties, store, resolver,
                                          CommercialPropertyAnalyzer)
        finally:
            note.dismiss()
        refresh_portfolio()
        ui.notify(
            f"Re-analyzed {res['updated']}/{res['total']} "
            f"({res['skipped']} skipped, {res['errors']} error(s)).",
            type="positive",
        )
        if res.get("issues"):
            _show_reanalyze_issues(res["issues"])

    with ui.row().classes("w-full items-center mt-2"):
        ui.label("Tip: click any row to open that property's investment report "
                 "(the existing HTML, rendered inside the app).").classes(
            "text-xs text-slate-500 mr-auto")
        ui.button("Add from URL", icon="link",
                  on_click=open_url_import).props("outline no-caps dense")
        ui.button("Re-analyze all", icon="refresh",
                  on_click=on_reanalyze_all).props("outline no-caps dense")

    async def on_click(e):
        # Extract ONLY the row's `data` client-side (3rd arg below). Sending the whole
        # AG Grid event fails with "circular structure to JSON" (context/beans refs),
        # which silently drops the event before it reaches Python.
        row = (e.args or {}).get("data") or {}
        # Resolve by the stable (address, listing_date) key, NOT the cached positional id —
        # the load order shifts on edit/add/delete, so a cached id can point at the wrong
        # record (or out of range).
        idx = form_logic.resolve_row_index(store.load_properties(), row.get("_addr"), row.get("_ld"))
        if idx is not None:
            await open_report(idx)
        elif row:
            ui.notify("Couldn't locate that property — refreshing the list.", type="warning")
            refresh_portfolio()

    grid.on("rowClicked", on_click, args=["data"])


async def open_report(idx: int):
    props = store.load_properties()
    if idx is None or idx >= len(props):
        return
    p = props[idx]

    def _current_index():
        # Re-resolve from the record's stable key at action time (the list may have shifted
        # since the dialog opened), so Edit/Delete never act on the wrong — or a blank — row.
        return form_logic.resolve_row_index(store.load_properties(),
                                            p.get("address"), p.get("listing_date"))

    def _edit():
        dialog.close()
        i = _current_index()
        if i is None:
            ui.notify("That property is no longer in the list.", type="warning"); refresh_portfolio(); return
        load_for_edit(i)

    def _delete():
        i = _current_index()
        if i is None:
            dialog.close(); ui.notify("That property is no longer in the list.", type="warning")
            refresh_portfolio(); return
        confirm_delete(i, dialog)

    with ui.dialog() as dialog, ui.card().classes("w-[92vw] max-w-[1200px] h-[88vh] p-0 flex flex-col"):
        with ui.row().classes("w-full items-center justify-between px-4 py-2 bg-slate-900 text-white"):
            ui.label(p.get("address") or "Property report").classes("font-semibold")
            with ui.row().classes("items-center gap-1"):
                ui.button("Edit", icon="edit", on_click=_edit).props("flat dense no-caps color=white")
                ui.button("Delete", icon="delete", on_click=_delete).props("flat dense no-caps color=white")
                ui.button(icon="close", on_click=dialog.close).props("flat round color=white")
        body = ui.column().classes("w-full flex-1 p-0 items-center justify-center")
        with body:
            ui.spinner(size="lg")
            ui.label("Building report with the production scorer…").classes("text-slate-500")
    dialog.open()

    try:
        scored  = scorer.score_property(p)
        targets = scorer.solve_targets(
            p, record_to_prop, CommercialPropertyAnalyzer, resolver)
        row  = build_report_row(p, scored, targets)
        html = prop_rpt.render([row])
        out  = REPORTS_DIR / f"report_{idx}.html"
        out.write_text(html, encoding="utf-8")
        body.clear()
        with body:
            # ui.html() strips <iframe>, so create a real iframe element. The report
            # is a full HTML document, so it renders isolated inside the frame.
            ui.element("iframe").props(f"src=/reports/report_{idx}.html?t={time.time_ns()}").style(
                "width:100%;height:100%;border:0;").classes("w-full h-full")
    except Exception as ex:
        body.clear()
        with body:
            ui.icon("info").classes("text-4xl text-amber-500")
            ui.label("No report for this record").classes("font-medium")
            ui.label(str(ex)).classes("text-xs text-slate-500 max-w-[600px] text-center")


# ── Page 2: dynamic, type-aware Add/Edit form ─────────────────────────────────
state = {"type": None}   # blank on a new entry — a type must be chosen before saving (4.12.1)
FIELDS = {}  # name → input element, rebuilt each time the form reshapes
_draft = {}  # last-entered field values, carried across a type switch so reshaping the
             # form never discards what's already typed (cleared on reset / edit / save).
# When load_for_edit programmatically sets the type dropdown, its on_change must NOT snapshot
# the (old/blank) form into _draft — that would overwrite the record's prefill and blank the
# edit form. This flag suppresses the snapshot during that programmatic set.
_suppress_type_change = {"on": False}
# When the report's "Edit" button jumps to the form tab it does so programmatically AFTER
# loading the record; the tab-change handler must NOT treat that as a user click (which would
# reset the edit it just loaded). This flag suppresses the reset during that programmatic jump.
_programmatic_tab = {"on": False}
# index=None → add mode; otherwise editing the record at that position (load order).
edit_ctx = {"index": None, "orig_key": None, "record": None}

# Reusable inline field validators (4.12.3). A blank/None value passes (fields are optional
# unless required in save_property_from_form), so these only reject clearly-invalid input
# as the user types. The authoritative gate is form_logic.validate_property_form, which
# re-checks the same rules at save time so bad data can never be persisted.
_V_NONNEG = {"Can't be negative": lambda v: v is None or v >= 0}
_V_PCT    = {"Must be between 0 and 100": lambda v: v is None or 0 <= v <= 100}
_V_GROWTH = {"Must be between -100 and 100": lambda v: v is None or -100 <= v <= 100}
_V_MIN1   = {"Must be at least 1": lambda v: v is None or v >= 1}


def _snapshot_form():
    """Capture the current input values into _draft so changing the property type (which
    rebuilds the form) preserves everything already entered."""
    for k, w in FIELDS.items():
        try:
            _draft[k] = w.value
        except Exception:
            pass


@ui.refreshable
def dynamic_form():
    FIELDS.clear()
    rec = edit_ctx["record"] or {}
    um  = rec.get("unit_mix") or {}
    groups = ["common"] + TYPE_GROUPS.get(state["type"], [])

    def pv(key, default=None):
        return form_logic.prefill_value(key, _draft, rec, default)

    def pvpct(key):
        return form_logic.prefill_pct(key, _draft, rec)

    # Rent prefills are conditional on provenance so editing a record doesn't silently
    # "freeze" a market-estimated figure as a user-entered one. A commercial/residential
    # rent is only prefilled when the record flags it as owner-entered; the direct total
    # (annual_rent) is only prefilled when there is no component rent to recompute from
    # — the same guard record_to_prop uses for re-analysis.
    _rents = form_logic.rent_prefills(_draft, rec)
    comm_prefill, res_prefill, annual_prefill = (
        _rents["commercial_rent"], _rents["residential_rent"], _rents["annual_rent"])

    # Resolved (global) financing — shown read-only so the form is complete; down
    # payment / rate / amortization live in Settings, not per property.
    _um_counts = rec.get("unit_mix") or {}
    _units_preview = sum(_um_counts.get(k, 0) or 0 for k in
                         ("bachelor", "one_br", "two_br", "three_br", "four_br", "unknown"))
    try:
        _fin_preview = resolve_financing(rec.get("asking_price") or 0,
                                         state["type"], _units_preview or None) \
            if state["type"] else {}   # no type picked yet → no per-type financing to preview
    except Exception:
        _fin_preview = {}

    # Add vs edit banner.
    if edit_ctx["index"] is not None:
        with ui.row().classes("w-full items-center gap-2 mb-2"):
            ui.badge("Editing").props("color=orange")
            ui.label(rec.get("address") or "—").classes("text-sm font-medium text-slate-700")
            ui.button("New / cancel", icon="close", on_click=reset_form).props("flat dense no-caps")

    # Live indicator of which groups this type activates.
    with ui.row().classes("gap-2 flex-wrap mb-2"):
        ui.label("Active field groups:").classes("text-sm text-slate-500 self-center")
        for g in groups:
            ui.badge(GROUP_LABEL.get(g, "Core details")).props("color=primary" if g != "common" else "color=grey-6")

    def card(title, icon):
        c = ui.card().classes("w-full mb-3 rounded-xl border border-slate-200 shadow-sm")
        with c:
            with ui.row().classes("items-center gap-2 mb-1"):
                ui.icon(icon).classes("text-blue-600")
                ui.label(title).classes("font-semibold text-slate-800")
        return c

    # Common — always shown.
    with card("Core details", "description"):
        with ui.row().classes("w-full gap-3"):
            FIELDS["address"]  = ui.input("Address", value=pv("address", "")).classes("flex-1")
            FIELDS["city"]     = ui.input("City", value=pv("city", "")).classes("w-40")
            _prov = (pv("province", "") or "").strip().upper() or None
            # Options are the 13 province/territory codes; if an edited record somehow holds a
            # non-standard value, keep it as an option so editing never silently drops it.
            _prov_opts = list(PROVINCE_CODES) + (
                [_prov] if _prov and _prov not in PROVINCE_CODES else [])
            FIELDS["province"] = ui.select(_prov_opts, value=_prov, label="Province",
                                           with_input=True, clearable=True).classes("w-28")
        with ui.row().classes("w-full gap-3"):
            FIELDS["mls_number"] = ui.input("MLS #", value=pv("mls_number", "")).classes("w-48")
            FIELDS["asking_price"]   = ui.number("Asking price", value=pv("asking_price"), prefix="$", format="%.0f",
                                                 validation={"Must be greater than 0": lambda v: v is None or v > 0}).classes("flex-1")
            FIELDS["original_price"] = ui.number("Original / list price", value=pv("original_price"), prefix="$", format="%.0f",
                                                 validation=_V_NONNEG).classes("flex-1")
        with ui.row().classes("w-full gap-3"):
            FIELDS["total_sq_ft"]    = ui.number("Total sq ft", value=pv("total_sq_ft"), format="%.0f",
                                                 validation=_V_NONNEG).classes("flex-1")
            # Floors is a building-wide attribute (every type has it) — in Core details, not
            # the residential group, so it's enterable for office/retail/industrial/hotel too.
            FIELDS["floors"] = ui.number("Floors", value=um.get("floors", rec.get("floors", 1)) or 1,
                                         format="%d", validation=_V_MIN1).classes("w-28")
            FIELDS["property_taxes"] = ui.number("Property taxes / yr", value=pv("property_taxes"), prefix="$", format="%.0f",
                                                 validation=_V_NONNEG).classes("flex-1")
            FIELDS["construction_cost"] = ui.number("Construction cost", value=pv("construction_cost"), prefix="$", format="%.0f",
                                                    validation=_V_NONNEG).classes("flex-1")
        with ui.row().classes("w-full gap-3"):
            FIELDS["lease_type"]   = ui.select(["Normal", "NNN"], value=pv("lease_type", "Normal"), label="Lease type").classes("w-40")
            FIELDS["status"]       = ui.select(["active", "inactive"], value=pv("status", "active"), label="Status").classes("w-40")
            FIELDS["listing_date"] = ui.input("Listing date", value=pv("listing_date", "")).props("type=date").classes("w-48")
            # hold_years is NOT per-property — it's a global house-wide setting
            # (config/financing.json defaults, edited on the Settings tab) applied to every
            # property. It is deliberately not on this form.
        if _fin_preview:
            # This is the per-type RESOLVED financing actually applied to this property
            # (per-type lending rules priced over the LIVE Bank of Canada base rate),
            # NOT the raw Settings defaults — so it legitimately differs from the
            # Settings screen for most types.
            _bv = _fin_preview.get("base_rate_value")
            _base_note = (f" · base {_bv*100:.3g}% GoC 5yr (BoC)"
                          if isinstance(_bv, (int, float)) else "")
            ui.label(
                f"Financing applied to this {state['type']}: "
                f"{_fin_preview.get('down_payment_pct', 0)*100:.0f}% down · "
                f"{_fin_preview.get('interest_rate', 0)*100:.3g}% · "
                f"{_fin_preview.get('term_years', 0)}-yr amortization — "
                f"per-type lending rules over a live Bank of Canada base rate{_base_note}"
            ).classes("text-xs text-slate-500")

    if "commercial" in groups:
        with card("Commercial lease", "storefront"):
            with ui.row().classes("w-full gap-3"):
                FIELDS["commercial_rent"] = ui.number("Commercial rent $/yr", value=comm_prefill, prefix="$", format="%.0f",
                                                      validation=_V_NONNEG).classes("flex-1")
                FIELDS["market_cap_rate"] = ui.number("Market cap rate", value=pvpct("market_cap_rate"), suffix="%", format="%.2f",
                                                      validation=_V_PCT).classes("flex-1")
                FIELDS["exit_cap_rate"]   = ui.number("Exit cap rate", value=pvpct("exit_cap_rate"), suffix="%", format="%.2f",
                                                      validation=_V_PCT).classes("flex-1")
            _comm_cap = form_logic.resolved_rent_caption(rec, "commercial_rent", comm_prefill)
            if _comm_cap:
                ui.label(_comm_cap).classes("text-xs text-emerald-700")
            with ui.row().classes("w-full gap-3"):
                FIELDS["commercial_lease_expiry"] = ui.input("Commercial lease expiry", value=pv("commercial_lease_expiry", "")).props("type=date").classes("w-48")
                ui.label("A commercial rent you enter is treated as advertised (actual), "
                         "not a market estimate.").classes("text-xs text-slate-500 self-center")

    if "residential" in groups:
        with card("Residential unit mix", "apartment"):
            with ui.row().classes("w-full gap-3 flex-wrap"):
                for key, lbl in [("bachelor", "Bachelor"), ("one_br", "1 BR"), ("two_br", "2 BR"),
                                 ("three_br", "3 BR"), ("four_br", "4 BR"), ("unknown", "Unknown")]:
                    FIELDS[f"um_{key}"] = ui.number(lbl, value=um.get(key, 0) or 0, format="%d",
                                                    validation=_V_NONNEG).classes("w-28")
            with ui.row().classes("w-full gap-3 items-center"):
                FIELDS["residential_rent"] = ui.number("Residential rent $/yr (override)", value=res_prefill,
                                                       prefix="$", format="%.0f",
                                                       validation=_V_NONNEG).classes("flex-1")
            _res_cap = form_logic.resolved_rent_caption(rec, "residential_rent", res_prefill)
            if _res_cap:
                ui.label(_res_cap).classes("text-xs text-emerald-700")
            ui.label("Leave the residential rent blank to price the unit mix at the city "
                     "market rate from the residential_rents table; enter a figure to use "
                     "it as the in-place residential income instead.").classes(
                "text-xs text-slate-500")

    if "hotel" in groups:
        with card("Hotel operations", "hotel"):
            with ui.row().classes("w-full gap-3"):
                FIELDS["hotel_rooms"]     = ui.number("Rooms", value=pv("hotel_rooms"), format="%d",
                                                      validation=_V_NONNEG).classes("flex-1")
                FIELDS["hotel_adr"]       = ui.number("ADR (avg daily rate)", value=pv("hotel_adr"), prefix="$", format="%.0f",
                                                      validation=_V_NONNEG).classes("flex-1")
                FIELDS["hotel_occupancy"] = ui.number("Occupancy", value=pvpct("hotel_occupancy"), suffix="%", format="%.1f",
                                                      validation=_V_PCT).classes("flex-1")

    if "industrial" in groups:
        with card("Industrial building detail", "factory"):
            with ui.row().classes("w-full gap-3"):
                FIELDS["ind_warehouse_sqft"] = ui.number("Warehouse sq ft", value=pv("ind_warehouse_sqft"), format="%.0f",
                                                         validation=_V_NONNEG).classes("flex-1")
                FIELDS["ind_office_sqft"]    = ui.number("Office sq ft", value=pv("ind_office_sqft"), format="%.0f",
                                                         validation=_V_NONNEG).classes("flex-1")
                FIELDS["ind_yard_sqft"]      = ui.number("Yard sq ft", value=pv("ind_yard_sqft"), format="%.0f",
                                                         validation=_V_NONNEG).classes("flex-1")
            with ui.row().classes("w-full gap-3"):
                FIELDS["ind_dock_doors"]      = ui.number("Dock doors", value=pv("ind_dock_doors"), format="%d",
                                                          validation=_V_NONNEG).classes("flex-1")
                FIELDS["ind_drive_in_doors"]  = ui.number("Drive-in doors", value=pv("ind_drive_in_doors"), format="%d",
                                                          validation=_V_NONNEG).classes("flex-1")
                FIELDS["ind_clear_height_ft"] = ui.number("Clear height (ft)", value=pv("ind_clear_height_ft"), format="%.1f",
                                                          validation=_V_NONNEG).classes("flex-1")
            with ui.row().classes("w-full gap-3"):
                FIELDS["ind_office_rate"] = ui.number("Office rate $/sq ft", value=pv("ind_office_rate"), prefix="$", format="%.2f",
                                                      validation=_V_NONNEG).classes("flex-1")
                FIELDS["ind_yard_rate"]   = ui.number("Yard rate $/sq ft", value=pv("ind_yard_rate"), prefix="$", format="%.2f",
                                                      validation=_V_NONNEG).classes("flex-1")

    # Assumptions & overrides — always shown. Each override is blank by default and
    # falls back to the model's resolver when left empty, so nothing here is required.
    with card("Income & assumptions (overrides)", "tune"):
        with ui.row().classes("w-full gap-3"):
            FIELDS["annual_rent"]     = ui.number("Direct total rent $/yr", value=annual_prefill, prefix="$", format="%.0f",
                                                  validation=_V_NONNEG).classes("flex-1")
            FIELDS["expense_ratio"]   = ui.number("Expense ratio", value=pvpct("expense_ratio"), suffix="%", format="%.1f",
                                                  validation=_V_PCT).classes("flex-1")
            FIELDS["vacancy_rate"]    = ui.number("Vacancy rate", value=pvpct("vacancy_rate"), suffix="%", format="%.1f",
                                                  validation=_V_PCT).classes("flex-1")
            FIELDS["noi_growth_rate"] = ui.number("NOI growth", value=pvpct("noi_growth_rate"), suffix="%", format="%.2f",
                                                  validation=_V_GROWTH).classes("flex-1")
        _annual_cap = form_logic.resolved_rent_caption(rec, "annual_rent", annual_prefill)
        if _annual_cap:
            ui.label(_annual_cap).classes("text-xs text-emerald-700")
        ui.label("Direct total rent overrides every component calculation (use only when you "
                 "have one in-place figure). Blank expense ratio = property-type default; blank "
                 "vacancy = regional resolver; blank NOI growth = house default.").classes(
            "text-xs text-slate-500")
        FIELDS["notes"] = ui.textarea("Notes", value=pv("notes", "")).props("autogrow outlined").classes("w-full mt-1")


def _fval(name, default=None):
    el = FIELDS.get(name)
    if el is None or el.value in ("", None):
        return default
    return el.value


def _pct(name):
    return form_logic.pct_to_fraction(_fval(name))


def save_property_from_form():
    """Build a record from the form and persist it through the production pipeline."""
    # Snapshot every input into a plain values dict and delegate the pure validation +
    # form→PropertyInput mapping to form_logic (unit-tested); app.py keeps only the UI
    # wiring (notify, resolve financing, persist, reset) below.
    values = {name: _fval(name) for name in FIELDS}
    values["property_type"] = state["type"]
    err = form_logic.validate_property_form(values)
    if err:
        ui.notify(err, type="warning")
        return

    ptype = state["type"]
    um = form_logic.unit_mix_from(values)
    share = mixed_use_commercial_gfa_share(ptype, um.floors)
    fin = resolve_financing(float(values.get("asking_price") or 0), ptype, um.total_units,
                            commercial_gfa_share=share)
    prop = form_logic.build_property_input(values, fin)
    address = prop.address

    # Pass the record being edited as `existing` so created_at (and other carried
    # provenance) survives the rebuild — matching the re-analysis path.
    existing = edit_ctx["record"] if edit_ctx["index"] is not None else None
    try:
        record = CommercialPropertyAnalyzer(prop, resolver).to_record(existing=existing)
        analyzed = True
    except Exception:
        record = build_partial_record(prop, existing=existing)  # no market rate yet
        analyzed = False

    # Notes is not part of the analysis pipeline (to_record doesn't emit it), so carry
    # the form value through explicitly. A blank field clears any prior note.
    notes_val = (_fval("notes") or "").strip()
    if notes_val:
        record["notes"] = notes_val

    editing = edit_ctx["index"] is not None
    if editing:
        # Remove the original first (handles an address / listing-date change), then
        # insert the rebuilt record.
        store.delete_property(edit_ctx["index"])
    store.save_property(record)
    city_note = None
    if prop.city and prop.province:
        # Stub the city across every reference store (rates + demographics + distances)
        # so a brand-new city never leaves a silent gap, and tell the user what's blank.
        created = store.ensure_city_reference_data(prop.city, prop.province)
        city_note = form_logic.city_data_needed_message(created)

    reset_form()
    refresh_portfolio()
    if _ui.get("tabs") is not None and _ui.get("t_list") is not None:
        _ui["tabs"].set_value(_ui["t_list"])
    ui.notify(
        f'{"Updated" if editing else "Saved"} "{address}"'
        + (" — full analysis computed." if analyzed
           else " — saved without analysis (no market rate yet).")
        + (f" {city_note}" if city_note else ""),
        type="positive",
    )


def reset_form():
    """Return the form to add mode and clear it — including the property type, which
    resets to blank so a new entry never inherits the last-used type (4.12.1)."""
    edit_ctx.update(index=None, orig_key=None, record=None)
    _draft.clear()
    state["type"] = None
    if _ui.get("type_select") is not None:
        # Suppress on_change so set_value doesn't snapshot the (about-to-be-cleared) form
        # back into _draft; the refresh below rebuilds the blank form.
        _suppress_type_change["on"] = True
        try:
            _ui["type_select"].set_value(None)
        finally:
            _suppress_type_change["on"] = False
    dynamic_form.refresh()


def load_for_edit(index: int):
    """Load an existing property into the type-aware form for in-place editing."""
    props = store.load_properties()
    if index is None or index >= len(props):
        return
    p = props[index]
    edit_ctx.update(index=index,
                    orig_key=(p.get("address", ""), p.get("listing_date", "")),
                    record=p)
    _draft.clear()   # show the record being edited, not a leftover add-mode draft
    state["type"] = p.get("property_type") or state["type"]
    if _ui.get("type_select") is not None:
        # Suppress the select's on_change so it doesn't snapshot the old/blank form into
        # _draft (which would override the record's prefill and blank the edit form).
        _suppress_type_change["on"] = True
        try:
            _ui["type_select"].set_value(state["type"])
        finally:
            _suppress_type_change["on"] = False
    dynamic_form.refresh()
    if _ui.get("tabs") is not None and _ui.get("t_form") is not None:
        # Programmatic jump to the form tab — suppress the tab-change reset so it doesn't
        # wipe the record we just loaded for editing. (handle_event runs this sync handler
        # inline within set_value, so the flag is still set when it fires.)
        _programmatic_tab["on"] = True
        try:
            _ui["tabs"].set_value(_ui["t_form"])
        finally:
            _programmatic_tab["on"] = False


async def confirm_delete(index: int, parent_dialog=None):
    """Confirm, then permanently remove a property from the database."""
    props = store.load_properties()
    if index is None or index >= len(props):
        return
    addr = props[index].get("address") or "this property"
    with ui.dialog() as d, ui.card().classes("p-4 gap-2"):
        ui.label(f'Delete "{addr}"?').classes("font-semibold text-slate-800")
        ui.label("This removes it from the database and cannot be undone.").classes(
            "text-sm text-slate-500")
        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            ui.button("Cancel", on_click=d.close).props("flat")

            def do_delete():
                store.delete_property(index)
                d.close()
                if parent_dialog is not None:
                    parent_dialog.close()
                if edit_ctx["index"] == index:
                    reset_form()
                refresh_portfolio()
                ui.notify(f'Deleted "{addr}".', type="warning")

            ui.button("Delete", icon="delete", on_click=do_delete).props("unelevated color=negative")
    d.open()


def form_tab():
    with ui.card().classes("w-full rounded-xl border border-slate-200 shadow-sm mb-3"):
        with ui.row().classes("items-center gap-4"):
            ui.icon("tune").classes("text-2xl text-blue-600")
            with ui.column().classes("gap-0"):
                ui.label("Type-aware entry").classes("font-semibold text-slate-800")
                ui.label("Change the property type and watch the form reshape — "
                         "no residential fields on a hotel, no dock doors on an apartment block.").classes(
                    "text-xs text-slate-500")

            def on_type(e):
                if _suppress_type_change["on"]:
                    return                # programmatic set during load_for_edit — don't snapshot
                _snapshot_form()          # keep what's already entered across the reshape
                state["type"] = e.value
                dynamic_form.refresh()

            _ui["type_select"] = ui.select(sorted(PROPERTY_TYPES), value=state["type"],
                      label="Property type", on_change=on_type).classes("w-56 ml-auto")

    dynamic_form()
    with ui.row().classes("w-full justify-end items-center gap-3 mt-1"):
        ui.label("Saves to the live database and refreshes the portfolio.").classes(
            "text-xs text-slate-400 mr-auto self-center")
        ui.button("Save property", icon="save",
                  on_click=save_property_from_form).props("unelevated")


# ── realtor.ca URL import (scraper, lazily imported) ───────────────────────────
# The scraper is imported INSIDE the handler so the app/exe starts without Playwright;
# a missing Playwright/Firefox degrades to a friendly message instead of a crash. The
# live fetch opens a real Firefox window and may require solving a CAPTCHA by hand.
def _parse_city_province_simple(addr: str):
    parts = [p.strip() for p in (addr or "").split(",") if p.strip()]
    city = province = ""
    if len(parts) >= 2:
        tail = parts[-1].split()
        if tail and len(tail[-1]) == 2 and tail[-1].isalpha():
            province = tail[-1].upper()
            city = parts[-2]
        else:
            city = parts[-1]
    return city, province


def _import_from_url(url: str):
    """Fetch a realtor.ca listing → partial record. Returns (record, error_msg)."""
    url = (url or "").strip()
    if "realtor.ca" not in url.lower():
        return None, "That doesn't look like a realtor.ca URL."
    try:
        from scraping.realtor_scraper import RealtorScraper, OUTCOME_FOUND
    except Exception as e:
        return None, (f"Scraper unavailable — Playwright isn't installed. "
                      f"Run: python -m playwright install firefox. ({e})")
    try:
        with RealtorScraper() as scraper:
            data = scraper.fetch_listing(url)
    except Exception as e:
        return None, (f"Browser error: {e}. Make sure Firefox is installed "
                      f"(python -m playwright install firefox).")
    if data.outcome != OUTCOME_FOUND or not data.address:
        return None, f"Could not read that listing ({data.outcome}). Nothing saved."
    city, province = _parse_city_province_simple(data.address)
    price = data.asking_price or 0
    fin = load_financing_config()
    prop = PropertyInput(
        address=data.address, mls_number=data.mls_number, status="active",
        original_price=price, asking_price=price,
        total_sq_ft=data.total_sq_ft, property_taxes=data.property_taxes or 0,
        down_payment_pct=fin["down_payment_pct"], interest_rate=fin["interest_rate"],
        term_years=fin["term_years"], hold_years=fin["hold_years"],
        expense_ratio=None, lease_type="Normal", property_type=None,
        listing_date=data.listing_date or date.today().isoformat(),
        city=city, province=province, unit_mix=UnitMix(floors=data.floors or 1),
    )
    record = build_partial_record(prop)
    record["notes"] = (
        f"⚠ Imported from realtor.ca on {date.today().isoformat()}: "
        f"{getattr(data, 'listing_url', url)}. Auto-filled price, MLS, taxes, sq ft, "
        f"listing date. VERIFY/ADD: property type, unit count & type, lease type.")
    return record, None


async def open_url_import():
    with ui.dialog() as dialog, ui.card().classes("w-[560px] max-w-[92vw] p-4 gap-2"):
        ui.label("Add from a realtor.ca URL").classes("font-semibold text-slate-800")
        ui.label("Opens a Firefox window to read the listing — solve any CAPTCHA there if "
                 "prompted. Saves an incomplete record; add property type + units via Edit.").classes(
            "text-xs text-slate-500")
        url_in = ui.input("realtor.ca listing URL").classes("w-full")
        with ui.row().classes("w-full justify-end gap-2 mt-1"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            async def do_fetch():
                note = ui.notification("Opening Firefox and reading the listing…",
                                       spinner=True, timeout=None)
                try:
                    record, err = await asyncio.to_thread(_import_from_url, url_in.value)
                finally:
                    note.dismiss()
                if err:
                    ui.notify(err, type="warning", multi_line=True, timeout=9000)
                    return
                store.save_property(record)
                city_note = None
                if record.get("city") and record.get("province"):
                    created = store.ensure_city_reference_data(record["city"], record["province"])
                    city_note = form_logic.city_data_needed_message(created)
                dialog.close()
                refresh_portfolio()
                ui.notify(f'Imported "{record.get("address")}" — complete it via Edit.'
                          + (f" {city_note}" if city_note else ""),
                          type="positive")

            ui.button("Fetch & add", icon="download", on_click=do_fetch).props("unelevated")
    dialog.open()


# ── Page 3: portfolio-wide reports (reuse the production HTML generators) ──────
# Every generator already exposes render()->str, and the row shapes come from the
# same build_report_row() the CLI uses. Reports that need lever-solving targets
# (investment, negotiation) call solve_targets per property; the rest don't.
def _rows_with_targets() -> list:
    rows = []
    for p in store.load_properties():
        scored  = scorer.score_property(p)
        targets = scorer.solve_targets(p, record_to_prop, CommercialPropertyAnalyzer, resolver)
        rows.append(build_report_row(p, scored, targets))
    return rows


def _rows_simple() -> list:
    return [build_report_row(p, scorer.score_property(p), {})
            for p in store.load_properties()]


REPORTS = [
    ("Investment report",            "assessment",     lambda: prop_rpt.render(_rows_with_targets())),
    ("City opportunity",             "location_city",  lambda: city_rpt.render(ranker.rank(store.load_properties()))),
    ("Deal watchlist",               "star",           lambda: watch_rpt.render(_rows_simple())),
    ("Negotiation targets",          "handshake",      lambda: nego_rpt.render(_rows_with_targets())),
    ("Vacancy sensitivity",          "warning",        lambda: vac_rpt.render(_rows_simple())),
    ("Price-drop alerts",            "trending_down",  lambda: drop_rpt.render(_rows_simple())),
    ("Cap-rate & $/sqft benchmarks", "bar_chart",      lambda: bench_rpt.render(_rows_simple())),
]


async def open_html_report(title: str, build_fn):
    with ui.dialog() as dialog, ui.card().classes("w-[92vw] max-w-[1200px] h-[88vh] p-0 flex flex-col"):
        with ui.row().classes("w-full items-center justify-between px-4 py-2 bg-slate-900 text-white"):
            ui.label(title).classes("font-semibold")
            ui.button(icon="close", on_click=dialog.close).props("flat round color=white")
        body = ui.column().classes("w-full flex-1 p-0 items-center justify-center")
        with body:
            ui.spinner(size="lg")
            ui.label(f"Building “{title}” across the portfolio…").classes("text-slate-500")
    dialog.open()
    try:
        # Off the event loop so the spinner renders; the heavy reports solve targets
        # for every property, which can take a few seconds at full scale.
        html = await asyncio.to_thread(build_fn)
        key  = re.sub(r"\W+", "_", title).strip("_").lower()
        out  = REPORTS_DIR / f"report_{key}.html"
        out.write_text(html, encoding="utf-8")
        body.clear()
        with body:
            ui.element("iframe").props(f"src=/reports/report_{key}.html?t={time.time_ns()}").style(
                "width:100%;height:100%;border:0;").classes("w-full h-full")
    except Exception as ex:
        body.clear()
        with body:
            ui.icon("info").classes("text-4xl text-amber-500")
            ui.label("Couldn't build this report").classes("font-medium")
            ui.label(str(ex)).classes("text-xs text-slate-500 max-w-[600px] text-center")


def reports_tab():
    with ui.card().classes("w-full rounded-xl border border-slate-200 shadow-sm mb-3"):
        with ui.row().classes("items-center gap-4"):
            ui.icon("summarize").classes("text-2xl text-blue-600")
            with ui.column().classes("gap-0"):
                ui.label("Portfolio reports").classes("font-semibold text-slate-800")
                ui.label("Each opens the existing HTML report — the same ones the CLI "
                         "launches in a browser — rendered inside the app.").classes(
                    "text-xs text-slate-500")
    with ui.row().classes("w-full flex-wrap gap-3"):
        for title, icon, build in REPORTS:
            ui.button(title, icon=icon,
                      on_click=lambda t=title, b=build: open_html_report(t, b)
                      ).props("outline no-caps").classes("grow-0")


# ── Page 4: rate editing (commercial + residential) ───────────────────────────
RATE_COMM_TYPES = ["Office", "Retail", "Industrial", "Mixed-Use"]
RATE_RES_FIELDS = [("bachelor", "Bachelor"), ("one_br", "1 BR"), ("two_br", "2 BR"),
                   ("three_br", "3 BR"), ("four_br", "4 BR")]
_NEW_CITY = "➕ Add a new city…"


def _rates_grid_editor(kind):
    """Editable TABLE of every city's rates for one kind ('commercial' or 'residential'):
    all cities as rows, each rate type/unit an editable column. Save persists only the
    cities whose cells changed and re-analyzes them; Add city appends a new one."""
    if kind == "commercial":
        columns = [(t, f"{t} ($/sqft/yr)") for t in RATE_COMM_TYPES]
        field_key, loader = "types", store.load_commercial_rate_rows
        hint = "Commercial rents are $/sq ft/yr. Edit a cell and click Save changes."
    else:
        columns = [(k, f"{lbl} ($/mo)") for k, lbl in RATE_RES_FIELDS]
        field_key, loader = "units", store.load_residential_rate_rows
        hint = ("Residential rents are $/mo. The “unknown” unit rate is auto-set to the "
                "average of the entered rents on save.")
    col_keys = [c for c, _ in columns]
    state = {"snap": form_logic.rate_rows_to_grid(loader(), field_key, col_keys)}

    def _save_one(city, prov, rates):
        if kind == "commercial":
            store.save_commercial_city(city, prov, rates)
        else:
            store.save_residential_city(city, prov, form_logic.residential_with_unknown(rates))

    def _reanalyze(keys):
        if not keys:
            return 0
        return reanalyze_properties(
            store, resolver, CommercialPropertyAnalyzer,
            predicate=lambda p: ((p.get("city", "") or "").strip().lower(),
                                 (p.get("province", "") or "").strip().upper()) in keys)["updated"]

    def _reload():
        state["snap"] = form_logic.rate_rows_to_grid(loader(), field_key, col_keys)
        grid.options["rowData"] = state["snap"]
        grid.update()

    ui.label(hint).classes("text-xs text-slate-500 mb-1")
    coldefs = [
        {"headerName": "City", "field": "city", "pinned": "left", "width": 160, "filter": True},
        {"headerName": "Prov", "field": "province", "width": 80},
    ] + [{"headerName": lbl, "field": c, "editable": True, "type": "numericColumn",
          "valueFormatter": "value==null||value===''?'—':'$'+Number(value).toLocaleString()"}
         for c, lbl in columns]
    grid = ui.aggrid({
        "columnDefs": coldefs,
        "rowData": state["snap"],
        "defaultColDef": {"sortable": True, "resizable": True},
        "pagination": True, "paginationPageSize": 25,
        "stopEditingWhenCellsLoseFocus": True,
        "rowSelection": "single",
    }).classes("h-[56vh]")
    # Register this grid's reload so a delete from either sub-tab refreshes both grids
    # (a delete removes the city from both the commercial and residential tables).
    _ui.setdefault("rates_reloads", []).append(_reload)

    async def save_changes():
        rows = await grid.get_client_data()
        changed = form_logic.changed_rate_rows(state["snap"], rows, col_keys)
        if not changed:
            ui.notify("No rate changes to save.", type="info"); return
        keys, saved = set(), 0
        for r in changed:
            city = (r.get("city") or "").strip(); prov = (r.get("province") or "").strip().upper()
            if not city or not prov:
                continue
            _save_one(city, prov, form_logic.grid_row_to_rates(r, col_keys))
            keys.add((city.lower(), prov)); saved += 1
        reanalyzed = _reanalyze(keys)
        _reload(); refresh_portfolio()
        ui.notify(f"Saved {saved} city rate set(s) — re-analyzed {reanalyzed} "
                  f"propert{'y' if reanalyzed == 1 else 'ies'}.", type="positive")

    def add_city():
        with ui.dialog() as d, ui.card().classes("p-4 gap-2 w-[560px] max-w-full"):
            ui.label(f"Add a city — {kind} rates").classes("font-semibold text-slate-800")
            with ui.row().classes("w-full gap-3"):
                ci = ui.input("City").classes("w-48")
                pi = ui.select(list(PROVINCE_CODES), label="Province",
                               with_input=True, clearable=True).classes("w-28")
            inputs = {}
            with ui.row().classes("w-full gap-3 flex-wrap"):
                for c, lbl in columns:
                    inputs[c] = ui.number(lbl, prefix="$",
                                          format="%.2f" if kind == "commercial" else "%.0f").classes("w-36")

            def do_add():
                city = (ci.value or "").strip(); prov = (pi.value or "").strip().upper()
                if not city or not prov:
                    ui.notify("City and province are required.", type="warning"); return
                rates = {c: float(inputs[c].value) for c in col_keys if inputs[c].value not in (None, "")}
                _save_one(city, prov, rates)
                n = _reanalyze({(city.lower(), prov)})
                d.close(); _reload(); refresh_portfolio()
                ui.notify(f"Added {city}, {prov} — re-analyzed {n} propert{'y' if n == 1 else 'ies'}.",
                          type="positive")

            with ui.row().classes("w-full justify-end gap-2 mt-1"):
                ui.button("Cancel", on_click=d.close).props("flat")
                ui.button("Add", icon="add", on_click=do_add).props("unelevated")
        d.open()

    async def delete_city():
        rows = await grid.get_selected_rows()
        if not rows:
            ui.notify("Select a city row first (click it), then Delete.", type="warning"); return
        row = rows[0]
        city = (row.get("city") or "").strip(); prov = (row.get("province") or "").strip().upper()
        if not city:
            ui.notify("That row has no city.", type="warning"); return
        linked = form_logic.properties_for_city(store.load_properties(), city, prov)
        n_linked = len(linked)
        with ui.dialog() as d, ui.card().classes("p-4 gap-2 w-[560px] max-w-full"):
            ui.label(f"Delete all rates for {city}, {prov}?").classes("font-semibold text-slate-800")
            if linked:
                ui.label(f"{n_linked} propert{'y' if n_linked == 1 else 'ies'} "
                         f"use{'s' if n_linked == 1 else ''} this city — "
                         f"{'it keeps' if n_linked == 1 else 'they keep'} the last report but "
                         f"lose{'s' if n_linked == 1 else ''} the market rate until you re-add "
                         f"rates or re-analyze:").classes("text-sm text-slate-600")
                with ui.column().classes("gap-0 max-h-40 overflow-auto w-full"):
                    for p in linked[:12]:
                        ui.label("• " + (p.get("address") or "—")).classes("text-xs text-slate-500")
                    if n_linked > 12:
                        ui.label(f"…and {n_linked - 12} more").classes("text-xs text-slate-400")
            else:
                ui.label("No properties are linked to this city.").classes("text-sm text-slate-500")
            ui.label("Removes the city from both the commercial and residential rate "
                     "tables. This cannot be undone — linked properties are listed in the "
                     "City data → Orphans tab for resolution.").classes("text-xs text-slate-500")
            with ui.row().classes("w-full justify-end gap-2 mt-1"):
                ui.button("Cancel", on_click=d.close).props("flat")

                def do_delete():
                    n = store.delete_city_rates(city, prov)
                    d.close()
                    for fn in _ui.get("rates_reloads", []):
                        fn()
                    refresh_portfolio()
                    _refresh_city_views()
                    ui.notify(
                        f"Deleted {city}, {prov} rates ({n} row(s)). "
                        + (f"{n_linked} linked propert{'y' if n_linked == 1 else 'ies'} — "
                           "re-add rates or re-analyze to refresh." if n_linked
                           else "No linked properties."),
                        type="warning")

                ui.button("Delete city", icon="delete", on_click=do_delete).props("unelevated color=negative")
        d.open()

    with ui.row().classes("w-full items-center gap-2 mt-2"):
        ui.button("Add city", icon="add_location_alt", on_click=add_city).props("outline no-caps dense")
        ui.button("Delete city", icon="delete", on_click=delete_city).props("outline no-caps dense color=negative")
        ui.space()
        ui.button("Save changes", icon="save", on_click=save_changes).props("unelevated no-caps")


def commercial_rates_editor():
    _rates_grid_editor("commercial")


def residential_rates_editor():
    _rates_grid_editor("residential")


def rates_tab():
    _ui["rates_reloads"] = []   # fresh registry each render (both sub-grids re-register)
    with ui.card().classes("w-full rounded-xl border border-slate-200 shadow-sm mb-3"):
        with ui.row().classes("items-center gap-4"):
            ui.icon("payments").classes("text-2xl text-blue-600")
            with ui.column().classes("gap-0"):
                ui.label("Market rent rates").classes("font-semibold text-slate-800")
                ui.label("Edit the commercial ($/sq ft/yr) and residential ($/mo) rents "
                         "stored in the database. Saving updates the rate tables directly.").classes(
                    "text-xs text-slate-500")
    with ui.tabs().classes("w-full") as sub:
        s_comm = ui.tab("Commercial")
        s_res  = ui.tab("Residential")
    with ui.tab_panels(sub, value=s_comm).classes("w-full bg-transparent"):
        with ui.tab_panel(s_comm):
            commercial_rates_editor()
        with ui.tab_panel(s_res):
            residential_rates_editor()


# Editable scalar fields per conventional per-type block and per CMHC sub-block.
# (key, label, kind) — kind drives %/ratio/int conversion on load + save.
_FIN_TYPE_FIELDS = [
    ("max_ltv", "Max LTV", "pct"),
    ("rate_low", "Rate low", "pct"),
    ("rate_high", "Rate high", "pct"),
    ("amort_years", "Amort (yrs)", "int"),
    ("dscr_floor", "DSCR floor", "ratio"),
    ("fixed_expense_fraction", "Fixed exp frac", "pct"),
]
_FIN_CMHC_FIELDS = [f for f in _FIN_TYPE_FIELDS if f[0] != "fixed_expense_fraction"]


def _financing_types_card():
    """Edit every per-asset-class lending rule (spread/LTV/amortization/DSCR), the
    CMHC Standard/Select sub-blocks, and the base-rate anchor — plus a raw-JSON
    editor for the complete config. Persists to the DB `config` table via save_raw."""
    raw = get_raw_config()
    ptypes = raw.get("property_types") or {}
    base = (raw.get("rate_base") or {}).get("value") or 0.0
    num_inputs = []   # (container_dict, key, kind, widget)

    def _add(container, key, label, kind):
        cur = container.get(key)
        has = isinstance(cur, (int, float)) and not isinstance(cur, bool)
        if kind == "pct":
            w = ui.number(label, value=(round(cur * 100, 4) if has else None),
                          suffix="%", format="%.4g").props("dense").classes("w-28")
        elif kind == "int":
            w = ui.number(label, value=(int(cur) if has else None),
                          format="%d").props("dense").classes("w-28")
        else:  # ratio
            w = ui.number(label, value=(round(cur, 4) if has else None),
                          format="%.4g").props("dense").classes("w-28")
        num_inputs.append((container, key, kind, w))

    with ui.card().classes("w-full rounded-xl border border-slate-200 shadow-sm mt-4"):
        with ui.row().classes("items-center gap-2 mb-1"):
            ui.icon("tune").classes("text-blue-600")
            ui.label("Per-asset-class lending rules").classes("font-semibold text-slate-800")
        ui.label("Each rate = the live base + this class's credit spread. Stored in the "
                 "database; edit here and Re-analyze to apply. Spreads are estimates — "
                 "only the base rate is sourced.").classes("text-xs text-slate-500 mb-2")

        # Base-rate anchor (re-bases the live shift).
        rb = raw.get("rate_base")
        asof_input = None
        if isinstance(rb, dict):
            with ui.row().classes("w-full gap-3 items-center mb-1"):
                _add(rb, "value", "Base anchor (GoC 5yr)", "pct")
                asof_input = ui.input("Anchor as-of", value=rb.get("as_of") or "").props("dense").classes("w-40")
            ui.label("The anchor the spreads were authored against; the live feed shifts "
                     "every rate by (fetched − anchor).").classes("text-xs text-slate-400 mb-1")

        for tkey, block in ptypes.items():
            if not isinstance(block, dict):
                continue
            if "alias" in block:
                ui.label(f"{tkey} → alias of {block['alias']} (edit that class)").classes(
                    "text-xs text-slate-400")
                continue
            with ui.expansion(tkey.replace("_", " ")).classes("w-full"):
                with ui.row().classes("w-full gap-3 flex-wrap items-center"):
                    for key, label, kind in _FIN_TYPE_FIELDS:
                        if key in block:
                            _add(block, key, label, kind)
                if isinstance(block.get("rate_low"), (int, float)) and isinstance(block.get("rate_high"), (int, float)):
                    ui.label(f"≈ {(block['rate_low'] - base) * 10000:.0f}–"
                             f"{(block['rate_high'] - base) * 10000:.0f} bps over the base rate"
                             ).classes("text-xs text-slate-400")
                cmhc = block.get("cmhc")
                if isinstance(cmhc, dict):
                    for sub in ("mli_standard", "mli_select"):
                        sb = cmhc.get(sub)
                        if isinstance(sb, dict):
                            ui.label(f"CMHC · {sub.replace('_', ' ')}").classes(
                                "text-xs font-semibold text-slate-500 mt-1")
                            with ui.row().classes("w-full gap-3 flex-wrap items-center"):
                                for key, label, kind in _FIN_CMHC_FIELDS:
                                    if key in sb:
                                        _add(sb, key, label, kind)

        def save_types():
            try:
                for container, key, kind, w in num_inputs:
                    cv = form_logic.coerce_financing_field(w.value, kind)
                    if cv is form_logic.SKIP:   # blank pct/int → leave the stored value
                        continue
                    container[key] = cv
                if asof_input is not None and isinstance(raw.get("rate_base"), dict):
                    raw["rate_base"]["as_of"] = (asof_input.value or "").strip()
                save_raw(raw)
                ui.notify("Saved per-asset-class lending rules — Re-analyze to apply.",
                          type="positive")
            except Exception as e:
                ui.notify(f"Could not save: {e}", type="warning")

        ui.button("Save lending rules", icon="save", on_click=save_types).props("unelevated").classes("mt-2")

        # Advanced: the complete config as raw JSON (covers nested CMHC point-tiers,
        # conditional rules, aliases, source notes — genuinely every value).
        with ui.expansion("Advanced — full financing config (raw JSON)").classes("w-full mt-2"):
            import json as _json
            ta = ui.textarea(value=_json.dumps(raw, indent=2, ensure_ascii=False)).props(
                "outlined input-class=font-mono input-style=height:320px").classes("w-full")

            def save_json():
                try:
                    parsed = _json.loads(ta.value)
                except Exception as e:
                    ui.notify(f"Not valid JSON: {e}", type="warning"); return
                try:
                    save_raw(parsed)
                    ui.notify("Saved full financing config — Re-analyze to apply.", type="positive")
                except Exception as e:
                    ui.notify(f"Rejected: {e}", type="warning")

            ui.button("Save raw JSON", icon="save", on_click=save_json).props("outline no-caps dense").classes("mt-1")


# ── Page 5: global settings (financing defaults + scoring formula) ─────────────
def settings_tab():
    # Financing defaults
    with ui.card().classes("w-full rounded-xl border border-slate-200 shadow-sm mb-4"):
        with ui.row().classes("items-center gap-2 mb-1"):
            ui.icon("account_balance").classes("text-blue-600")
            ui.label("Global financing defaults").classes("font-semibold text-slate-800")
        ui.label("House-wide — applied to every property, not entered per listing. "
                 "Re-analyze (CLI 'r') to push changes into stored results.").classes(
            "text-xs text-slate-500 mb-2")
        cfg = load_financing_config()
        with ui.row().classes("w-full gap-3"):
            dp = ui.number("Down payment %", value=cfg["down_payment_pct"] * 100, suffix="%", format="%.2f").classes("w-40")
            ir = ui.number("Interest rate %", value=cfg["interest_rate"] * 100, suffix="%", format="%.2f").classes("w-40")
            tm = ui.number("Amortization (yrs)", value=cfg["term_years"], format="%d").classes("w-40")
            hy = ui.number("Hold period (yrs)", value=cfg["hold_years"], format="%d").classes("w-40")

        def save_fin():
            try:
                d = float(dp.value); d = d / 100 if d > 1 else d
                r = float(ir.value); r = r / 100 if r > 1 else r
                if not (0 <= d < 1) or r < 0:
                    ui.notify("Down payment 0–100%, rate ≥ 0.", type="warning"); return
                save_financing_config(round(d, 4), round(r, 4), int(tm.value), int(hy.value))
                ui.notify("Saved global financing defaults — run “Re-analyze all” "
                          "(Portfolio tab) to apply it to stored results.", type="positive")
            except (TypeError, ValueError):
                ui.notify("Please enter valid numbers.", type="warning")

        ui.button("Save financing", icon="save", on_click=save_fin).props("unelevated")

        ui.separator().classes("my-2")

        @ui.refreshable
        def _base_rate_row():
            info = base_rate_info()
            fetched, anchor = info.get("fetched"), (info.get("anchor") or 0)
            adj = info.get("adjustment") or 0
            with ui.row().classes("items-center gap-2"):
                ui.icon("sync" if info.get("live") else "sync_problem").classes(
                    "text-emerald-600" if info.get("live") else "text-amber-600")
                if fetched is not None:
                    txt = (f"Base rate (sourced): {info.get('series_label')} = {fetched*100:.3g}% "
                           f"— {info.get('source')}, as of {info.get('fetched_as_of')}.")
                else:
                    txt = (f"Base rate anchor {anchor*100:.3g}% — no live feed yet "
                           f"(using config default; click Refresh).")
                ui.label(txt).classes("text-xs text-slate-600")
            ui.label(
                f"Every per-type rate = this sourced base + an asset-class credit spread. "
                f"Live shift vs the authored anchor ({anchor*100:.3g}%): {adj*100:+.2f}%."
            ).classes("text-xs text-slate-400")

        _base_rate_row()

        async def refresh_rates():
            from analysis.rate_feed import refresh_interest_rates
            changed, reason = await asyncio.to_thread(
                lambda: refresh_interest_rates(force=True, timeout=30, store=store))
            financing_config.reload_rate_feed()
            _base_rate_row.refresh()
            ui.notify(f"Base rate {reason}" + ("  — Re-analyze to apply." if changed else ""),
                      type="positive" if changed else "warning")

        ui.button("Refresh base rate (Bank of Canada)", icon="cloud_download",
                  on_click=refresh_rates).props("outline no-caps dense").classes("mt-1")

    # Per-asset-class lending rules (spreads / LTV / amortization / DSCR) + raw editor
    _financing_types_card()

    # Scoring formula weights
    with ui.card().classes("w-full rounded-xl border border-slate-200 shadow-sm"):
        with ui.row().classes("items-center gap-2 mb-1"):
            ui.icon("tune").classes("text-blue-600")
            ui.label("Scoring formula — weights & thresholds").classes("font-semibold text-slate-800")
        scfg = scorer.load_config()
        weights = dict(scfg.get("weights", {}))
        thresholds = {k: list(v) for k, v in scfg.get("thresholds", {}).items()}
        total_lbl = ui.label().classes("text-xs text-slate-500 mb-2")

        def _update_total():
            s = sum((ins["w"].value or 0) for ins in w_inputs.values()) / 100
            total_lbl.set_text(f"Weights sum to {s:.2f} (scores are auto-normalized; set 0 to disable).")

        w_inputs = {}
        with ui.grid(columns=4).classes("w-full gap-x-4 gap-y-1 items-center"):
            ui.label("Component").classes("text-xs font-semibold text-slate-500")
            ui.label("Weight %").classes("text-xs font-semibold text-slate-500")
            ui.label("Floor (score 0)").classes("text-xs font-semibold text-slate-500")
            ui.label("Ceiling (score 10)").classes("text-xs font-semibold text-slate-500")
            for k in weights:
                lo, hi = thresholds.get(k, [0, 1])
                ui.label(k).classes("text-sm text-slate-700")
                w_inputs[k] = {
                    "w":  ui.number(value=round(weights[k] * 100, 1), format="%.1f", on_change=_update_total).props("dense"),
                    "lo": ui.number(value=lo, format="%.2f").props("dense"),
                    "hi": ui.number(value=hi, format="%.2f").props("dense"),
                }
        _update_total()

        def save_scoring():
            try:
                for k, ins in w_inputs.items():
                    weights[k] = round((ins["w"].value or 0) / 100, 4)
                    thresholds[k] = [float(ins["lo"].value), float(ins["hi"].value)]
                scfg["weights"] = weights
                scfg["thresholds"] = thresholds
                scorer.save_config(scfg)
                ui.notify("Saved scoring weights & thresholds.", type="positive")
            except (TypeError, ValueError):
                ui.notify("Please enter valid numbers.", type="warning")

        ui.button("Save scoring", icon="save", on_click=save_scoring).props("unelevated").classes("mt-2")

    # City-opportunity weights (the city ranker)
    with ui.card().classes("w-full rounded-xl border border-slate-200 shadow-sm mt-4"):
        with ui.row().classes("items-center gap-2 mb-1"):
            ui.icon("location_city").classes("text-blue-600")
            ui.label("City opportunity — signal weights & model knobs").classes("font-semibold text-slate-800")
        ui.label("Relative quality weights for the city ranker (auto-normalized). Opportunity "
                 "blends quality with market depth via the knobs below.").classes(
            "text-xs text-slate-500 mb-2")
        ccfg = scorer.load_config()
        cweights = dict(ccfg.get("city_score_weights", {}))
        cw_inputs = {}
        with ui.row().classes("w-full gap-2 flex-wrap"):
            for k in cweights:
                cw_inputs[k] = ui.number(k, value=round(cweights[k] * 100, 1), suffix="%",
                                         format="%.1f").props("dense").classes("w-32")
        ui.label("Model knobs").classes("text-xs font-semibold text-slate-500 mt-2")
        with ui.row().classes("w-full gap-3"):
            k_exp = ui.number("Depth weight (0–1)", value=ccfg.get("opportunity_depth_exp", 0.4), format="%.2f").classes("w-40")
            k_ref = ui.number("Depth ref (# active)", value=ccfg.get("opportunity_depth_ref", 50), format="%.0f").classes("w-40")
            k_cap = ui.number("Outlier cap ceiling", value=ccfg.get("outlier_max_cap_rate", 12.0), suffix="%", format="%.1f").classes("w-40")
            k_coc = ui.number("Outlier CoCR ceiling", value=ccfg.get("outlier_max_coc", 25.0), suffix="%", format="%.1f").classes("w-40")

        def save_city_scoring():
            try:
                cfg = scorer.load_config()
                cfg["city_score_weights"] = {k: round((i.value or 0) / 100, 4) for k, i in cw_inputs.items()}
                if k_exp.value is not None and 0 <= k_exp.value < 1:
                    cfg["opportunity_depth_exp"] = round(k_exp.value, 3)
                if k_ref.value and k_ref.value > 1:
                    cfg["opportunity_depth_ref"] = round(k_ref.value, 2)
                cfg["outlier_max_cap_rate"] = round(float(k_cap.value), 2)
                cfg["outlier_max_coc"] = round(float(k_coc.value), 2)
                scorer.save_config(cfg)
                ui.notify("Saved city opportunity weights & knobs.", type="positive")
            except (TypeError, ValueError):
                ui.notify("Please enter valid numbers.", type="warning")

        ui.button("Save city weights", icon="save", on_click=save_city_scoring).props("unelevated").classes("mt-2")


# ── Page 6: city reference data (distances + demographics) ─────────────────────
def _refresh_city_views():
    """Re-query the City-data Status dashboard and the Orphans report (whichever are mounted)
    after a delete / edit, so both reflect the change without a reload."""
    for key in ("city_status_refresh", "orphans_refresh"):
        fn = _ui.get(key)
        if fn:
            fn()


def _city_delete_dialog(kind, city, on_confirm):
    """Confirm deleting a city's reference data (`kind`: 'distance' / 'demographics'). Lists
    the properties linked to that city and warns that forcing the delete orphans them (they
    then appear in the Orphans tab for resolution). `on_confirm()` does the actual delete."""
    linked = form_logic.properties_for_city_name(store.load_properties(), city)
    n = len(linked)
    with ui.dialog() as d, ui.card().classes("p-4 gap-2 w-[560px] max-w-full"):
        ui.label(f"Delete {kind} for {city}?").classes("font-semibold text-slate-800")
        if linked:
            ui.label(f"{n} propert{'y' if n == 1 else 'ies'} "
                     f"{'is' if n == 1 else 'are'} linked to this city. Deleting its {kind} leaves "
                     f"{'it' if n == 1 else 'them'} orphaned (missing data) until you re-add it — "
                     f"the Orphans tab lists them for resolution:").classes("text-sm text-slate-600")
            with ui.column().classes("gap-0 max-h-40 overflow-auto w-full"):
                for p in linked[:12]:
                    ui.label("• " + (p.get("address") or "—")).classes("text-xs text-slate-500")
                if n > 12:
                    ui.label(f"…and {n - 12} more").classes("text-xs text-slate-400")
        else:
            ui.label("No properties are linked to this city.").classes("text-sm text-slate-500")
        ui.label("This cannot be undone.").classes("text-xs text-slate-500")
        with ui.row().classes("w-full justify-end gap-2 mt-1"):
            ui.button("Cancel", on_click=d.close).props("flat")

            def _go():
                d.close()
                on_confirm()

            ui.button("Delete anyway" if linked else "Delete city",
                      icon="delete", on_click=_go).props("unelevated color=negative")
    d.open()


def _distances_editor():
    raw = {"d": store.load_city_distances()}   # {City(display): {distance_km, nearest_centre}}
    sel = {"val": _NEW_CITY}

    @ui.refreshable
    def form():
        row = raw["d"].get(sel["val"]) if sel["val"] != _NEW_CITY else None
        f = {}
        with ui.row().classes("w-full gap-3"):
            f["city"] = ui.input("City", value=(sel["val"] if row else "")).classes("w-48")
            if row:
                f["city"].props("readonly")
            f["centre"] = ui.input("Nearest regional centre",
                                    value=(row or {}).get("nearest_centre", "")).classes("w-56")
            f["km"] = ui.number("Distance (km)", value=(row or {}).get("distance_km"),
                                format="%.0f").classes("w-40")

        def save():
            city = (f["city"].value or "").strip().title()
            if not city:
                ui.notify("City is required.", type="warning"); return
            store.save_city_distance(city, {"distance_km": f["km"].value,
                                            "nearest_centre": (f["centre"].value or "").strip()})
            raw["d"] = store.load_city_distances()
            sel["val"] = city
            city_select.set_options([_NEW_CITY] + sorted(raw["d"], key=str.lower), value=city)
            form.refresh()
            ui.notify(f"Saved distance for {city}.", type="positive")

        def delete():
            target = sel["val"]

            def _do():
                store.delete_city_distance(target)
                raw["d"] = store.load_city_distances()
                sel["val"] = _NEW_CITY
                city_select.set_options([_NEW_CITY] + sorted(raw["d"], key=str.lower), value=_NEW_CITY)
                form.refresh()
                _refresh_city_views()
                ui.notify(f"Deleted distance for {target}.", type="warning")

            _city_delete_dialog("distance", target, _do)

        with ui.row().classes("items-center gap-2 mt-1"):
            ui.button("Save distance", icon="save", on_click=save).props("unelevated")
            if row:
                ui.button("Delete city", icon="delete", on_click=delete).props("flat color=negative")

    def on_city(e):
        sel["val"] = e.value
        form.refresh()

    city_select = ui.select([_NEW_CITY] + sorted(raw["d"], key=str.lower), value=_NEW_CITY,
                            label="City to edit", on_change=on_city).classes("w-72 mb-3")
    form()


def _demographics_editor():
    raw = {"d": store.load_city_demographics()}   # {city_lower: {population, ...}}
    sel = {"val": _NEW_CITY}

    @ui.refreshable
    def form():
        key = sel["val"].lower() if sel["val"] != _NEW_CITY else None
        row = raw["d"].get(key) if key else None
        f = {}
        with ui.row().classes("w-full gap-3"):
            f["city"] = ui.input("City", value=(sel["val"] if row else "")).classes("w-48")
            if row:
                f["city"].props("readonly")
            f["pop"] = ui.number("Population (2021)", value=(row or {}).get("population"),
                                 format="%.0f").classes("w-44")
            f["pop16"] = ui.number("Population (2016)", value=(row or {}).get("population_2016"),
                                   format="%.0f").classes("w-44")
        with ui.row().classes("w-full gap-3"):
            f["source"] = ui.input("Source", value=(row or {}).get("source", "")).classes("flex-1")
        ui.label("Annualised growth is computed from the two census populations.").classes(
            "text-xs text-slate-500")

        def save():
            city = (f["city"].value or "").strip().title()
            if not city:
                ui.notify("City is required.", type="warning"); return
            pop = int(f["pop"].value) if f["pop"].value else 0
            pop16 = int(f["pop16"].value) if f["pop16"].value else 0
            growth = round(((pop / pop16) ** (1 / 5) - 1) * 100, 2) if pop and pop16 else (row or {}).get("growth_pct_annual")
            store.save_city_demographics(city, {
                "population": pop, "population_2016": pop16,
                "growth_pct_annual": growth,
                "source": (f["source"].value or "").strip() or "Stats Canada 2021 Census",
                "notes": (row or {}).get("notes", ""),
            })
            raw["d"] = store.load_city_demographics()
            sel["val"] = city
            city_select.set_options([_NEW_CITY] + sorted((k.title() for k in raw["d"]), key=str.lower), value=city)
            form.refresh()
            ui.notify(f"Saved demographics for {city} (growth {growth:+.2f}%/yr)."
                      if growth is not None else f"Saved demographics for {city}.", type="positive")

        def delete():
            target = sel["val"]

            def _do():
                store.delete_city_demographics(target)
                raw["d"] = store.load_city_demographics()
                sel["val"] = _NEW_CITY
                city_select.set_options(
                    [_NEW_CITY] + sorted((k.title() for k in raw["d"]), key=str.lower), value=_NEW_CITY)
                form.refresh()
                _refresh_city_views()
                ui.notify(f"Deleted demographics for {target}.", type="warning")

            _city_delete_dialog("demographics", target, _do)

        with ui.row().classes("items-center gap-2 mt-1"):
            ui.button("Save demographics", icon="save", on_click=save).props("unelevated")
            if row:
                ui.button("Delete city", icon="delete", on_click=delete).props("flat color=negative")

    def on_city(e):
        sel["val"] = e.value
        form.refresh()

    city_select = ui.select([_NEW_CITY] + sorted((k.title() for k in raw["d"]), key=str.lower),
                            value=_NEW_CITY, label="City to edit", on_change=on_city).classes("w-72 mb-3")
    form()


def _city_status_dashboard():
    """At-a-glance completeness of every city's reference data: which cities are missing
    commercial/residential rates, a distance, or demographics, and how many properties
    depend on each (4.12.7)."""
    rows = form_logic.city_data_status(
        store.load_properties(),
        store.load_commercial_rate_rows(),
        store.load_residential_rate_rows(),
        store.load_city_demographics(),
        store.load_city_distances(),
    )
    n_cities = len(rows)
    n_incomplete = sum(1 for r in rows if r["missing"])
    ui.label(f"{n_cities} cit{'y' if n_cities == 1 else 'ies'} · "
             f"{n_incomplete} missing some data").classes("text-sm font-medium text-slate-700 mb-1")
    ui.label("✓ = on file, ✗ = needs data. Fill gaps on the Rates tab (rents) and the "
             "Distances / Demographics sub-tabs above.").classes("text-xs text-slate-500 mb-2")

    def _mark(b):
        return "✓" if b else "✗"

    grid_rows = [{
        "city": r["city"], "province": r["province"], "n_props": r["n_props"],
        "commercial": _mark(r["has_commercial"]), "residential": _mark(r["has_residential"]),
        "distance": _mark(r["has_distance"]), "demographics": _mark(r["has_demographics"]),
        "missing": ", ".join(r["missing"]) or "—",
    } for r in rows]
    ui.aggrid({
        "columnDefs": [
            {"headerName": "City", "field": "city", "pinned": "left", "width": 150, "filter": True},
            {"headerName": "Prov", "field": "province", "width": 80},
            {"headerName": "# Props", "field": "n_props", "width": 100, "type": "numericColumn"},
            {"headerName": "Commercial", "field": "commercial", "width": 120},
            {"headerName": "Residential", "field": "residential", "width": 120},
            {"headerName": "Distance", "field": "distance", "width": 110},
            {"headerName": "Demographics", "field": "demographics", "width": 130},
            {"headerName": "Missing", "field": "missing", "flex": 1, "filter": True},
        ],
        "rowData": grid_rows,
        "defaultColDef": {"sortable": True, "resizable": True},
        "pagination": True, "paginationPageSize": 25,
    }).classes("h-[56vh]")


def _orphans_report():
    """Resolution worklist of orphaned properties — those whose city is missing reference
    data (e.g. left behind when a city's rates / distance / demographics were deleted while
    properties still point at it). Computed live, so an orphan clears when its data is
    re-added or the property's city is corrected."""
    rows = form_logic.orphaned_properties(
        store.load_properties(),
        store.load_commercial_rate_rows(),
        store.load_residential_rate_rows(),
        store.load_city_demographics(),
        store.load_city_distances(),
    )
    n = len(rows)
    if n == 0:
        ui.label("No orphaned properties — every property's city has its reference data on "
                 "file.").classes("text-sm text-slate-500")
        return
    ui.label(f"{n} orphaned propert{'y' if n == 1 else 'ies'} — each points at a city that is "
             "missing some reference data.").classes("text-sm font-medium text-amber-600 mb-1")
    ui.label("Resolve by re-adding the data (Rates / Distances / Demographics) or editing the "
             "property's city on Add / Edit property.").classes("text-xs text-slate-500 mb-2")
    grid_rows = [{"address": r["address"], "city": r["city"], "province": r["province"],
                  "missing": ", ".join(r["missing"])} for r in rows]
    ui.aggrid({
        "columnDefs": [
            {"headerName": "Address", "field": "address", "pinned": "left", "width": 200, "filter": True},
            {"headerName": "City", "field": "city", "width": 140, "filter": True},
            {"headerName": "Prov", "field": "province", "width": 80},
            {"headerName": "Missing data", "field": "missing", "flex": 1, "filter": True},
        ],
        "rowData": grid_rows,
        "defaultColDef": {"sortable": True, "resizable": True},
        "pagination": True, "paginationPageSize": 25,
    }).classes("h-[56vh]")


def city_data_tab():
    with ui.card().classes("w-full rounded-xl border border-slate-200 shadow-sm mb-3"):
        with ui.row().classes("items-center gap-4"):
            ui.icon("public").classes("text-2xl text-blue-600")
            with ui.column().classes("gap-0"):
                ui.label("City reference data").classes("font-semibold text-slate-800")
                ui.label("Distances to the nearest regional centre (drives the Location score) and "
                         "census population / growth (feeds the city-opportunity ranker).").classes(
                    "text-xs text-slate-500")
    with ui.tabs().classes("w-full") as sub:
        s_status = ui.tab("Status")
        s_dist = ui.tab("Distances")
        s_demo = ui.tab("Demographics")
        s_orphans = ui.tab("Orphans")

    @ui.refreshable
    def status_panel():
        _city_status_dashboard()

    @ui.refreshable
    def orphans_panel():
        _orphans_report()

    # Expose the refreshes so switching back to this top-nav tab (e.g. after editing rates),
    # or deleting a city, re-queries the dashboard + orphan worklist too.
    _ui["city_status_refresh"] = status_panel.refresh
    _ui["orphans_refresh"] = orphans_panel.refresh

    def _on_sub(e):
        # Each panel is rendered once; re-query it whenever the user switches to it so edits
        # just made in the sibling sub-tabs show without a reload.
        if e.value == s_status.props["name"]:
            status_panel.refresh()
        elif e.value == s_orphans.props["name"]:
            orphans_panel.refresh()

    sub.on_value_change(_on_sub)

    with ui.tab_panels(sub, value=s_status).classes("w-full bg-transparent"):
        with ui.tab_panel(s_status):
            status_panel()
        with ui.tab_panel(s_dist):
            _distances_editor()
        with ui.tab_panel(s_demo):
            _demographics_editor()
        with ui.tab_panel(s_orphans):
            orphans_panel()


# ── Page 7: database explorer (read-only) ─────────────────────────────────────
def _db_truncate_formatter():
    """AG Grid cell formatter: show NULL, and trim long values (JSON blobs) to a preview."""
    return ("value==null?'NULL':((''+value).length>120?(''+value).slice(0,120)+'…':value)")


def _db_row_dialog(row: dict):
    """Full-row inspector; JSON-looking string columns are pretty-printed."""
    import json as _json
    with ui.dialog() as d, ui.card().classes("p-4 gap-1 w-[760px] max-w-full"):
        ui.label("Row detail").classes("font-semibold text-slate-800")
        with ui.scroll_area().classes("w-full").style("height:min(70vh,560px)"):
            for k, v in row.items():
                ui.label(k).classes("text-xs font-semibold text-slate-500 mt-2")
                text = "NULL" if v is None else v
                if isinstance(v, str) and v[:1] in "{[":
                    try:
                        text = _json.dumps(_json.loads(v), indent=2, ensure_ascii=False)
                    except Exception:
                        text = v
                ui.label(str(text)).classes(
                    "w-full whitespace-pre-wrap font-mono text-xs text-slate-700 "
                    "bg-slate-50 rounded p-2")
        with ui.row().classes("w-full justify-end mt-1"):
            ui.button("Close", on_click=d.close).props("flat")
    d.open()


def database_tab():
    with ui.card().classes("w-full rounded-xl border border-slate-200 shadow-sm mb-3"):
        with ui.row().classes("items-center gap-4"):
            ui.icon("storage").classes("text-2xl text-blue-600")
            with ui.column().classes("gap-0"):
                ui.label("Database explorer").classes("font-semibold text-slate-800")
                ui.label("Browse the SQLite tables and rows behind the app, or run a read-only "
                         "query. Read-only — nothing here can modify the database.").classes(
                    "text-xs text-slate-500")

    tables = store.list_tables()
    if not tables:
        ui.label("The database has no tables.").classes("text-sm text-slate-500"); return
    counts = {t["name"]: t["rows"] for t in tables}
    tnames = list(counts)
    state = {"table": tnames[0], "offset": 0, "size": 50}

    @ui.refreshable
    def browser():
        name = state["table"]
        page = store.table_page(name, limit=state["size"], offset=state["offset"])
        total = page["total"]
        with ui.row().classes("gap-2 flex-wrap mb-1 items-center"):
            ui.label(f"{name} — {total:,} row(s)").classes("text-sm font-medium text-slate-700")
            for c in store.table_schema(name):
                ui.badge(f"{c['name']}{' PK' if c['pk'] else ''} · {c['type'] or '—'}").props(
                    "color=primary" if c["pk"] else "color=grey-6")
        cols = page["columns"]
        rows = [dict(zip(cols, r)) for r in page["rows"]]
        grid = ui.aggrid({
            "columnDefs": [{"headerName": c, "field": c, "filter": True,
                            "valueFormatter": _db_truncate_formatter()} for c in cols],
            "rowData": rows,
            "defaultColDef": {"sortable": True, "resizable": True},
            "rowSelection": "single",
        }).classes("h-[52vh]")
        grid.on("rowClicked", lambda e: _db_row_dialog((e.args or {}).get("data") or {}),
                args=["data"])
        with ui.row().classes("w-full items-center gap-2 mt-2"):
            lo = state["offset"] + 1 if total else 0
            hi = min(state["offset"] + state["size"], total)
            ui.label(f"{lo}–{hi} of {total:,}").classes("text-xs text-slate-500")
            ui.space()

            def _prev():
                state["offset"] = max(0, state["offset"] - state["size"]); browser.refresh()

            def _next():
                if state["offset"] + state["size"] < total:
                    state["offset"] += state["size"]; browser.refresh()

            ui.button("Prev", icon="chevron_left", on_click=_prev).props("flat dense no-caps")
            ui.button("Next", icon="chevron_right", on_click=_next).props("flat dense no-caps")
        ui.label("Click a row to see the full values (JSON columns pretty-printed).").classes(
            "text-xs text-slate-400 mt-1")

    def _on_table(e):
        state["table"] = e.value; state["offset"] = 0; browser.refresh()

    ui.select({n: f"{n} ({counts[n]:,})" for n in tnames}, value=state["table"],
              label="Table", on_change=_on_table).classes("w-72 mb-2")
    browser()

    with ui.expansion("Run a read-only query").classes("w-full mt-4"):
        ui.label("Only a single SELECT / WITH / PRAGMA / EXPLAIN statement runs; anything that "
                 "could write is rejected.").classes("text-xs text-slate-500")
        q = ui.textarea(placeholder="SELECT name, updated_at FROM config ORDER BY name").props(
            "outlined input-class=font-mono").classes("w-full")
        result_box = ui.column().classes("w-full")

        def run_query():
            result_box.clear()
            sql = (q.value or "").strip()
            if not sql:
                return
            try:
                res = store.run_readonly_query(sql)
            except Exception as ex:
                with result_box:
                    ui.label(f"✗ {ex}").classes("text-sm text-red-600")
                return
            with result_box:
                cols = res["columns"]
                if not cols:
                    ui.label("Query ran — no result columns.").classes("text-sm text-slate-500")
                    return
                rrows = [dict(zip(cols, r)) for r in res["rows"]]
                ui.label(f"{len(rrows)} row(s).").classes("text-xs text-slate-500 mt-1")
                g = ui.aggrid({
                    "columnDefs": [{"headerName": c, "field": c, "filter": True,
                                    "valueFormatter": _db_truncate_formatter()} for c in cols],
                    "rowData": rrows,
                    "defaultColDef": {"sortable": True, "resizable": True},
                    "rowSelection": "single",
                }).classes("h-[40vh]")
                g.on("rowClicked", lambda e: _db_row_dialog((e.args or {}).get("data") or {}),
                     args=["data"])

        ui.button("Run query", icon="play_arrow", on_click=run_query).props(
            "unelevated no-caps").classes("mt-1")


# ── App shell (explicit @ui.page → required for a packaged onefile exe) ────────
# All UI lives inside the page function; nothing is created in global scope. This
# stops NiceGUI from re-executing the script per request (which fails once the
# "script" is a frozen .exe binary).
# Dark theme: the UI uses fixed light utilities (bg-white / text-slate-* / border-slate-*). NiceGUI
# ships Tailwind + Quasar utilities inside cascade layers (…, utilities, overrides,
# quasar_importants), and Quasar's colour utilities are !important — an unlayered override loses to
# them. Adding our overrides INTO the last layer (quasar_importants) with a higher-specificity
# body.body--dark selector wins the cascade. Light mode is untouched. AG Grid uses the v33 theming
# API (generated ag-theme-* class), themed via its --ag-* variables. (4.12.8)
_DARK_CSS = """
<style>
@layer quasar_importants {
  body.body--dark { background:#0f172a !important; color:#e2e8f0 !important; }
  body.body--dark .bg-white { background-color:#1e293b !important; }
  body.body--dark .q-card { background-color:#1e293b !important; color:#e2e8f0 !important; }
  body.body--dark .bg-slate-50 { background-color:#1e293b !important; }
  body.body--dark .bg-slate-100 { background-color:#334155 !important; }
  body.body--dark .border-slate-200 { border-color:#334155 !important; }
  body.body--dark .border-slate-100 { border-color:#293548 !important; }
  body.body--dark .text-slate-900 { color:#f1f5f9 !important; }
  body.body--dark .text-slate-800 { color:#e2e8f0 !important; }
  body.body--dark .text-slate-700 { color:#cbd5e1 !important; }
  body.body--dark .text-slate-600 { color:#cbd5e1 !important; }
  body.body--dark .text-slate-500 { color:#94a3b8 !important; }
  body.body--dark .text-slate-400 { color:#94a3b8 !important; }
  /* Accent/status text: the -600/-700 shades are too dark on the navy page, so
     brighten them to the -400 variants (keeps blue/red/green/amber legible). */
  body.body--dark .text-blue-600,    body.body--dark .text-blue-700    { color:#60a5fa !important; }
  body.body--dark .text-red-600,     body.body--dark .text-red-700     { color:#f87171 !important; }
  body.body--dark .text-emerald-600, body.body--dark .text-emerald-700,
  body.body--dark .text-green-600,   body.body--dark .text-green-700   { color:#34d399 !important; }
  body.body--dark .text-amber-500,   body.body--dark .text-amber-600,
  body.body--dark .text-amber-700                                      { color:#fbbf24 !important; }
  body.body--dark [class*="ag-theme"] {
    --ag-background-color:#1e293b; --ag-foreground-color:#e2e8f0;
    --ag-header-background-color:#273449; --ag-header-foreground-color:#cbd5e1;
    --ag-odd-row-background-color:#1b2638; --ag-row-hover-color:#273449;
    --ag-border-color:#334155; --ag-control-panel-background-color:#1e293b;
    --ag-input-border-color:#475569; --ag-input-background-color:#0f172a;
    --ag-secondary-foreground-color:#cbd5e1;
  }
}
</style>
"""


@ui.page("/")
def index():
    ui.colors(primary="#2563eb", secondary="#0f172a", accent="#10b981")
    ui.add_head_html('<style>body{background:#f1f5f9;}</style>')
    ui.add_head_html(_DARK_CSS)
    # Restore the saved theme (DB-persisted) before building the page.
    try:
        _dark_pref = bool((store.read_config("ui_prefs", None) or {}).get("dark", False))
    except Exception:
        _dark_pref = False
    _ui["dark_mode"] = ui.dark_mode(value=_dark_pref)
    header()
    with ui.column().classes("w-full max-w-[1300px] mx-auto px-6 py-4 gap-0"):
        with ui.tabs().classes("w-full") as tabs:
            t_list = ui.tab("Portfolio", icon="table_view")
            t_form = ui.tab("Add / Edit Property", icon="add_box")
            t_rpts = ui.tab("Reports", icon="summarize")
            t_rate = ui.tab("Rates", icon="payments")
            t_city = ui.tab("City data", icon="public")
            t_db   = ui.tab("Database", icon="storage")
            t_set  = ui.tab("Settings", icon="settings")
        _ui["tabs"] = tabs          # so a save can switch back to the portfolio
        _ui["t_list"] = t_list
        _ui["t_form"] = t_form      # so "Edit" can jump to the form

        def _on_tab_change(e):
            # Clicking "Add / Edit Property" directly should give a fresh blank add form, not
            # keep showing a record the user loaded via Edit but never saved/cancelled.
            if form_logic.should_reset_form_on_tab(
                    e.value, t_form.props["name"],
                    programmatic=_programmatic_tab["on"],
                    editing=edit_ctx["index"] is not None):
                reset_form()
            # Re-query the City-data status dashboard on entry so it reflects edits made
            # elsewhere (e.g. rates) without a full reload.
            if e.value == t_city.props["name"] and _ui.get("city_status_refresh"):
                _ui["city_status_refresh"]()

        tabs.on_value_change(_on_tab_change)
        with ui.tab_panels(tabs, value=t_list).classes("w-full bg-transparent"):
            with ui.tab_panel(t_list):
                portfolio_tab()
            with ui.tab_panel(t_form):
                form_tab()
            with ui.tab_panel(t_rpts):
                reports_tab()
            with ui.tab_panel(t_rate):
                rates_tab()
            with ui.tab_panel(t_city):
                city_data_tab()
            with ui.tab_panel(t_db):
                database_tab()
            with ui.tab_panel(t_set):
                settings_tab()


if __name__ in {"__main__", "__mp_main__"}:
    import multiprocessing
    multiprocessing.freeze_support()  # required for PyInstaller onefile + native mode
    if os.environ.get("CPA_WEB") == "1":
        # Dev/test mode: serve in the browser (set CPA_WEB=1) so the UI can be
        # previewed and clicked without a native window. The packaged exe never
        # sets this, so it always runs as a native desktop window.
        ui.run(reload=False, port=8080, show=False,
               title="Commercial Property Analyser POC")
    else:
        ui.run(native=True, reload=False, window_size=(1320, 860),
               port=native.find_open_port(),
               title="Commercial Property Analyser POC")
