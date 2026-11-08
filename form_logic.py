"""
Pure, UI-free form/logic helpers for the desktop app (poc_nicegui/app.py).

Everything here is extracted from app.py so it can be unit-tested WITHOUT importing
app.py (which runs heavy boot side-effects at import: DB setup, chdir, a network
thread). app.py keeps the NiceGUI wiring and delegates the computation here. No
`nicegui` import, no module-level side effects.

Covered behaviours (by changelog release):
  * filter_rows ............ portfolio address search (4.7.1)
  * prefill_value/_pct ..... draft-over-record form prefill + type-switch draft (4.7.2, 4.9.4)
  * rent_prefills .......... rent prefill provenance guard (4.7.2)
  * pct_to_fraction ........ percent-field coercion
  * coerce_financing_field . per-asset-class financing editor coercion (4.9.0)
  * validate_property_form . save-time validation (4.4)
  * build_property_input ... form values -> PropertyInput, financing from global (4.1/4.4/4.7.2/4.9.4)
"""
from __future__ import annotations

import re
from datetime import date

from models.property_input import PropertyInput, UnitMix

# Sentinel: a blank non-ratio financing field means "leave the stored value as-is",
# distinct from a blank ratio field which clears it to None.
SKIP = object()


# ── Portfolio search (4.7.1) ─────────────────────────────────────────────────

def filter_rows(rows, term):
    """Rows whose address OR city contains `term` (case-insensitive substring) — so a
    listing is findable by its street address or by the city, even when the two differ
    (e.g. address 'Brockton' but city 'Walkerton'). An empty/blank term returns all rows."""
    t = (term or "").strip().lower()
    if not t:
        return list(rows)
    return [r for r in rows
            if t in (r.get("address") or "").lower()
            or t in (r.get("city") or "").lower()]


# ── Address normalization (4.11.4) ───────────────────────────────────────────

def clean_address(address, city, province):
    """Strip a trailing ', <city>' and/or ', <province>' from an address when they duplicate
    the record's own city/province fields, leaving just the street. Conservative: only removes
    a trailing segment that matches (case-insensitive) — so a street whose trailing town
    differs from the city field (e.g. '… , Brockton, ON' with city 'Walkerton') keeps that
    town, and an already-clean street is returned unchanged (idempotent). Never returns empty
    when the input had a street."""
    addr = (address or "").strip()
    # Remove from the end: province first (it's last), then city. Repeat so ', City, Prov'
    # collapses to the street.
    for token in ((province or "").strip(), (city or "").strip()):
        if not token:
            continue
        suffix = ", " + token
        if addr.lower().endswith(suffix.lower()):
            stripped = addr[: -len(suffix)].rstrip().rstrip(",").rstrip()
            if stripped:                 # never strip away the whole address
                addr = stripped
    return addr


# ── Stable row identity (4.11.1) ─────────────────────────────────────────────

def resolve_row_index(records, address, listing_date):
    """Index of the record matching (address, listing_date) — the table's UNIQUE key — in
    the CURRENT record list. Used so a grid selection maps to the right property even after
    the load order shifts (an edit/add moves a record to the end; a delete renumbers). A
    cached positional id can go stale; this key never does. Returns None if not found."""
    addr = address or ""
    ld = listing_date or ""
    for i, r in enumerate(records):
        if (r.get("address") or "") == addr and (r.get("listing_date") or "") == ld:
            return i
    return None


def should_reset_form_on_tab(tab_value, form_tab_name, *, programmatic, editing):
    """Whether switching to the Add/Edit form tab should reset it to a blank add form.

    Clicking the "Add / Edit Property" tab directly means "add a new property", so a record
    left loaded for editing must not linger from a previous Edit the user never saved or
    cancelled. Only reset when:
      * the tab being shown IS the form tab (``tab_value == form_tab_name``),
      * the form is currently in EDIT mode (``editing``) — an in-progress *new* entry is kept, and
      * the switch was a real user click, not the programmatic jump the report's Edit button
        makes (``not programmatic``) — that one loads a record on purpose.
    """
    return bool(editing) and (not programmatic) and tab_value == form_tab_name


