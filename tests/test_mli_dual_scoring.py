"""MLI dual scoring + acquisition-LTV / mixed-use-30%-rule routing."""
import pytest
from analysis.financing_config import (
    resolve_financing, mixed_use_commercial_gfa_share, _load_raw,
)
from scoring.scorer import PropertyScorer


@pytest.fixture(autouse=True)
def _fresh_cfg():
    _load_raw(force_reload=True)


# ── Routing: acquisition LTV cap + Standard ranking + Select scenario ────────

def test_5plus_mf_at_or_above_1M_ranks_on_mli_standard_85():
    """A 5+ MF whose 75%-LTV loan >= $1M ranks on MLI Standard at 85% (never 95%)."""
    fin = resolve_financing(3_000_000, "Multi-Family", 6)   # 75%-loan $2.25M
    assert fin["financing_scenario"] == "mli_standard"
    assert fin["max_ltv"] == 0.85
    assert fin["term_years"] == 40
    assert fin["covenant_dscr"] == 1.2


def test_5plus_mf_small_balance_reverts_conventional():
    """Fix A: a 5+ MF whose 75%-LTV loan < $1M finances conventionally (75% LTV),
    keyed on the loan amount, not price."""
    fin = resolve_financing(500_000, "Multi-Family", 6)     # 75%-loan $375k < $1M
    assert fin["financing_scenario"] == "type"
    assert fin["max_ltv"] == 0.75
    assert fin["select"] is None
    assert fin["small_balance_flag"] is True


def test_select_scenario_capped_at_85_tier_amort():
    """Select upside is 85% LTV (not 95%), 45yr modelled (70pt tier, not 50), 1.10."""
    sel = resolve_financing(3_000_000, "Multi-Family", 6)["select"]
    assert sel["max_ltv"] == 0.85
    assert sel["term_years"] == 45
    assert sel["covenant_dscr"] == 1.1
    assert sel["amort_by_points"] == {"50": 40, "70": 45, "100": 50}
    assert "95% LTV requires" in sel["label"]


def test_no_95pct_ltv_anywhere_in_scored_mf():
    fin = resolve_financing(5_000_000, "Multi-Family", 20)
    assert fin["max_ltv"] == 0.85 and fin["select"]["max_ltv"] == 0.85


# ── Mixed-use 30% rule ────────────────────────────────────────────────────────

def _mu(price, units, floors):
    share = mixed_use_commercial_gfa_share("Mixed-Use", floors)
    return resolve_financing(price, "Mixed-Use", units, commercial_gfa_share=share)

def test_mixed_use_eligible_under_30pct_with_5plus_units():
    fin = _mu(2_000_000, 5, floors=4)          # 1/4 = 25% ≤ 30%
    assert fin["financing_scenario"] == "mli_standard"
    assert fin["cmhc_eligible"] is True
    assert "30% rule" in fin["mli_eligibility"]

def test_mixed_use_over_30pct_is_conventional():
    fin = _mu(2_000_000, 5, floors=2)          # 1/2 = 50% > 30%
    assert fin["financing_scenario"] == "type"
    assert fin["select"] is None

def test_mixed_use_eligible_but_small_balance_reverts_conventional():
    # Passes the 30% gate (4 floors) but 75%-LTV loan = $562k < $1M → the uniform
    # small-balance floor reverts it to conventional (no MLI on a sub-$1M loan).
    fin = _mu(750_000, 5, floors=4)
    assert fin["financing_scenario"] == "type"
    assert fin["small_balance_flag"] is True
    assert fin["select"] is None
    assert "small-balance" in fin["mli_eligibility"]

def test_mixed_use_under_5_residential_units_conventional():
    fin = _mu(2_000_000, 3, floors=4)
    assert fin["financing_scenario"] == "type"

def test_mixed_use_unknown_share_is_undetermined_conventional():
    fin = resolve_financing(2_000_000, "Mixed-Use", 6, commercial_gfa_share=None)
    assert fin["financing_scenario"] == "type"
    assert "undetermined" in fin["mli_eligibility"]

def test_non_residential_types_never_eligible():
    for t in ("Office", "Retail", "Industrial", "Hotel"):
        fin = resolve_financing(2_000_000, t, 0)
        assert fin["cmhc_eligible"] is False
        assert fin["select"] is None


# ── Dual scoring ─────────────────────────────────────────────────────────────

def _record(select_results=True):
    base_rows = [
        {"metric": "Cap Rate", "value": "7.0%", "grade": "GOOD"},
        {"metric": "CoCR", "value": "8.0%", "grade": "GOOD"},
        {"metric": "DSCR", "value": "1.30", "grade": "GOOD"},
        {"metric": "IRR (10-Yr)", "value": "12.0%", "grade": "GOOD"},
        {"metric": "Equity Multiple", "value": "1.8x", "grade": "GOOD"},
        {"metric": "Annual Cash Flow", "value": "$15000", "grade": "GOOD"},
        {"metric": "NOI", "value": "$60,000.00", "grade": "GOOD"},
    ]
    rec = {
        "city": "Ottawa", "province": "ON", "asking_price": 2_000_000,
        "property_type": "Multi-Family", "unit_mix": {"one_br": 6, "floors": 3},
        "interest_rate": 0.0488, "down_payment_pct": 0.15,
        "financing_robustness": 55.0, "results": base_rows,
    }
    if select_results:
        sel = [dict(r) for r in base_rows]
        for r in sel:                              # Select: a touch stronger on returns
            if r["metric"] == "CoCR": r["value"] = "9.0%"
            if r["metric"] == "IRR (10-Yr)": r["value"] = "13.0%"
        rec["select_results"] = sel
        rec["select_financing_robustness"] = 62.0
    return rec


def test_dual_score_reports_standard_select_and_gap(make_store):
    scorer = PropertyScorer(make_store())
    result = scorer.score_property(_record())
    assert result["mli_eligible"] is True
    assert result["select_score"] is not None
    assert result["select_score"] >= result["score"]        # Select ≥ Standard
    assert result["select_gap"] == pytest.approx(
        round(result["select_score"] - result["score"], 1), abs=0.05)

def test_non_eligible_record_has_no_select(make_store):
    scorer = PropertyScorer(make_store())
    result = scorer.score_property(_record(select_results=False))
    assert result["mli_eligible"] is False
    assert result["select_score"] is None
    assert result["select_gap"] is None
