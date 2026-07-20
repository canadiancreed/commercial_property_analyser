"""
Revision 2 — mixed-use component engine, refi headroom, config display/notes
split, and lease-expiry field.

Money ±$5, ratios ±0.005. Values computed independently with the Canadian
semi-annual compounding formula and the config: residential_vacancy 0.04,
commercial_vacancy 0.125, residential 0.40, NNN 0.08, gross commercial 0.40,
mixed_use block 75% LTV / 6.125% / 25yr / dscr 1.25 / f 0.55, stress 0.02.
"""
import pytest
from unittest.mock import MagicMock

from models.property_input import PropertyInput
from models.constants import EXPENSE_RATIO_DEFAULTS
from analysis.financing_config import resolve_financing
from analysis.rent_resolver import RentResolver
from analysis.analyzer import CommercialPropertyAnalyzer
from analysis.deal_financing import DealFinancing
from analysis.metrics.income import MixedUseComponents

MONEY = 5.0
RATIO = 0.005


def _analyze(app_type, *, price, comm=None, res=None, lease="Normal",
             expiry=None, units=0):
    fin = resolve_financing(price, app_type, units)
    prop = PropertyInput(
        original_price=price, asking_price=price, total_sq_ft=5000, property_taxes=7000,
        down_payment_pct=fin["down_payment_pct"], interest_rate=fin["interest_rate"],
        term_years=fin["term_years"], hold_years=fin["hold_years"],
        property_type=app_type, lease_type=lease,
        commercial_rent=comm, residential_rent=res,
        commercial_rent_user_entered=comm is not None,
        residential_rent_user_entered=res is not None,
        commercial_lease_expiry=expiry,
        city="Testville", province="ON", listing_date="2026-01-01",
    )
    return CommercialPropertyAnalyzer(prop, RentResolver(MagicMock(), MagicMock(), None))


def _row_values(analyzer):
    return {r.metric: r.value for r in analyzer.report()}


# ── T-M1 / T-M2: full component engine end-to-end ────────────────────────────

def test_tm1_nnn_mixed_use_bayside():
    a = _analyze("Mixed-Use", price=730_000, comm=40_000, res=65_400, lease="NNN")
    m = a.mixed_use
    assert m.comm_egi == pytest.approx(35_000.00, abs=MONEY)
    assert m.res_egi  == pytest.approx(62_784.00, abs=MONEY)
    assert m.egi      == pytest.approx(97_784.00, abs=MONEY)
    assert m.blended_vacancy       == pytest.approx(0.0723, abs=RATIO)
    assert m.total_opex            == pytest.approx(27_913.60, abs=MONEY)
    assert m.blended_expense_ratio == pytest.approx(0.2855, abs=RATIO)
    assert m.noi      == pytest.approx(69_870.40, abs=MONEY)
    assert a.income.cap_rate == pytest.approx(9.57, abs=0.02)
    assert m.commercial_share == pytest.approx(0.3795, abs=RATIO)
    assert m.commercial_majority is False

    assert a.mortgage.loan_amount    == pytest.approx(547_500, abs=MONEY)
    assert a.mortgage.monthly_payment == pytest.approx(3_543.72, abs=MONEY)
    assert a.mortgage.annual_mortgage == pytest.approx(42_524.69, abs=MONEY)
    assert a.debt.dscr          == pytest.approx(1.643, abs=RATIO)
    assert a.debt.stressed_dscr == pytest.approx(1.379, abs=RATIO)
    assert a.deal_financing.dscr_max_loan == pytest.approx(603_992.55, abs=MONEY)
    assert a.deal_financing.binding_constraint == "LTV"
    assert a.deal_financing.refi_headroom == pytest.approx(56_492.55, abs=MONEY)
    assert a.debt.break_even_point / 100 == pytest.approx(0.630, abs=RATIO)
    # The bug being fixed: prior single-ratio engine gave NOI $88,240.88.
    assert abs(m.noi - 88_240.88) > 1_000


