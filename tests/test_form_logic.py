"""
Unit tests for poc_nicegui/form_logic.py — the pure, UI-free logic extracted from the
desktop app (poc_nicegui/app.py), which itself can't be imported in tests (boot side
effects). These cover the desktop-layer behaviours shipped across v4.1–v4.9:

  * portfolio address search (4.7.1)
  * draft-over-record prefill + type-switch draft preservation (4.7.2, 4.9.4)
  * rent prefill provenance guard (4.7.2)
  * percent + per-asset-class financing field coercion (4.9.0)
  * save-time validation (4.4)
  * form values → PropertyInput mapping, financing/hold from global (4.1/4.4/4.7.2/4.9.4)
"""
import pytest

import form_logic as fl

FIN = {"down_payment_pct": 0.2, "interest_rate": 0.05, "term_years": 25, "hold_years": 10}


# ── filter_rows (4.7.1) ──────────────────────────────────────────────────────

def test_filter_rows_substring_case_insensitive():
    rows = [{"address": "123 Bridge St"}, {"address": "9 Main Ave"}, {"address": None}]
    assert fl.filter_rows(rows, "bridge") == [{"address": "123 Bridge St"}]
    assert fl.filter_rows(rows, "MAIN") == [{"address": "9 Main Ave"}]


def test_filter_rows_blank_returns_all():
    rows = [{"address": "a"}, {"address": "b"}]
    assert fl.filter_rows(rows, "") == rows
    assert fl.filter_rows(rows, "   ") == rows
    assert fl.filter_rows(rows, None) == rows


def test_filter_rows_no_match_is_empty():
    assert fl.filter_rows([{"address": "a"}], "zzz") == []


# ── prefill_value / prefill_pct (4.7.2, 4.9.4) ───────────────────────────────

def test_prefill_draft_over_record():
    assert fl.prefill_value("x", {"x": "draft"}, {"x": "rec"}) == "draft"


def test_prefill_record_when_no_draft():
    assert fl.prefill_value("x", {}, {"x": "rec"}) == "rec"


def test_prefill_default_when_empty_or_missing():
    assert fl.prefill_value("x", {"x": ""}, {}, default="d") == "d"
    assert fl.prefill_value("x", {}, {"x": None}, default="d") == "d"
    assert fl.prefill_value("x", {}, {}, default="d") == "d"


def test_prefill_pct_converts_record_fraction():
    assert fl.prefill_pct("r", {}, {"r": 0.65}) == 65.0


def test_prefill_pct_draft_is_display_value():
    assert fl.prefill_pct("r", {"r": 42}, {"r": 0.65}) == 42   # draft already a display %


def test_prefill_pct_none_when_absent():
    assert fl.prefill_pct("r", {}, {}) is None
    assert fl.prefill_pct("r", {}, {"r": None}) is None


# ── rent_prefills provenance (4.7.2) ─────────────────────────────────────────

def test_rent_prefills_skip_market_estimate():
    rec = {"commercial_rent": 100000, "commercial_rent_user_entered": False,
           "residential_rent": 50000, "residential_rent_user_entered": False}
    rp = fl.rent_prefills({}, rec)
    assert rp["commercial_rent"] is None and rp["residential_rent"] is None


def test_rent_prefills_use_owner_entered():
    rec = {"commercial_rent": 100000, "commercial_rent_user_entered": True}
    assert fl.rent_prefills({}, rec)["commercial_rent"] == 100000


def test_rent_prefills_draft_overrides():
    rec = {"commercial_rent": 100000, "commercial_rent_user_entered": False}
    assert fl.rent_prefills({"commercial_rent": 77}, rec)["commercial_rent"] == 77


def test_rent_prefills_annual_guarded_by_component():
    assert fl.rent_prefills({}, {"commercial_rent": 100000, "annual_rent": 9})["annual_rent"] is None
    assert fl.rent_prefills({}, {"annual_rent": 9})["annual_rent"] == 9
    assert fl.rent_prefills({"annual_rent": 5}, {"commercial_rent": 100000, "annual_rent": 9})["annual_rent"] == 5


