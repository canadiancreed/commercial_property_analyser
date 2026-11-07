"""Shared record ↔ model / report-row helpers.

The single source of truth for two mappings used by BOTH front-ends:
  * record_to_prop(record)            — stored dict  → PropertyInput (re-analysis)
  * build_report_row(record, scored, targets) — stored dict + scoring → report row

Previously these lived as PropertyMenu staticmethods and were copied into the desktop
POC. They now live here; `ui/menu.py` exposes them as PropertyMenu._record_to_prop /
_build_report_row (preserving that API), and poc_nicegui/app.py imports them directly.
"""
from datetime import date

import history_logic
from models.property_input import PropertyInput, UnitMix
from analysis.financing_config import resolve_financing, mixed_use_commercial_gfa_share


def record_to_prop(p: dict) -> PropertyInput:
    um_data   = p.get("unit_mix") or {}
    has_units = any(um_data.get(k, 0) for k in
                    ("bachelor", "one_br", "two_br", "three_br", "four_br", "unknown"))
    if has_units:
        unit_mix = UnitMix(
            bachelor=um_data.get("bachelor", 0), one_br=um_data.get("one_br", 0),
            two_br=um_data.get("two_br", 0), three_br=um_data.get("three_br", 0),
            four_br=um_data.get("four_br", 0), unknown=um_data.get("unknown", 0),
            floors=um_data.get("floors", p.get("floors", 1)),
        )
    else:
        unit_mix = UnitMix(floors=um_data.get("floors", p.get("floors", 1)))
    _units = unit_mix.total_units if unit_mix else 0
    _share = mixed_use_commercial_gfa_share(
        p.get("property_type"), unit_mix.floors if unit_mix else p.get("floors", 1))
    fin = resolve_financing(p.get("asking_price", 0), p.get("property_type"), _units,
                            commercial_gfa_share=_share)
    return PropertyInput(
        address=p["address"], mls_number=p.get("mls_number", ""),
        status=p.get("status", "active"),
        original_price=p.get("original_price", p.get("asking_price", 0)),
        asking_price=p.get("asking_price", 0), total_sq_ft=p.get("total_sq_ft", 0),
        property_taxes=p.get("property_taxes", 0),
        down_payment_pct=fin["down_payment_pct"], interest_rate=fin["interest_rate"],
        term_years=fin["term_years"], hold_years=fin["hold_years"],
        expense_ratio=p.get("expense_ratio", None), lease_type=p.get("lease_type", "Normal"),
        commercial_lease_expiry=p.get("commercial_lease_expiry"),
        construction_cost=p.get("construction_cost", 0) or 0,
        listing_date=p.get("listing_date", date.today().isoformat()),
        commercial_rent=p.get("commercial_rent") or None,
        residential_rent=p.get("residential_rent") or None,
        annual_rent=(p.get("annual_rent") or None) if not (
            p.get("commercial_rent") or p.get("residential_rent")) else None,
        city=p.get("city"), province=p.get("province"),
        property_type=p.get("property_type"), unit_mix=unit_mix,
        hotel_rooms=p.get("hotel_rooms", 0) or 0, hotel_adr=p.get("hotel_adr"),
        hotel_occupancy=p.get("hotel_occupancy"),
        ind_warehouse_sqft=p.get("ind_warehouse_sqft", 0) or 0,
        ind_office_sqft=p.get("ind_office_sqft", 0) or 0,
        ind_yard_sqft=p.get("ind_yard_sqft", 0) or 0,
        ind_dock_doors=p.get("ind_dock_doors", 0) or 0,
        ind_drive_in_doors=p.get("ind_drive_in_doors", 0) or 0,
        ind_clear_height_ft=p.get("ind_clear_height_ft", 0) or 0,
        ind_office_rate=p.get("ind_office_rate"), ind_yard_rate=p.get("ind_yard_rate"),
        vacancy_rate=p.get("vacancy_rate"), noi_growth_rate=p.get("noi_growth_rate"),
        commercial_rent_user_entered=p.get("commercial_rent_user_entered",
                                           p.get("rent_manually_entered", False)),
        residential_rent_user_entered=p.get("residential_rent_user_entered",
                                            p.get("rent_manually_entered", False)),
    )