def test_tm2_gross_mixed_use_napanee():
    a = _analyze("Mixed-Use", price=590_000, comm=32_801.50, res=72_300, lease="Normal")
    m = a.mixed_use
    assert m.comm_egi == pytest.approx(28_701.31, abs=MONEY)
    assert m.res_egi  == pytest.approx(69_408.00, abs=MONEY)
    assert m.egi      == pytest.approx(98_109.31, abs=MONEY)
    assert m.blended_vacancy       == pytest.approx(0.0665, abs=RATIO)
    assert m.total_opex            == pytest.approx(39_243.73, abs=MONEY)
    assert m.blended_expense_ratio == pytest.approx(0.4000, abs=RATIO)
    assert m.noi      == pytest.approx(58_865.59, abs=MONEY)
    assert a.income.cap_rate == pytest.approx(9.98, abs=0.02)
    assert a.mortgage.annual_mortgage == pytest.approx(34_369.27, abs=MONEY)
    assert a.debt.dscr          == pytest.approx(1.713, abs=RATIO)
    assert a.debt.stressed_dscr == pytest.approx(1.437, abs=RATIO)
    assert a.deal_financing.dscr_max_loan == pytest.approx(508_861.79, abs=MONEY)
    assert a.deal_financing.binding_constraint == "LTV"
    assert a.deal_financing.refi_headroom == pytest.approx(66_361.79, abs=MONEY)
    assert a.debt.break_even_point / 100 == pytest.approx(0.649, abs=RATIO)
    assert m.commercial_share == pytest.approx(0.3121, abs=RATIO)
    assert m.commercial_majority is False


# ── T-M3: commercial-majority flag ───────────────────────────────────────────

def test_tm3_commercial_majority_flag():
    a = _analyze("Mixed-Use", price=800_000, comm=60_000, res=45_000, lease="Normal")
    assert a.mixed_use.commercial_share == pytest.approx(0.5714, abs=RATIO)
    assert a.mixed_use.commercial_majority is True
    vals = _row_values(a)
    assert "Commercial Majority" in vals
    assert "commercial, not mixed-use" in vals["Commercial Majority"]
    # T-M1 fixture (37.95%) must NOT fire.
    a2 = _analyze("Mixed-Use", price=730_000, comm=40_000, res=65_400, lease="NNN")
    assert a2.mixed_use.commercial_majority is False
    assert "Commercial Majority" not in _row_values(a2)


# ── T-M4: NNN guard specificity ──────────────────────────────────────────────

def test_tm4_nnn_guard_lowers_only_commercial():
    nnn    = _analyze("Mixed-Use", price=730_000, comm=40_000, res=65_400, lease="NNN")
    normal = _analyze("Mixed-Use", price=730_000, comm=40_000, res=65_400, lease="Normal")
    # Same fixture, Normal → commercial opex uses gross default → NOI drops.
    assert normal.mixed_use.noi < nnn.mixed_use.noi
    assert normal.mixed_use.noi == pytest.approx(58_670.40, abs=MONEY)
    # Residential opex is identical under both tags — the tag never touches it.
    assert normal.mixed_use.res_opex == pytest.approx(nnn.mixed_use.res_opex, abs=0.01)
    assert nnn.mixed_use.res_opex == pytest.approx(62_784.00 * 0.40, abs=0.01)


def test_tm4_pure_residential_ignores_nnn_tag():
    # A residential asset class can't be NNN (Ontario RTA) — the tag must not
    # collapse its expense ratio to the ~0.08 NNN default.
    for t in ("Multi-Family", "Residential"):
        p = PropertyInput(original_price=1, asking_price=1, total_sq_ft=1, property_taxes=0,
                          down_payment_pct=0.2, interest_rate=0.05, term_years=25,
                          property_type=t, lease_type="NNN")
        assert p.expense_ratio == EXPENSE_RATIO_DEFAULTS[t.lower()]
        assert p.expense_ratio != EXPENSE_RATIO_DEFAULTS["nnn"]


def test_tm4_component_residential_ratio_is_tag_invariant():
    kw = dict(comm_vacancy=0.125, res_vacancy=0.04, comm_gross_ratio=0.40,
              comm_nnn_ratio=0.08, res_ratio=0.40, majority_threshold=0.50)
    a = MixedUseComponents(40_000, 65_400, "NNN", **kw)
    b = MixedUseComponents(40_000, 65_400, "Normal", **kw)
    assert a.res_opex == pytest.approx(b.res_opex)      # residential unaffected
    assert a.comm_opex < b.comm_opex                    # commercial lowered by NNN


