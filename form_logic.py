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


# ── Validation (4.4) ─────────────────────────────────────────────────────────

def validate_property_form(values):
    """Return an error message if the form can't be saved, else None: an address is
    required and the asking price must be > 0."""
    if not (values.get("address") or "").strip():
        return "Address is required to save."
    try:
        asking = float(values.get("asking_price") or 0)
    except (TypeError, ValueError):
        asking = 0
    if asking <= 0:
        return "Asking price must be greater than 0."
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
    units = um.total_units
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
        unit_mix=um if units else None,
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