def reanalyze_properties(store, resolver, analyzer_cls, predicate=None) -> dict:
    """Re-run analysis for stored properties and save the refreshed records in place.

    Mirrors the CLI `_reanalyze_all` core loop (minus the CLI-only console reporting):
    record → PropertyInput → analyzer → to_record(existing) → update_property. A
    ValueError means no market rate for that city yet (expected → skipped); any other
    exception is counted as an error. Pass `predicate(record)->bool` to limit the set
    (e.g. one city after a rate edit). Returns a counts dict plus an ``issues`` list —
    one entry per skipped/errored property ({address, mls, city, property_type, kind,
    reason}) so callers can show exactly which properties didn't update and why.
    """
    props = store.load_properties()
    updated = considered = 0
    issues = []   # per-property skip/error detail: {address, mls, city, kind, reason}

    def _detail(p, kind, exc):
        reason = str(exc).strip()
        if kind == "error":
            reason = f"{type(exc).__name__}: {reason}" if reason else type(exc).__name__
        elif not reason:
            reason = "No market rent rate for this city yet."
        return {"address": p.get("address") or "—", "mls": p.get("mls_number") or "",
                "city": p.get("city") or "", "property_type": p.get("property_type") or "",
                "kind": kind, "reason": reason}

    for i, p in enumerate(props):
        if predicate is not None and not predicate(p):
            continue
        considered += 1
        try:
            prop   = record_to_prop(p)
            record = analyzer_cls(prop, resolver).to_record(existing=p)
            if p.get("notes"):
                record["notes"] = p["notes"]
            store.update_property(i, record)
            updated += 1
        except ValueError as e:
            issues.append(_detail(p, "skipped", e))   # no market rent rates yet — expected
        except Exception as e:
            issues.append(_detail(p, "error", e))
    skipped = sum(1 for x in issues if x["kind"] == "skipped")
    errors  = sum(1 for x in issues if x["kind"] == "error")
    return {"updated": updated, "skipped": skipped, "errors": errors,
            "considered": considered, "total": len(props), "issues": issues}


def build_report_row(p: dict, scored: dict, targets: dict) -> dict:
    return {
        "address": p.get("address", "—"), "mls": p.get("mls_number", "—"),
        "status": p.get("status", "—"), "city": p.get("city") or "",
        "province": p.get("province") or "", "type": p.get("property_type") or "—",
        "asking": p.get("asking_price", 0), "sqft": p.get("total_sq_ft", 0),
        "listed": p.get("listing_date", "—"), "analyzed": p.get("analyzed_on") or "—",
        "notes": p.get("notes") or "", "construction": p.get("construction_cost") or 0,
        "dist_km": scored.get("dist_km"), "dist_centre": scored.get("dist_centre") or "",
        "comm_rent": p.get("commercial_rent") or 0, "res_rent": p.get("residential_rent") or 0,
        "score": scored.get("score"), "breakdown": scored.get("breakdown", {}),
        "weights": scored.get("weights", {}),
        "robustness_pending": scored.get("robustness_pending", False),
        "mli_eligible": scored.get("mli_eligible", False),
        "select_score": scored.get("select_score"), "select_gap": scored.get("select_gap"),
        "cap_rate": scored.get("cap_rate", 0), "coc": scored.get("coc", 0),
        "dscr": scored.get("dscr", 0), "irr": scored.get("irr"), "em": scored.get("em", 0),
        "cf_annual": scored.get("cf_annual", 0), "price_drop": scored.get("price_drop", 0),
        "dom": scored.get("dom", 0), "dom_band": scored.get("dom_band"),
        "price_drop_band": scored.get("price_drop_band"),
        "liquidity_band": scored.get("liquidity_band"),
        "market_signal_multiplier": scored.get("market_signal_multiplier"),
        "deal_context_read": scored.get("deal_context_read"),
        "verified_income_pct": scored.get("verified_income_pct"),
        "original": p.get("original_price", 0), "taxes": p.get("property_taxes", 0),
        "down_pct": p.get("down_payment_pct", 0), "rate": p.get("interest_rate", 0),
        "term": p.get("term_years", 0), "hold": p.get("hold_years", 0),
        "expense_ratio": p.get("expense_ratio", 0), "lease_type": p.get("lease_type", ""),
        "results": p.get("results", []), "income_confidence": p.get("income_confidence"),
        "income_size_band": p.get("income_size_band"), "targets": targets,
        "hotel_rooms": p.get("hotel_rooms", 0) or 0, "hotel_adr": p.get("hotel_adr") or 0,
        "hotel_occ": p.get("hotel_occupancy") or 0,
        "rent_breakdown": p.get("rent_breakdown", []),
        "history": history_logic.build_timeline(p),
    }