# ── Form prefill: draft (type-switch) over edited record (4.7.2, 4.9.4) ──────

def prefill_value(key, draft, record, default=None):
    """Prefill a plain field: a carried draft entry first (survives a type switch),
    else the edited record, else the default. Empty/None falls through to default."""
    v = draft[key] if key in draft else record.get(key, default)
    return v if v not in ("", None) else default


def prefill_pct(key, draft, record):
    """Prefill a percent field. A draft entry already holds the display % (what the
    user typed), so return it as-is; otherwise convert the record's stored fraction."""
    if key in draft:
        return draft[key]
    v = record.get(key)
    return round(v * 100, 2) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def rent_prefills(draft, record):
    """Provenance-aware rent prefills. Commercial/residential prefill only when the user
    entered them (present in the draft) or the record flags them owner-entered — so editing
    never silently freezes a market estimate as user-entered. The direct total (annual_rent)
    prefills from a draft entry, else only when there's no component rent to recompute from."""
    comm = prefill_value("commercial_rent", draft, record) \
        if ("commercial_rent" in draft or record.get("commercial_rent_user_entered")) else None
    res = prefill_value("residential_rent", draft, record) \
        if ("residential_rent" in draft or record.get("residential_rent_user_entered")) else None
    has_component = bool(record.get("commercial_rent")) or bool(record.get("residential_rent"))
    annual = prefill_value("annual_rent", draft, record) if "annual_rent" in draft \
        else (None if has_component else prefill_value("annual_rent", draft, record))
    return {"commercial_rent": comm, "residential_rent": res, "annual_rent": annual}


# Short provenance note per rent field for the read-only "what was calculated" caption.
_RENT_CAPTION_NOTE = {
    "commercial_rent":  "market estimate",
    "residential_rent": "market estimate",
    "annual_rent":      "total",
}


def resolved_rent_caption(record, field, prefilled):
    """Read-only caption showing the rent figure the last analysis resolved for ``field``,
    for display beneath the edit input. ``rent_prefills`` deliberately blanks a market-estimated
    rent so editing never freezes an estimate as owner-entered — but that left the edit form
    hiding what the analysis actually used. This restores the parity the CLI edit view had, where
    the resolved rent appeared as the field's "current" value, without touching the editable
    input (so provenance is still preserved on save).

    Returns the caption string, or ``None`` when the input is already prefilled (owner-entered →
    the figure is in the box), or there's no positive stored figure (a brand-new add, or a type
    without that component)."""
    if prefilled not in (None, ""):
        return None
    try:
        amt = float(record.get(field))
    except (TypeError, ValueError):
        return None
    if amt <= 0:
        return None
    note = _RENT_CAPTION_NOTE.get(field, "resolved")
    return f"Last analysis used ${amt:,.0f}/yr ({note})."


# ── City rate table (v4.11) ──────────────────────────────────────────────────

def rate_rows_to_grid(rows, field_key, columns):
    """Flatten store rate rows ([{city, province, <field_key>: {col: val}}]) into editable
    grid rows ({city, province, <col>: val|None, …}). `field_key` is 'types' (commercial)
    or 'units' (residential); `columns` the rate keys to surface as columns."""
    out = []
    for r in rows:
        vals = r.get(field_key) or {}
        g = {"city": r.get("city") or "", "province": r.get("province") or ""}
        for col in columns:
            g[col] = vals.get(col)
        out.append(g)
    return out


def grid_row_to_rates(row, columns):
    """{col: float(value)} for the non-blank rate cells of one grid row (what save_*_city
    takes). Non-numeric / blank cells are dropped."""
    out = {}
    for col in columns:
        v = row.get(col)
        if v in (None, ""):
            continue
        try:
            out[col] = float(v)
        except (TypeError, ValueError):
            pass
    return out


