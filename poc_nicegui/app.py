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
import shutil
import asyncio
import threading
import statistics
import tempfile
from pathlib import Path

# ── Locate the project + a WRITABLE data directory ────────────────────────────
WORKTREE = Path(__file__).resolve().parents[1]

if getattr(sys, "frozen", False):
    # Packaged (.exe): project code + seed data are bundled read-only under _MEIPASS,
    # which is wiped on exit — so the live DB must live in a persistent user dir.
    BASE = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    LEGACY_PROPS = BASE / "properties.json"            # bundled one-time seed
    _data_base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    DATA_DIR = _data_base / "CommercialPropertyAnalyser"
else:
    # Dev: run from the worktree; seed from the LIVE repo-root properties.json.
    BASE = WORKTREE
    _live = WORKTREE.parents[2] / "properties.json"
    LEGACY_PROPS = _live if _live.exists() else WORKTREE / "properties.json"
    DATA_DIR = WORKTREE / "poc_nicegui" / "_data"

sys.path.insert(0, str(BASE))  # import the project packages from the code location
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Seed writable copies of config/ + the reference json/ into the data dir on first run,
# then run FROM there, so every relative path the engine uses (config/financing.json,
# json/score_weights.json, json/vacancy_rates.json, …) is writable. The packaged bundle
# (_MEIPASS) is read-only, and in dev this keeps edits out of the tracked repo files.
for _sub in ("config", "json"):
    _dst = DATA_DIR / _sub
    if not _dst.exists() and (BASE / _sub).exists():
        shutil.copytree(BASE / _sub, _dst)

# pywebview derives a default base_uri from sys.argv[0] AT IMPORT TIME; once we chdir
# into the data dir a relative argv[0] would no longer resolve, so pin it to an absolute
# path first (a frozen exe already has an absolute argv[0]).
if not getattr(sys, "frozen", False):
    sys.argv[0] = str(Path(__file__).resolve())

os.chdir(DATA_DIR)             # run from the writable data dir (config/ + json/ copies)
DB_PATH = DATA_DIR / "properties.db"

from datetime import date

