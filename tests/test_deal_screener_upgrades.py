"""
Deal-screener upgrades — per-type financing, break-even occupancy, rent
provenance tags, and the price-drop-velocity Deal Context read.

The financing values (T1-T8) were computed independently with the Canadian
semi-annual compounding formula: monthly_rate = (1 + annual_rate/2)^(1/6) − 1.
Monetary assertions use ±$5 (rounding); ratios ±0.005. Rates are band midpoints;
the qualifying rate = contract + stress_test_bump.
"""
import pytest
from unittest.mock import MagicMock

from analysis import financing_config as fc
from analysis.financing_config import resolve_financing, get_financing
from analysis.deal_financing import DealFinancing
from analysis.mortgage import MortgageCalculator
from analysis.metrics.cash_flow import DebtMetrics
from analysis.metrics.income import IncomeConfidenceMetrics
from analysis.rent_resolver import RentResolver
from analysis.screener_config import load_screener_config
from scoring.scorer import _deal_context_read
from models.property_input import PropertyInput, UnitMix

MONEY_TOL = 5.0
RATIO_TOL = 0.005


# ── Shared builder: resolve financing and instantiate the calculators ────────

def _build(price, gpr, vacancy, opex_ratio, app_type, units):
    fin = resolve_financing(price, app_type, units)
    egi        = gpr * (1 - vacancy)
    total_opex = egi * opex_ratio
    noi        = egi - total_opex
    mort = MortgageCalculator(price, fin["down_payment_pct"], fin["interest_rate"],
                              fin["term_years"], fin["hold_years"], province="ON")
    debt = DebtMetrics(
        noi, opex_ratio, mort.annual_mortgage, gpr,
        loan_amount=mort.loan_amount, interest_rate=fin["interest_rate"],
        term_years=fin["term_years"], compounding=mort.compounding,
        stress_rate_bump=fin["stress_test_bump"],
        stress_min_dscr=fin["dscr_floor"] or 1.20,
        egi=egi, total_operating_expenses=total_opex,
        fixed_expense_fraction=fin["fixed_expense_fraction"],
    )
    deal = DealFinancing(fin, price, noi, gpr=gpr, units=units,
                         compounding=mort.compounding)
    return fin, mort, debt, deal, noi


# ── T1-T8: one scenario per property type ────────────────────────────────────

CASES = [
    dict(id="T1_multi_family_1_4", type="Multi-Family", units=4,
         price=800_000, gpr=76_800, vacancy=0.03, opex=0.40,
         scenario="type", down=160_000, pmt=3_415.62, ads=40_987.44,
         dscr=1.09, stress_dscr=0.88, dscr_loan=None, max_loan=640_000,
         binding="n/a (GDS/TDS)", beo=0.914, beo_warn=True),
    dict(id="T2_multi_family_5plus_small", type="Multi-Family", units=6,
         price=500_000, gpr=90_300, vacancy=0.03, opex=0.40,
         scenario="conventional", down=125_000, pmt=2_343.83, ads=28_126.00,
         dscr=1.87, stress_dscr=1.56, dscr_loan=488_361, max_loan=375_000,
         binding="LTV", beo=0.655, beo_warn=False),
    dict(id="T3_multi_family_5plus_large", type="Multi-Family", units=16,
         price=2_400_000, gpr=288_000, vacancy=0.03, opex=0.42,
         scenario="mli_select", down=120_000, pmt=9_882.01, ads=118_584.16,
         dscr=1.37, stress_dscr=1.03, dscr_loan=2_132_644, max_loan=2_132_644,
         binding="DSCR", beo=0.793, beo_warn=False),
    dict(id="T4_mixed_use", type="Mixed-Use", units=0,
         price=900_000, gpr=96_000, vacancy=0.05, opex=0.38,
         scenario="type", down=225_000, pmt=4_368.97, ads=52_427.70,
         dscr=1.08, stress_dscr=0.91, dscr_loan=488_793, max_loan=488_793,
         binding="DSCR", beo=0.898, beo_warn=True),
    dict(id="T5_office", type="Office", units=0,
         price=1_800_000, gpr=333_000, vacancy=0.09, opex=0.41,
         scenario="type", down=630_000, pmt=8_663.85, ads=103_966.26,
         dscr=1.72, stress_dscr=1.48, dscr_loan=1_334_882, max_loan=1_170_000,
         binding="LTV", beo=0.604, beo_warn=False),
    dict(id="T6_retail", type="Retail", units=0,
         price=1_200_000, gpr=132_000, vacancy=0.06, opex=0.35,
         scenario="type", down=360_000, pmt=5_499.83, ads=65_997.96,
         dscr=1.22, stress_dscr=1.03, dscr_loan=690_016, max_loan=690_016,
         binding="DSCR", beo=0.796, beo_warn=False),
    dict(id="T7_industrial", type="Industrial", units=0,
         price=1_500_000, gpr=140_000, vacancy=0.04, opex=0.30,
         scenario="type", down=375_000, pmt=7_197.82, ads=86_373.89,
         dscr=1.09, stress_dscr=0.91, dscr_loan=821_788, max_loan=821_788,
         binding="DSCR", beo=0.893, beo_warn=True),
    dict(id="T8_hotel", type="Hotel", units=0,
         price=2_000_000, gpr=600_000, vacancy=0.35, opex=0.65,
         scenario="type", down=800_000, pmt=9_761.07, ads=117_132.90,
         dscr=1.17, stress_dscr=1.01, dscr_loan=868_149, max_loan=868_149,
         binding="DSCR", beo=0.602, beo_warn=False),
]