# ── coercion ─────────────────────────────────────────────────────────────────

def test_pct_to_fraction():
    assert fl.pct_to_fraction(65) == 0.65
    assert fl.pct_to_fraction(None) is None
    assert fl.pct_to_fraction("") is None


def test_coerce_financing_field_kinds():
    assert fl.coerce_financing_field(6.5, "pct") == 0.065
    assert fl.coerce_financing_field(25.0, "int") == 25
    assert fl.coerce_financing_field(1.2, "ratio") == 1.2


def test_coerce_blank_ratio_clears_blank_other_skips():
    assert fl.coerce_financing_field("", "ratio") is None
    assert fl.coerce_financing_field(None, "ratio") is None
    assert fl.coerce_financing_field("", "pct") is fl.SKIP
    assert fl.coerce_financing_field(None, "int") is fl.SKIP


# ── validation (4.4) ─────────────────────────────────────────────────────────

def test_validate_requires_address():
    assert "Address" in fl.validate_property_form({"address": "", "asking_price": 100})
    assert "Address" in fl.validate_property_form({"asking_price": 100})


def test_validate_requires_positive_price():
    assert "Asking" in fl.validate_property_form({"address": "x", "asking_price": 0})
    assert "Asking" in fl.validate_property_form({"address": "x", "asking_price": None})
    assert "Asking" in fl.validate_property_form({"address": "x", "asking_price": -5})


def test_validate_ok_returns_none():
    assert fl.validate_property_form({"address": "x", "asking_price": 100}) is None


# ── build_property_input (4.1/4.4/4.7.2/4.9.4) ───────────────────────────────

def test_build_uses_global_financing():
    p = fl.build_property_input({"address": "1 A St", "asking_price": 500000, "property_type": "Office"}, FIN)
    assert (p.down_payment_pct, p.interest_rate, p.term_years, p.hold_years) == (0.2, 0.05, 25, 10)
    assert p.asking_price == 500000 and p.address == "1 A St" and p.property_type == "Office"


def test_build_hold_years_always_global_never_form():
    # A stray per-property hold_years in the form values must be ignored (4.9.4).
    p = fl.build_property_input({"address": "a", "asking_price": 500000, "hold_years": 99}, FIN)
    assert p.hold_years == 10


def test_build_rent_user_entered_flags():
    p = fl.build_property_input({"address": "a", "asking_price": 500000, "commercial_rent": 120000}, FIN)
    assert p.commercial_rent == 120000 and p.commercial_rent_user_entered is True
    p2 = fl.build_property_input({"address": "a", "asking_price": 500000}, FIN)
    assert p2.commercial_rent is None and p2.commercial_rent_user_entered is False


def test_build_pct_overrides_to_fractions():
    p = fl.build_property_input({"address": "a", "asking_price": 500000,
                                 "expense_ratio": 40, "vacancy_rate": 5, "noi_growth_rate": 2}, FIN)
    assert p.expense_ratio == 0.4 and p.vacancy_rate == 0.05 and p.noi_growth_rate == 0.02


def test_build_unit_mix_present_and_absent():
    p = fl.build_property_input({"address": "a", "asking_price": 500000, "um_two_br": 4, "floors": 2}, FIN)
    assert p.unit_mix is not None and p.unit_mix.total_units == 4 and p.unit_mix.floors == 2
    p2 = fl.build_property_input({"address": "a", "asking_price": 500000}, FIN)
    assert p2.unit_mix is None


def test_build_original_price_defaults_to_asking():
    p = fl.build_property_input({"address": "a", "asking_price": 300000}, FIN)
    assert p.original_price == 300000


def test_build_strips_address():
    p = fl.build_property_input({"address": "  5 Main St  ", "asking_price": 500000}, FIN)
    assert p.address == "5 Main St"