def residential_with_unknown(units):
    """Residential units dict + `unknown` = average of the entered unit rents (rounded to
    2dp) — the rule the per-city residential form applies, so component resolution matches."""
    out = dict(units)
    known = [v for v in units.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if known:
        out["unknown"] = round(sum(known) / len(known), 2)
    return out


def _norm_cell(v):
    """Normalize a grid cell for change-detection: blank → None, numeric-like → float."""
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def changed_rate_rows(original, edited, columns):
    """Return the `edited` grid rows whose rate cells differ from `original` (matched by
    city+province, case-insensitive), including cities not in `original` (newly added).
    Rows with a blank city are ignored."""
    def key(r):
        return ((r.get("city") or "").strip().lower(), (r.get("province") or "").strip().upper())

    def cells(r):
        return tuple(_norm_cell(r.get(c)) for c in columns)

    orig = {key(r): cells(r) for r in original}
    out = []
    for r in edited:
        k = key(r)
        if not k[0]:
            continue
        if k not in orig or cells(r) != orig[k]:
            out.append(r)
    return out


# ── City data: linked properties, "data needed" notice, status dashboard ───────

def properties_for_city(properties, city, province):
    """Records whose city/province match `city`/`province` (case-insensitive). Used to
    show what's linked to a city before deleting its rates, and to count a city's
    properties on the status dashboard (4.12.5)."""
    c = (city or "").strip().lower()
    p = (province or "").strip().upper()
    out = []
    for rec in properties:
        if (rec.get("city") or "").strip().lower() == c and \
           (rec.get("province") or "").strip().upper() == p:
            out.append(rec)
    return out


def properties_for_city_name(properties, city):
    """Records whose city matches `city` (case-insensitive), ANY province. Used by the City
    data (demographics / distances) delete, whose rows are keyed by city name only — so the
    linked-properties warning and the orphan check span every province sharing that name."""
    c = (city or "").strip().lower()
    return [rec for rec in (properties or [])
            if (rec.get("city") or "").strip().lower() == c]


def city_data_needed_message(created):
    """Notice text for a newly-added property whose city had no reference data, from the
    flags dict `ensure_city_reference_data` returns. Returns None when nothing was newly
    stubbed (the city already had data), so the caller appends nothing (4.12.6)."""
    if not created or not created.get("any_created"):
        return None
    need = []
    if created.get("rates"):
        need.append("rates")
    if created.get("demographics"):
        need.append("demographics")
    if created.get("distances"):
        need.append("distance")
    if not need:
        return None
    joined = need[0] if len(need) == 1 else (
        ", ".join(need[:-1]) + " and " + need[-1])
    return (f"That city is new — its {joined} {'is' if len(need) == 1 else 'are'} blank. "
            f"Fill it in on the City data and Rates tabs so this property can be analyzed.")


def _rate_map_filled(mapping):
    """True when a {col: value} rate map has at least one non-blank numeric value."""
    for v in (mapping or {}).values():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return True
    return False


def city_data_status(properties, comm_rows, res_rows, demographics, distances):
    """Per-city data-completeness rows for the status dashboard (4.12.7). Unions cities
    across properties and the two rate tables, keyed by (city_lower, province). For each:
    property count, whether commercial/residential rates exist (any non-null cell), and
    whether a distance (distance_km) and demographics (population) are on file — looked up
    by lowercase city (demographics) and Title-case city (distances), matching the stores.
    Each row lists what's `missing`. Sorted most-incomplete, then most properties, then
    name."""
    comm_by = {((r.get("city") or "").strip().lower(), (r.get("province") or "").strip().upper()):
               r.get("types") for r in (comm_rows or [])}
    res_by = {((r.get("city") or "").strip().lower(), (r.get("province") or "").strip().upper()):
              r.get("units") for r in (res_rows or [])}
    demo = {(k or "").strip().lower(): v for k, v in (demographics or {}).items()}
    dist = {(k or "").strip().lower(): v for k, v in (distances or {}).items()}

    # Build the display name per key from whatever source has it, favouring a real
    # property/rate-row spelling.
    keys, names = set(), {}
    for rec in (properties or []):
        c = (rec.get("city") or "").strip()
        p = (rec.get("province") or "").strip().upper()
        if not c:
            continue
        k = (c.lower(), p)
        keys.add(k); names.setdefault(k, c)
    for src in (comm_rows or []), (res_rows or []):
        for r in src:
            c = (r.get("city") or "").strip()
            p = (r.get("province") or "").strip().upper()
            if not c:
                continue
            k = (c.lower(), p)
            keys.add(k); names.setdefault(k, c)

    rows = []
    for (c_lower, prov) in keys:
        name = names.get((c_lower, prov), c_lower.title())
        n_props = len(properties_for_city(properties or [], c_lower, prov))
        has_comm = _rate_map_filled(comm_by.get((c_lower, prov)))
        has_res = _rate_map_filled(res_by.get((c_lower, prov)))
        d = demo.get(c_lower) or {}
        has_demo = bool(d.get("population"))
        dist_row = dist.get(c_lower) or {}
        has_dist = dist_row.get("distance_km") is not None
        missing = []
        if not has_comm:
            missing.append("commercial rates")
        if not has_res:
            missing.append("residential rates")
        if not has_dist:
            missing.append("distance")
        if not has_demo:
            missing.append("demographics")
        rows.append({
            "city": name, "province": prov, "n_props": n_props,
            "has_commercial": has_comm, "has_residential": has_res,
            "has_distance": has_dist, "has_demographics": has_demo,
            "missing": missing,
        })
    rows.sort(key=lambda r: (-len(r["missing"]), -r["n_props"], r["city"].lower()))
    return rows


def orphaned_properties(properties, comm_rows, res_rows, demographics, distances):
    """Properties whose referenced city is missing one or more reference-data types
    (commercial / residential rates, distance, demographics). These are "orphans" — left
    behind when a city's data is deleted (or forced-deleted) while properties still point at
    it, or simply never entered. Computed LIVE from current data, so an orphan clears itself
    the moment its city's data is re-added. Returns [{address, city, province, missing: [...]}],
    one per affected property, sorted most-missing → city → address: a resolution worklist."""
    status = city_data_status(properties, comm_rows, res_rows, demographics, distances)
    missing_by = {((r["city"] or "").strip().lower(), (r["province"] or "").strip().upper()):
                  r["missing"] for r in status}
    out = []
    for rec in (properties or []):
        c = (rec.get("city") or "").strip()
        p = (rec.get("province") or "").strip().upper()
        if not c:
            continue
        miss = missing_by.get((c.lower(), p), [])
        if miss:
            out.append({
                "address": (rec.get("address") or "").strip() or "—",
                "city": c, "province": p, "missing": list(miss),
            })
    out.sort(key=lambda r: (-len(r["missing"]), r["city"].lower(), r["address"].lower()))
    return out


# ── DB explorer: read-only SQL guard (5.1.0) ──────────────────────────────────

_SQL_READONLY_START = re.compile(r"^(select|with|pragma|explain)\b", re.IGNORECASE)
# Write/DDL/transaction keywords rejected as whole words anywhere in the statement.
_SQL_BANNED = re.compile(
    r"\b(insert|update|delete|replace|drop|alter|create|attach|detach|reindex|"
    r"vacuum|truncate|begin|commit|rollback|savepoint|release)\b", re.IGNORECASE)


def is_readonly_sql(sql):
    """Gate for the DB explorer's query box. Returns (ok, cleaned_sql). ok is True ONLY for a
    single read-only statement: SELECT / WITH…SELECT / PRAGMA (no assignment) / EXPLAIN. Rejects
    multiple statements (any inner ';'), a write/DDL/transaction keyword anywhere, and a PRAGMA
    that assigns (contains '='). Defense-in-depth with the store's PRAGMA query_only."""
    s = (sql or "").strip()
    # One statement only: strip a single trailing ';', then reject any remaining ';'.
    if s.endswith(";"):
        s = s[:-1].strip()
    if not s or ";" in s:
        return False, ""
    if not _SQL_READONLY_START.match(s):
        return False, ""
    if _SQL_BANNED.search(s):
        return False, ""
    if s.lower().startswith("pragma") and "=" in s:
        return False, ""
    return True, s


# ── Coercion ─────────────────────────────────────────────────────────────────

def pct_to_fraction(v):
    """A percent-field display value (e.g. 65) → stored fraction (0.65). Blank → None."""
    return (float(v) / 100) if v not in (None, "") else None


def coerce_financing_field(value, kind):
    """Coerce one per-asset-class financing editor input (4.9.0). `kind` is 'pct'
    (display % → fraction), 'int', or 'ratio'. A blank ratio clears to None; a blank
    pct/int returns SKIP (leave the stored value unchanged)."""
    if value is None or value == "":
        return None if kind == "ratio" else SKIP
    if kind == "pct":
        return round(float(value) / 100, 6)
    if kind == "int":
        return int(value)
    return round(float(value), 4)   # ratio


# ── Validation (4.4 / 4.12.1 / 4.12.3) ───────────────────────────────────────

# Numeric form fields that must never be negative — money, sizes and counts. The values
# are the RAW form values (what the user typed), so this runs on the same scale the field
# shows. A blank field is skipped (optional); only an entered value is checked.
_NON_NEGATIVE_FIELDS = {
    "original_price": "Original / list price", "property_taxes": "Property taxes",
    "construction_cost": "Construction cost", "total_sq_ft": "Total sq ft",
    "commercial_rent": "Commercial rent", "residential_rent": "Residential rent",
    "annual_rent": "Direct total rent",
    "um_bachelor": "Bachelor units", "um_one_br": "1 BR units", "um_two_br": "2 BR units",
    "um_three_br": "3 BR units", "um_four_br": "4 BR units", "um_unknown": "Unknown units",
    "hotel_rooms": "Rooms", "hotel_adr": "ADR",
    "ind_warehouse_sqft": "Warehouse sq ft", "ind_office_sqft": "Office sq ft",
    "ind_yard_sqft": "Yard sq ft", "ind_dock_doors": "Dock doors",
    "ind_drive_in_doors": "Drive-in doors", "ind_clear_height_ft": "Clear height",
    "ind_office_rate": "Office rate", "ind_yard_rate": "Yard rate",
}
# Percent fields bounded to 0–100 (entered as a display %, e.g. 65 for 65%).
_PERCENT_FIELDS = {
    "expense_ratio": "Expense ratio", "vacancy_rate": "Vacancy rate",
    "hotel_occupancy": "Occupancy", "market_cap_rate": "Market cap rate",
    "exit_cap_rate": "Exit cap rate",
}


def _as_number(v):
    """Coerce a raw form value to float, or None when blank/non-numeric."""
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def validate_property_form(values):
    """Return an error message if the form can't be saved, else None.

    Required: an address, a property type (the whole analysis — field groups, per-type
    financing, cap-rate resolution — keys off it, and the new-entry form defaults it to
    blank, 4.12.1), and an asking price > 0. Numeric sanity (4.12.3): money/size/count
    fields can't be negative, percent ratios must be 0–100%, and NOI growth −100–100%.
    Floors, when entered, must be at least 1. This is the authoritative gate — the form's
    inline per-field validators mirror these rules for live feedback, but a save always
    re-checks here so invalid data can never be persisted. Blank optional fields pass."""
    if not (values.get("address") or "").strip():
        return "Address is required to save."
    asking = _as_number(values.get("asking_price"))
    if asking is None or asking <= 0:
        return "Asking price must be greater than 0."
    if not (values.get("property_type") or "").strip():
        return "Select a property type to save."

    for field, label in _NON_NEGATIVE_FIELDS.items():
        n = _as_number(values.get(field))
        if n is not None and n < 0:
            return f"{label} can't be negative."
    for field, label in _PERCENT_FIELDS.items():
        n = _as_number(values.get(field))
        if n is not None and not (0 <= n <= 100):
            return f"{label} must be between 0 and 100%."
    growth = _as_number(values.get("noi_growth_rate"))
    if growth is not None and not (-100 <= growth <= 100):
        return "NOI growth must be between -100 and 100%."
    floors = _as_number(values.get("floors"))
    if floors is not None and floors < 1:
        return "Floors must be at least 1."
    return None


# ── Form values → PropertyInput (4.1/4.4/4.7.2/4.9.4) ────────────────────────

def _fv(values, name, default=None):
    """Value for `name`, falling back to `default` when blank/missing (mirrors app._fval)."""
    v = values.get(name)
    return v if v not in ("", None) else default


def _num(values, name, default=0.0):
    return float(_fv(values, name, default) or default)


def _int(values, name, default=0):
    return int(_fv(values, name, default) or default)


def unit_mix_from(values):
    """Build a UnitMix from the form's unit-count + floors fields."""
    return UnitMix(
        bachelor=_int(values, "um_bachelor"), one_br=_int(values, "um_one_br"),
        two_br=_int(values, "um_two_br"), three_br=_int(values, "um_three_br"),
        four_br=_int(values, "um_four_br"), unknown=_int(values, "um_unknown"),
        floors=_int(values, "floors", 1) or 1,
    )


def build_property_input(values, fin):
    """Map a plain form-values dict + a resolved financing block into a PropertyInput.

    Down payment / interest rate / amortization / hold period ALL come from `fin` (the
    global, house-wide financing — never per-property, 4.9.4). Rent user-entered flags are
    set from whether the field was filled (4.7.2); overrides (expense/vacancy/noi, caps)
    pass through as fractions. `values` are raw field values (blank → None), exactly what
    app._fval returns."""
    um = unit_mix_from(values)
    asking = _num(values, "asking_price", 0)
    comm_rent = _fv(values, "commercial_rent")
    res_rent = _fv(values, "residential_rent")

    def pct(name):
        return pct_to_fraction(_fv(values, name))

    return PropertyInput(
        original_price=float(_fv(values, "original_price", asking) or asking), asking_price=asking,
        total_sq_ft=_num(values, "total_sq_ft", 0),
        property_taxes=_num(values, "property_taxes", 0),
        down_payment_pct=fin["down_payment_pct"], interest_rate=fin["interest_rate"],
        term_years=fin["term_years"], hold_years=fin["hold_years"],
        address=(_fv(values, "address", "") or "").strip(), mls_number=_fv(values, "mls_number", "") or "",
        city=_fv(values, "city"), province=_fv(values, "province"),
        property_type=_fv(values, "property_type"), status=_fv(values, "status", "active"),
        lease_type=_fv(values, "lease_type", "Normal"),
        listing_date=_fv(values, "listing_date") or date.today().isoformat(),
        construction_cost=_num(values, "construction_cost", 0),
        commercial_lease_expiry=_fv(values, "commercial_lease_expiry"),
        # Always carry the UnitMix (even with 0 units) so `floors` persists for every
        # building type — matching the re-analysis path, which builds a floors-only UnitMix
        # for unit-less properties. (`floors` is a building-wide attribute, not residential-only.)
        unit_mix=um,
        annual_rent=_fv(values, "annual_rent"),
        commercial_rent=comm_rent, commercial_rent_user_entered=comm_rent is not None,
        residential_rent=res_rent, residential_rent_user_entered=res_rent is not None,
        expense_ratio=pct("expense_ratio"), vacancy_rate=pct("vacancy_rate"),
        noi_growth_rate=pct("noi_growth_rate"),
        market_cap_rate=pct("market_cap_rate"), exit_cap_rate=pct("exit_cap_rate"),
        hotel_rooms=_int(values, "hotel_rooms", 0), hotel_adr=_fv(values, "hotel_adr"),
        hotel_occupancy=pct("hotel_occupancy"),
        ind_warehouse_sqft=_num(values, "ind_warehouse_sqft", 0),
        ind_office_sqft=_num(values, "ind_office_sqft", 0),
        ind_yard_sqft=_num(values, "ind_yard_sqft", 0),
        ind_dock_doors=_int(values, "ind_dock_doors", 0),
        ind_drive_in_doors=_int(values, "ind_drive_in_doors", 0),
        ind_clear_height_ft=_num(values, "ind_clear_height_ft", 0),
        ind_office_rate=_fv(values, "ind_office_rate"), ind_yard_rate=_fv(values, "ind_yard_rate"),
    )