@pytest.mark.parametrize("c", CASES, ids=[c["id"] for c in CASES])
def test_financing_per_type(c):
    fin, mort, debt, deal, noi = _build(
        c["price"], c["gpr"], c["vacancy"], c["opex"], c["type"], c["units"])

    assert fin["financing_scenario"] == c["scenario"]
    assert mort.down_payment    == pytest.approx(c["down"], abs=MONEY_TOL)
    assert mort.monthly_payment == pytest.approx(c["pmt"],  abs=MONEY_TOL)
    assert mort.annual_mortgage == pytest.approx(c["ads"],  abs=MONEY_TOL)
    assert debt.dscr            == pytest.approx(c["dscr"], abs=RATIO_TOL)
    assert debt.stressed_dscr   == pytest.approx(c["stress_dscr"], abs=RATIO_TOL)

    if c["dscr_loan"] is None:
        assert deal.dscr_max_loan is None
    else:
        assert deal.dscr_max_loan == pytest.approx(c["dscr_loan"], abs=MONEY_TOL)
    assert deal.max_supportable_loan == pytest.approx(c["max_loan"], abs=MONEY_TOL)
    assert deal.binding_constraint == c["binding"]

    assert debt.break_even_point / 100 == pytest.approx(c["beo"], abs=RATIO_TOL)
    beo_row = next(r for r in debt.rows() if r.metric == "Break-Even Occupancy %")
    assert ("⚠" in beo_row.value) == c["beo_warn"]


def test_binding_constraint_coverage():
    """Deliberate coverage: LTV binds on T2/T5, DSCR on T3/T4/T6/T7/T8."""
    binds = {c["id"]: c["binding"] for c in CASES}
    assert binds["T2_multi_family_5plus_small"] == "LTV"
    assert binds["T5_office"] == "LTV"
    assert {binds[k] for k in
            ("T3_multi_family_5plus_large", "T4_mixed_use", "T6_retail",
             "T7_industrial", "T8_hotel")} == {"DSCR"}


# ── Multi-family panel details ───────────────────────────────────────────────

def test_t2_mli_panel_small_balance():
    fin, _, _, deal, _ = _build(500_000, 90_300, 0.03, 0.40, "Multi-Family", 6)
    metrics = {r.metric: r.value for r in deal.rows()}
    assert metrics["MLI Eligible"] == "Yes (5+ units)"
    assert "MLI Small-Balance Flag" in metrics          # loan < $1M
    assert metrics["Units"] == "6"
    assert deal.price_per_door == pytest.approx(83_333, abs=1.0)


def test_t3_mli_select_no_small_balance():
    fin, _, _, deal, _ = _build(2_400_000, 288_000, 0.03, 0.42, "Multi-Family", 16)
    metrics = {r.metric: r.value for r in deal.rows()}
    assert metrics["MLI Eligible"] == "Yes (5+ units)"
    assert "MLI Small-Balance Flag" not in metrics       # loan >= $1M
    assert deal.price_per_door == pytest.approx(150_000, abs=1.0)


def test_t1_mli_ineligible():
    _, _, _, deal, _ = _build(800_000, 76_800, 0.03, 0.40, "Multi-Family", 4)
    metrics = {r.metric: r.value for r in deal.rows()}
    assert metrics["MLI Eligible"] == "No"


def test_t4_mixed_use_no_mli_panel():
    _, _, _, deal, _ = _build(900_000, 96_000, 0.05, 0.38, "Mixed-Use", 0)
    metrics = {r.metric for r in deal.rows()}
    assert "MLI Eligible" not in metrics
    assert "Units" not in metrics


# ── T9: retail_office alias resolves to office ───────────────────────────────

def test_t9_retail_office_alias_equals_office():
    ro = resolve_financing(1_000_000, "Retail-Office", 0)
    of = resolve_financing(1_000_000, "Office", 0)
    for k in ("down_payment_pct", "interest_rate", "term_years", "hold_years",
              "max_ltv", "dscr_floor", "fixed_expense_fraction", "amort_years",
              "type_key", "financing_scenario"):
        assert ro[k] == of[k], f"{k}: {ro[k]!r} != {of[k]!r}"