from data.store import DataStore, CommercialRentLoader, ResidentialRentLoader
from analysis.rent_resolver import RentResolver
from analysis.analyzer import CommercialPropertyAnalyzer, build_partial_record
from analysis.report_builder import record_to_prop, build_report_row, reanalyze_properties
from analysis.financing_config import (
    resolve_financing, mixed_use_commercial_gfa_share,
    load_financing_config, save_financing_config, base_rate_info,
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
from models.constants import PROPERTY_TYPES
from version import __version__

from nicegui import ui, app, native

# Persistent SQLite store, migrated once from the bundled/legacy JSON seed. All of the
# store's own relative paths (json/commercial_rents.json, missing_cities.json, …) now
# resolve under the writable DATA_DIR because we chdir'd there above.
store = DataStore(properties_path=str(DB_PATH))
store.ensure_properties_migrated(str(LEGACY_PROPS))
store.ensure_rates_migrated()


# ── Live base-rate feed (Bank of Canada GoC 5yr) ─────────────────────────────
# Auto-refresh the sourced base rate on boot: one lightweight BoC Valet call,
# throttled to once/day, fully offline-safe. A failed fetch keeps the last good
# json/interest_rates.json (and the engine ultimately falls back to the anchor in
# config/financing.json), so this never blocks or breaks startup. Runs off-thread.
def _refresh_base_rate_async():
    try:
        from analysis.rate_feed import refresh_interest_rates
        from analysis import financing_config
        changed, _reason = refresh_interest_rates(max_age_hours=20)
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


def header():
    with ui.header().classes("items-center justify-between px-6 py-3 bg-slate-900 text-white shadow"):
        with ui.row().classes("items-center gap-3"):
            ui.icon("domain").classes("text-2xl text-blue-400")
            with ui.column().classes("gap-0"):
                ui.label("Commercial Property Analyser").classes("text-lg font-semibold leading-tight")
                ui.label("Desktop UI — proof of concept").classes("text-xs text-slate-400 leading-tight")
        ui.label(f"v{__version__} · live SQLite database").classes("text-xs text-slate-300")


def _load_rows() -> list:
    rows = []
    for i, p in enumerate(store.load_properties()):
        rows.append({
            "id": i,
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
    rows = _ui.get("all_rows") or []
    term = (_ui.get("search_term") or "").strip().lower()
    if term:
        rows = [r for r in rows if term in (r.get("address") or "").lower()]
    grid.options["rowData"] = rows
    grid.update()


def refresh_portfolio():
    """Re-read the DB and refresh the stat tiles + grid (called after a save)."""
    if "stats" in _ui:
        _ui["stats"].refresh()
    _ui["all_rows"] = _load_rows()
    _apply_portfolio_filter()


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
        search = (ui.input(placeholder="Search by address…", on_change=on_search)
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
        if row.get("id") is not None:
            await open_report(row["id"])

    grid.on("rowClicked", on_click, args=["data"])


async def open_report(idx: int):
    props = store.load_properties()
    if idx is None or idx >= len(props):
        return
    p = props[idx]
    with ui.dialog() as dialog, ui.card().classes("w-[92vw] max-w-[1200px] h-[88vh] p-0 flex flex-col"):
        with ui.row().classes("w-full items-center justify-between px-4 py-2 bg-slate-900 text-white"):
            ui.label(p.get("address") or "Property report").classes("font-semibold")
            with ui.row().classes("items-center gap-1"):
                ui.button("Edit", icon="edit",
                          on_click=lambda: (dialog.close(), load_for_edit(idx))
                          ).props("flat dense no-caps color=white")
                ui.button("Delete", icon="delete",
                          on_click=lambda: confirm_delete(idx, dialog)
                          ).props("flat dense no-caps color=white")
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
state = {"type": "Hotel"}
FIELDS = {}  # name → input element, rebuilt each time the form reshapes
# index=None → add mode; otherwise editing the record at that position (load order).
edit_ctx = {"index": None, "orig_key": None, "record": None}


@ui.refreshable
def dynamic_form():
    FIELDS.clear()
    rec = edit_ctx["record"] or {}
    um  = rec.get("unit_mix") or {}
    groups = ["common"] + TYPE_GROUPS.get(state["type"], [])

    def pv(key, default=None):
        """Prefill value for an existing field (edit mode), else the default."""
        v = rec.get(key, default)
        return v if v not in ("", None) else default

    def pvpct(key):
        v = rec.get(key)
        return round(v * 100, 2) if isinstance(v, (int, float)) else None

    # Rent prefills are conditional on provenance so editing a record doesn't silently
    # "freeze" a market-estimated figure as a user-entered one. A commercial/residential
    # rent is only prefilled when the record flags it as owner-entered; the direct total
    # (annual_rent) is only prefilled when there is no component rent to recompute from
    # — the same guard record_to_prop uses for re-analysis.
    comm_prefill   = pv("commercial_rent")  if rec.get("commercial_rent_user_entered")  else None
    res_prefill    = pv("residential_rent") if rec.get("residential_rent_user_entered") else None
    _has_component = bool(rec.get("commercial_rent")) or bool(rec.get("residential_rent"))
    annual_prefill = None if _has_component else pv("annual_rent")

    # Resolved (global) financing — shown read-only so the form is complete; down
    # payment / rate / amortization live in Settings, not per property.
    _um_counts = rec.get("unit_mix") or {}
    _units_preview = sum(_um_counts.get(k, 0) or 0 for k in
                         ("bachelor", "one_br", "two_br", "three_br", "four_br", "unknown"))
    try:
        _fin_preview = resolve_financing(rec.get("asking_price") or 0,
                                         state["type"], _units_preview or None)
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
            FIELDS["province"] = ui.input("Province", value=pv("province", "")).classes("w-28")
        with ui.row().classes("w-full gap-3"):
            FIELDS["mls_number"] = ui.input("MLS #", value=pv("mls_number", "")).classes("w-48")
            FIELDS["asking_price"]   = ui.number("Asking price", value=pv("asking_price"), prefix="$", format="%.0f",
                                                 validation={"Must be greater than 0": lambda v: v is None or v > 0}).classes("flex-1")
            FIELDS["original_price"] = ui.number("Original / list price", value=pv("original_price"), prefix="$", format="%.0f").classes("flex-1")
        with ui.row().classes("w-full gap-3"):
            FIELDS["total_sq_ft"]    = ui.number("Total sq ft", value=pv("total_sq_ft"), format="%.0f",
                                                 validation={"Can't be negative": lambda v: v is None or v >= 0}).classes("flex-1")
            FIELDS["property_taxes"] = ui.number("Property taxes / yr", value=pv("property_taxes"), prefix="$", format="%.0f").classes("flex-1")
            FIELDS["construction_cost"] = ui.number("Construction cost", value=pv("construction_cost"), prefix="$", format="%.0f").classes("flex-1")
        with ui.row().classes("w-full gap-3"):
            FIELDS["lease_type"]   = ui.select(["Normal", "NNN"], value=pv("lease_type", "Normal"), label="Lease type").classes("w-40")
            FIELDS["status"]       = ui.select(["active", "inactive"], value=pv("status", "active"), label="Status").classes("w-40")
            FIELDS["listing_date"] = ui.input("Listing date", value=pv("listing_date", "")).props("type=date").classes("w-48")
            FIELDS["hold_years"]   = ui.number("Hold years", value=pv("hold_years", _fin_preview.get("hold_years", 10)),
                                               format="%d").classes("w-32")
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
                FIELDS["commercial_rent"] = ui.number("Commercial rent $/yr", value=comm_prefill, prefix="$", format="%.0f").classes("flex-1")
                FIELDS["market_cap_rate"] = ui.number("Market cap rate", value=pvpct("market_cap_rate"), suffix="%", format="%.2f").classes("flex-1")
                FIELDS["exit_cap_rate"]   = ui.number("Exit cap rate", value=pvpct("exit_cap_rate"), suffix="%", format="%.2f").classes("flex-1")
            with ui.row().classes("w-full gap-3"):
                FIELDS["commercial_lease_expiry"] = ui.input("Commercial lease expiry", value=pv("commercial_lease_expiry", "")).props("type=date").classes("w-48")
                ui.label("A commercial rent you enter is treated as advertised (actual), "
                         "not a market estimate.").classes("text-xs text-slate-500 self-center")

    if "residential" in groups:
        with card("Residential unit mix", "apartment"):
            with ui.row().classes("w-full gap-3 flex-wrap"):
                for key, lbl in [("bachelor", "Bachelor"), ("one_br", "1 BR"), ("two_br", "2 BR"),
                                 ("three_br", "3 BR"), ("four_br", "4 BR"), ("unknown", "Unknown")]:
                    FIELDS[f"um_{key}"] = ui.number(lbl, value=um.get(key, 0) or 0, format="%d").classes("w-28")
            with ui.row().classes("w-full gap-3 items-center"):
                FIELDS["floors"] = ui.number("Floors", value=um.get("floors", rec.get("floors", 1)) or 1, format="%d").classes("w-28")
                FIELDS["residential_rent"] = ui.number("Residential rent $/yr (override)", value=res_prefill,
                                                       prefix="$", format="%.0f").classes("flex-1")
            ui.label("Leave the residential rent blank to price the unit mix at the city "
                     "market rate from the residential_rents table; enter a figure to use "
                     "it as the in-place residential income instead.").classes(
                "text-xs text-slate-500")

    if "hotel" in groups:
        with card("Hotel operations", "hotel"):
            with ui.row().classes("w-full gap-3"):
                FIELDS["hotel_rooms"]     = ui.number("Rooms", value=pv("hotel_rooms"), format="%d").classes("flex-1")
                FIELDS["hotel_adr"]       = ui.number("ADR (avg daily rate)", value=pv("hotel_adr"), prefix="$", format="%.0f").classes("flex-1")
                FIELDS["hotel_occupancy"] = ui.number("Occupancy", value=pvpct("hotel_occupancy"), suffix="%", format="%.1f").classes("flex-1")

    if "industrial" in groups:
        with card("Industrial building detail", "factory"):
            with ui.row().classes("w-full gap-3"):
                FIELDS["ind_warehouse_sqft"] = ui.number("Warehouse sq ft", value=pv("ind_warehouse_sqft"), format="%.0f").classes("flex-1")
                FIELDS["ind_office_sqft"]    = ui.number("Office sq ft", value=pv("ind_office_sqft"), format="%.0f").classes("flex-1")
                FIELDS["ind_yard_sqft"]      = ui.number("Yard sq ft", value=pv("ind_yard_sqft"), format="%.0f").classes("flex-1")
            with ui.row().classes("w-full gap-3"):
                FIELDS["ind_dock_doors"]      = ui.number("Dock doors", value=pv("ind_dock_doors"), format="%d").classes("flex-1")
                FIELDS["ind_drive_in_doors"]  = ui.number("Drive-in doors", value=pv("ind_drive_in_doors"), format="%d").classes("flex-1")
                FIELDS["ind_clear_height_ft"] = ui.number("Clear height (ft)", value=pv("ind_clear_height_ft"), format="%.1f").classes("flex-1")
            with ui.row().classes("w-full gap-3"):
                FIELDS["ind_office_rate"] = ui.number("Office rate $/sq ft", value=pv("ind_office_rate"), prefix="$", format="%.2f").classes("flex-1")
                FIELDS["ind_yard_rate"]   = ui.number("Yard rate $/sq ft", value=pv("ind_yard_rate"), prefix="$", format="%.2f").classes("flex-1")

    # Assumptions & overrides — always shown. Each override is blank by default and
    # falls back to the model's resolver when left empty, so nothing here is required.
    with card("Income & assumptions (overrides)", "tune"):
        with ui.row().classes("w-full gap-3"):
            FIELDS["annual_rent"]     = ui.number("Direct total rent $/yr", value=annual_prefill, prefix="$", format="%.0f").classes("flex-1")
            FIELDS["expense_ratio"]   = ui.number("Expense ratio", value=pvpct("expense_ratio"), suffix="%", format="%.1f").classes("flex-1")
            FIELDS["vacancy_rate"]    = ui.number("Vacancy rate", value=pvpct("vacancy_rate"), suffix="%", format="%.1f").classes("flex-1")
            FIELDS["noi_growth_rate"] = ui.number("NOI growth", value=pvpct("noi_growth_rate"), suffix="%", format="%.2f").classes("flex-1")
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
    v = _fval(name)
    return (float(v) / 100) if v not in (None, "") else None


def save_property_from_form():
    """Build a record from the form and persist it through the production pipeline."""
    address = (_fval("address") or "").strip()
    if not address:
        ui.notify("Address is required to save.", type="warning")
        return
    asking = float(_fval("asking_price", 0) or 0)
    if asking <= 0:
        ui.notify("Asking price must be greater than 0.", type="warning")
        return

    ptype   = state["type"]
    um = UnitMix(
        bachelor=int(_fval("um_bachelor", 0) or 0), one_br=int(_fval("um_one_br", 0) or 0),
        two_br=int(_fval("um_two_br", 0) or 0), three_br=int(_fval("um_three_br", 0) or 0),
        four_br=int(_fval("um_four_br", 0) or 0), unknown=int(_fval("um_unknown", 0) or 0),
        floors=int(_fval("floors", 1) or 1),
    )
    units = um.total_units
    share = mixed_use_commercial_gfa_share(ptype, um.floors)
    fin   = resolve_financing(asking, ptype, units, commercial_gfa_share=share)

    comm_rent = _fval("commercial_rent")
    res_rent  = _fval("residential_rent")
    prop = PropertyInput(
        original_price=float(_fval("original_price", asking) or asking), asking_price=asking,
        total_sq_ft=float(_fval("total_sq_ft", 0) or 0),
        property_taxes=float(_fval("property_taxes", 0) or 0),
        # Down payment / rate / amortization are global (config/financing.json, Settings
        # tab); hold_years is the one per-property financing input.
        down_payment_pct=fin["down_payment_pct"], interest_rate=fin["interest_rate"],
        term_years=fin["term_years"],
        hold_years=int(_fval("hold_years", fin["hold_years"]) or fin["hold_years"]),
        address=address, mls_number=_fval("mls_number", "") or "",
        city=_fval("city"), province=_fval("province"),
        property_type=ptype, status=_fval("status", "active"),
        lease_type=_fval("lease_type", "Normal"),
        listing_date=_fval("listing_date") or date.today().isoformat(),
        construction_cost=float(_fval("construction_cost", 0) or 0),
        commercial_lease_expiry=_fval("commercial_lease_expiry"),
        unit_mix=um if units else None,
        annual_rent=_fval("annual_rent"),
        commercial_rent=comm_rent,
        commercial_rent_user_entered=comm_rent is not None,
        residential_rent=res_rent,
        residential_rent_user_entered=res_rent is not None,
        expense_ratio=_pct("expense_ratio"),
        vacancy_rate=_pct("vacancy_rate"),
        noi_growth_rate=_pct("noi_growth_rate"),
        market_cap_rate=_pct("market_cap_rate"), exit_cap_rate=_pct("exit_cap_rate"),
        hotel_rooms=int(_fval("hotel_rooms", 0) or 0), hotel_adr=_fval("hotel_adr"),
        hotel_occupancy=_pct("hotel_occupancy"),
        ind_warehouse_sqft=float(_fval("ind_warehouse_sqft", 0) or 0),
        ind_office_sqft=float(_fval("ind_office_sqft", 0) or 0),
        ind_yard_sqft=float(_fval("ind_yard_sqft", 0) or 0),
        ind_dock_doors=int(_fval("ind_dock_doors", 0) or 0),
        ind_drive_in_doors=int(_fval("ind_drive_in_doors", 0) or 0),
        ind_clear_height_ft=float(_fval("ind_clear_height_ft", 0) or 0),
        ind_office_rate=_fval("ind_office_rate"), ind_yard_rate=_fval("ind_yard_rate"),
    )

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
    if prop.city and prop.province:
        store.ensure_city_in_rates(prop.city, prop.province)

    reset_form()
    refresh_portfolio()
    if _ui.get("tabs") is not None and _ui.get("t_list") is not None:
        _ui["tabs"].set_value(_ui["t_list"])
    ui.notify(
        f'{"Updated" if editing else "Saved"} "{address}"'
        + (" — full analysis computed." if analyzed
           else " — no market rate for that city yet, saved without analysis."),
        type="positive",
    )


def reset_form():
    """Return the form to add mode and clear it."""
    edit_ctx.update(index=None, orig_key=None, record=None)
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
    state["type"] = p.get("property_type") or state["type"]
    if _ui.get("type_select") is not None:
        _ui["type_select"].set_value(state["type"])
    dynamic_form.refresh()
    if _ui.get("tabs") is not None and _ui.get("t_form") is not None:
        _ui["tabs"].set_value(_ui["t_form"])


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
                if record.get("city") and record.get("province"):
                    store.ensure_city_in_rates(record["city"], record["province"])
                dialog.close()
                refresh_portfolio()
                ui.notify(f'Imported "{record.get("address")}" — complete it via Edit.',
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


def commercial_rates_editor():
    data = {"rows": store.load_commercial_rate_rows()}
    sel = {"val": _NEW_CITY}

    def labels():
        return {f"{r['city']}, {r['province']}": r for r in data["rows"]}

    @ui.refreshable
    def form():
        row = labels().get(sel["val"])
        f = {}
        with ui.row().classes("w-full gap-3"):
            f["city"] = ui.input("City", value=(row["city"] if row else "")).classes("w-48")
            f["province"] = ui.input("Province", value=(row["province"] if row else "")).classes("w-28")
            if row:
                f["city"].props("readonly"); f["province"].props("readonly")
        with ui.row().classes("w-full gap-3 flex-wrap"):
            for t in RATE_COMM_TYPES:
                cur = row["types"].get(t) if row else None
                f[t] = ui.number(f"{t} $/sq ft", value=cur, prefix="$", format="%.2f").classes("w-40")

        def save():
            city = (f["city"].value or "").strip()
            prov = (f["province"].value or "").strip().upper()
            if not city or not prov:
                ui.notify("City and province are required.", type="warning"); return
            rates = {t: float(f[t].value) for t in RATE_COMM_TYPES if f[t].value not in (None, "")}
            store.save_commercial_city(city, prov, rates)
            res = reanalyze_properties(
                store, resolver, CommercialPropertyAnalyzer,
                predicate=lambda p: (p.get("city", "") or "").strip().lower() == city.lower()
                and (p.get("province", "") or "").strip().upper() == prov)
            data["rows"] = store.load_commercial_rate_rows()
            sel["val"] = next((k for k, r in labels().items()
                               if r["city"].lower() == city.lower() and r["province"] == prov), _NEW_CITY)
            city_select.set_options([_NEW_CITY] + sorted(labels(), key=str.lower), value=sel["val"])
            form.refresh()
            refresh_portfolio()
            msg = f"Saved commercial rates for {city}, {prov}"
            msg += f" — re-analyzed {res['updated']} affected propert{'y' if res['updated'] == 1 else 'ies'}." if res["considered"] else "."
            ui.notify(msg, type="positive")

        ui.button("Save rates", icon="save", on_click=save).props("unelevated").classes("mt-1")

    def on_city(e):
        sel["val"] = e.value
        form.refresh()

    city_select = ui.select([_NEW_CITY] + sorted(labels(), key=str.lower), value=_NEW_CITY,
                            label="City to edit", on_change=on_city).classes("w-72 mb-3")
    form()


def residential_rates_editor():
    data = {"rows": store.load_residential_rate_rows()}
    sel = {"val": _NEW_CITY}

    def labels():
        return {f"{r['city']}, {r['province']}": r for r in data["rows"]}

    @ui.refreshable
    def form():
        row = labels().get(sel["val"])
        f = {}
        with ui.row().classes("w-full gap-3"):
            f["city"] = ui.input("City", value=(row["city"] if row else "")).classes("w-48")
            f["province"] = ui.input("Province", value=(row["province"] if row else "")).classes("w-28")
            if row:
                f["city"].props("readonly"); f["province"].props("readonly")
        with ui.row().classes("w-full gap-3 flex-wrap"):
            for key, lbl in RATE_RES_FIELDS:
                cur = row["units"].get(key) if row else None
                f[key] = ui.number(f"{lbl} $/mo", value=cur, prefix="$", format="%.0f").classes("w-32")
        ui.label("The “unknown” unit rate is auto-set to the average of the entered "
                 "unit rents (matches the CLI).").classes("text-xs text-slate-500")

        def save():
            city = (f["city"].value or "").strip()
            prov = (f["province"].value or "").strip().upper()
            if not city or not prov:
                ui.notify("City and province are required.", type="warning"); return
            units = {key: float(f[key].value) for key, _ in RATE_RES_FIELDS if f[key].value not in (None, "")}
            known = list(units.values())
            if known:
                units["unknown"] = round(sum(known) / len(known), 2)
            store.save_residential_city(city, prov, units)
            res = reanalyze_properties(
                store, resolver, CommercialPropertyAnalyzer,
                predicate=lambda p: (p.get("city", "") or "").strip().lower() == city.lower()
                and (p.get("province", "") or "").strip().upper() == prov)
            data["rows"] = store.load_residential_rate_rows()
            sel["val"] = next((k for k, r in labels().items()
                               if r["city"].lower() == city.lower() and r["province"] == prov), _NEW_CITY)
            city_select.set_options([_NEW_CITY] + sorted(labels(), key=str.lower), value=sel["val"])
            form.refresh()
            refresh_portfolio()
            msg = f"Saved residential rates for {city}, {prov}"
            msg += f" — re-analyzed {res['updated']} affected propert{'y' if res['updated'] == 1 else 'ies'}." if res["considered"] else "."
            ui.notify(msg, type="positive")

        ui.button("Save rates", icon="save", on_click=save).props("unelevated").classes("mt-1")

    def on_city(e):
        sel["val"] = e.value
        form.refresh()

    city_select = ui.select([_NEW_CITY] + sorted(labels(), key=str.lower), value=_NEW_CITY,
                            label="City to edit", on_change=on_city).classes("w-72 mb-3")
    form()


def rates_tab():
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
            from analysis import financing_config
            changed, reason = await asyncio.to_thread(
                lambda: refresh_interest_rates(force=True, timeout=30))
            financing_config.reload_rate_feed()
            _base_rate_row.refresh()
            ui.notify(f"Base rate {reason}" + ("  — Re-analyze to apply." if changed else ""),
                      type="positive" if changed else "warning")

        ui.button("Refresh base rate (Bank of Canada)", icon="cloud_download",
                  on_click=refresh_rates).props("outline no-caps dense").classes("mt-1")

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
_CITY_DISTANCES_FILE = "json/city_distances.json"
_CITY_DEMOGRAPHICS_FILE = "json/city_demographics.json"


def _read_json_file(path):
    return store._read(path) if os.path.exists(path) else {}


def _distances_editor():
    raw = {"d": _read_json_file(_CITY_DISTANCES_FILE)}
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
            raw["d"][city] = {"distance_km": f["km"].value,
                              "nearest_centre": (f["centre"].value or "").strip()}
            store._write(_CITY_DISTANCES_FILE, raw["d"])
            sel["val"] = city
            city_select.set_options([_NEW_CITY] + sorted(raw["d"], key=str.lower), value=city)
            form.refresh()
            ui.notify(f"Saved distance for {city}.", type="positive")

        ui.button("Save distance", icon="save", on_click=save).props("unelevated").classes("mt-1")

    def on_city(e):
        sel["val"] = e.value
        form.refresh()

    city_select = ui.select([_NEW_CITY] + sorted(raw["d"], key=str.lower), value=_NEW_CITY,
                            label="City to edit", on_change=on_city).classes("w-72 mb-3")
    form()


def _demographics_editor():
    raw = {"d": _read_json_file(_CITY_DEMOGRAPHICS_FILE)}
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
            raw["d"][city.lower()] = {
                "population": pop, "population_2016": pop16,
                "growth_pct_annual": growth,
                "source": (f["source"].value or "").strip() or "Stats Canada 2021 Census",
                "notes": (row or {}).get("notes", ""),
            }
            store._write(_CITY_DEMOGRAPHICS_FILE, raw["d"])
            sel["val"] = city
            city_select.set_options([_NEW_CITY] + sorted((k.title() for k in raw["d"]), key=str.lower), value=city)
            form.refresh()
            ui.notify(f"Saved demographics for {city} (growth {growth:+.2f}%/yr)."
                      if growth is not None else f"Saved demographics for {city}.", type="positive")

    def on_city(e):
        sel["val"] = e.value
        form.refresh()

    city_select = ui.select([_NEW_CITY] + sorted((k.title() for k in raw["d"]), key=str.lower),
                            value=_NEW_CITY, label="City to edit", on_change=on_city).classes("w-72 mb-3")
    form()


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
        s_dist = ui.tab("Distances")
        s_demo = ui.tab("Demographics")
    with ui.tab_panels(sub, value=s_dist).classes("w-full bg-transparent"):
        with ui.tab_panel(s_dist):
            _distances_editor()
        with ui.tab_panel(s_demo):
            _demographics_editor()


# ── App shell (explicit @ui.page → required for a packaged onefile exe) ────────
# All UI lives inside the page function; nothing is created in global scope. This
# stops NiceGUI from re-executing the script per request (which fails once the
# "script" is a frozen .exe binary).
@ui.page("/")
def index():
    ui.colors(primary="#2563eb", secondary="#0f172a", accent="#10b981")
    ui.add_head_html('<style>body{background:#f1f5f9;}</style>')
    header()
    with ui.column().classes("w-full max-w-[1300px] mx-auto px-6 py-4 gap-0"):
        with ui.tabs().classes("w-full") as tabs:
            t_list = ui.tab("Portfolio", icon="table_view")
            t_form = ui.tab("Add / Edit Property", icon="add_box")
            t_rpts = ui.tab("Reports", icon="summarize")
            t_rate = ui.tab("Rates", icon="payments")
            t_city = ui.tab("City data", icon="public")
            t_set  = ui.tab("Settings", icon="settings")
        _ui["tabs"] = tabs          # so a save can switch back to the portfolio
        _ui["t_list"] = t_list
        _ui["t_form"] = t_form      # so "Edit" can jump to the form
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