# ── T-M5: refi headroom, both binding outcomes + null floor ──────────────────

def _deal(app_type, price, gpr, vacancy, opex_ratio, units=0):
    fin = resolve_financing(price, app_type, units)
    egi = gpr * (1 - vacancy)
    noi = egi - egi * opex_ratio
    return DealFinancing(fin, price, noi, gpr=gpr, units=units)


def test_tm5_refi_headroom_ltv_binding():
    d = _deal("Multi-Family", 500_000, 90_300, 0.03, 0.40, units=6)  # Verona
    assert d.binding_constraint == "LTV"
    assert d.refi_headroom == pytest.approx(113_361.09, abs=MONEY)   # 488,361.09 − 375,000


def test_tm5_refi_headroom_omitted_when_dscr_binds():
    d = _deal("Retail", 1_200_000, 132_000, 0.06, 0.35)              # prior T6
    assert d.binding_constraint == "DSCR"
    assert d.refi_headroom is None


def test_tm5_refi_headroom_absent_without_dscr_floor():
    d = _deal("Multi-Family", 800_000, 76_800, 0.03, 0.40, units=4)  # 1-4 unit, no floor
    assert d.dscr_floor is None
    assert d.refi_headroom is None


# ── T-M6: display/notes split — internal prose can never leak ────────────────

def _small_balance_fin(with_display):
    fin = resolve_financing(500_000, "Multi-Family", 6)   # mf5plus, small balance
    assert fin["small_balance_flag"] is True
    if not with_display:
        fin = dict(fin)
        fin["cmhc"] = {k: v for k, v in fin["cmhc"].items() if k != "display"}
    return fin


def test_tm6_small_balance_renders_display_copy():
    d = DealFinancing(_small_balance_fin(True), 500_000, 52_554.60, gpr=90_300, units=6)
    vals = {r.metric: r.value for r in d.rows()}
    assert vals["MLI Small-Balance Flag"] == \
        "Loan under $1M — CMHC costs/timeline rarely pencil at this size; shown as secondary option."


def test_tm6_no_display_renders_nothing():
    d = DealFinancing(_small_balance_fin(False), 500_000, 52_554.60, gpr=90_300, units=6)
    assert "MLI Small-Balance Flag" not in {r.metric for r in d.rows()}


def test_tm6_internal_prose_never_appears_on_any_card():
    fixtures = [
        _analyze("Mixed-Use", price=730_000, comm=40_000, res=65_400, lease="NNN"),
        _analyze("Mixed-Use", price=590_000, comm=32_801.50, res=72_300, lease="Normal"),
        _analyze("Office", price=1_800_000, comm=333_000, lease="Normal"),
    ]
    d = DealFinancing(_small_balance_fin(True), 500_000, 52_554.60, gpr=90_300, units=6)
    blob = " ".join(r.value for a in fixtures for r in a.report())
    blob += " " + " ".join(r.value for r in d.rows())
    assert "min_practical_loan" not in blob


# ── T-M7: commercial lease expiry ────────────────────────────────────────────

def test_tm7_lease_expiry_present_and_absent():
    with_exp = _analyze("Mixed-Use", price=730_000, comm=40_000, res=65_400,
                        lease="NNN", expiry="2029-06-30")
    assert _row_values(with_exp)["Commercial Lease Expiry"] == "2029-06-30"
    without = _analyze("Mixed-Use", price=730_000, comm=40_000, res=65_400, lease="NNN")
    assert _row_values(without)["Commercial Lease Expiry"] == "unknown ⚠"


def test_tm7_non_mixed_use_never_shows_lease_expiry():
    a = _analyze("Office", price=1_800_000, comm=333_000, lease="Normal")
    assert "Commercial Lease Expiry" not in _row_values(a)


# ── T-M8: isolation — component config has zero effect outside mixed_use ──────

def test_tm8_non_mixed_use_untouched():
    office = _analyze("Office", price=1_800_000, comm=333_000, lease="Normal")
    assert office.mixed_use is None
    assert office.income.vacancy_rate == pytest.approx(0.14)      # office default, not component
    assert "Commercial Share of GPR" not in _row_values(office)
    # LTV binds on office → refi headroom present (the only additive change).
    assert office.deal_financing.refi_headroom is not None