# ── Regression: an empty property_types map reproduces defaults exactly ──────

def test_absent_property_types_reproduces_defaults(monkeypatch):
    raw = fc._load_raw()
    defaults = dict(raw["defaults"] if "defaults" in raw else raw)
    monkeypatch.setattr(fc, "_cache", {
        "defaults": defaults, "property_types": {},
        "stress_test_bump": raw.get("stress_test_bump", 0.02),
        "verified_date": raw.get("verified_date"),
    })
    for t in ("Office", "Retail", "Multi-Family", "Hotel", "Mixed-Use", None):
        block = get_financing(t, units=6)
        assert block["source"] == "defaults"
        assert block["down_payment_pct"] == defaults["down_payment_pct"]
        assert block["interest_rate"]    == defaults["interest_rate"]
        assert block["term_years"]       == defaults["term_years"]
        assert block["hold_years"]       == defaults["hold_years"]
    fc.load_financing_config(force_reload=True)


# ── T10: edge cases ──────────────────────────────────────────────────────────

def test_beo_over_100_caps_and_warns():
    # High mortgage relative to income → BEO computes > 1.0.
    debt = DebtMetrics(50_000, 0.40, 120_000, 100_000, fixed_expense_fraction=0.65)
    assert debt._beo_fraction > 1.0
    assert debt.break_even_point == pytest.approx(100.0)     # displayed cap
    row = next(r for r in debt.rows() if r.metric == "Break-Even Occupancy %")
    assert row.value.startswith("100.00%")
    assert "⚠" in row.value


def _resolver(comm_rates=None, res_rates=None):
    comm = MagicMock()
    comm.get_rent_per_sqft.side_effect = lambda city, prov, ptype: (
        comm_rates.get(ptype) if comm_rates else None)
    res = MagicMock()
    res.get_rates.return_value = res_rates
    return RentResolver(comm, res, None)


def _prop(**kwargs):
    defaults = dict(original_price=500_000, asking_price=500_000, total_sq_ft=5_000,
                    property_taxes=8_000, down_payment_pct=0.25, interest_rate=0.055,
                    term_years=25, hold_years=10)
    defaults.update(kwargs)
    return PropertyInput(**defaults)


def test_market_rent_line_flips_income_to_estimated():
    r = _resolver(res_rates={"one_br": 1_200, "two_br": 1_500})
    prop = _prop(city="Testville", province="ON", property_type="Residential",
                 unit_mix=UnitMix(one_br=2, two_br=1))
    rent, breakdown = r.resolve(prop)
    assert any(line.startswith("[M]") for line in breakdown)
    # Verified/estimated split must count [M] dollars as estimated — never 100%.
    conf = IncomeConfidenceMetrics(rent, r._advertised_income, r._imputed_lines)
    assert conf.verified_income_pct == pytest.approx(0.0)
    assert r._estimated_income == pytest.approx(rent)


def test_specified_rent_line_is_advertised():
    r = _resolver(res_rates={"one_br": 1_200})
    prop = _prop(city="Testville", province="ON", property_type="Residential",
                 unit_mix=UnitMix(one_br=2, one_br_rent=1_300))
    rent, breakdown = r.resolve(prop)
    assert any(line.startswith("[A]") for line in breakdown)
    assert r._advertised_income == pytest.approx(rent)
    conf = IncomeConfidenceMetrics(rent, r._advertised_income, r._imputed_lines)
    assert conf.verified_income_pct == pytest.approx(100.0)


# ── T10: Deal Context read — price-drop velocity + seller bleed ──────────────

def _read(price_drop_pct, dom_days, monthly_bleed, dom_band="normal",
          drop_band="modest", is_high_conf=True):
    return _deal_context_read(dom_band, drop_band, "moderate", is_high_conf,
                              price_drop_pct=price_drop_pct, dom_days=dom_days,
                              monthly_bleed=monthly_bleed,
                              screener_cfg=load_screener_config())


def test_verona_fast_drop_low_bleed_circumstantial():
    read = _read(16.67, 35, monthly_bleed=179)
    assert "circumstantial motivation" in read
    assert "financial pressure" not in read


def test_fast_drop_high_bleed_financial_pressure():
    read = _read(16.67, 35, monthly_bleed=5_000)
    assert "financial pressure" in read
    assert "circumstantial motivation" not in read


def test_small_drop_fires_neither():
    read = _read(5.0, 35, monthly_bleed=179, drop_band="none")
    assert "circumstantial motivation" not in read
    assert "financial pressure" not in read
    assert "No notable" in read


def test_saint_john_staleness_read_only():
    read = _read(0.0, 248, monthly_bleed=None, dom_band="stale",
                 drop_band="none", is_high_conf=False)
    assert "Extended time on market" in read
    assert "circumstantial motivation" not in read
    assert "financial pressure" not in read
