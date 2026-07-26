import pytest
from unittest.mock import MagicMock
from datetime import date
from models.property_input import PropertyInput, UnitMix
from analysis.analyzer import CommercialPropertyAnalyzer


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_resolver(annual_rent=60_000):
    resolver = MagicMock()
    resolver.resolve.return_value = (annual_rent, ["$60k/yr direct"])
    resolver._comm_rent          = annual_rent
    resolver._res_rent           = 0.0
    resolver._city_rent_per_sqft = 12.0
    resolver._comm_sq_ft         = None
    return resolver


def _make_prop(**kwargs):
    defaults = dict(
        address="1 Main St, Ottawa, ON",
        mls_number="MLS-001",
        status="active",
        original_price=500_000,
        asking_price=480_000,
        total_sq_ft=5000,
        property_taxes=8_000,
        down_payment_pct=0.25,
        interest_rate=0.055,
        term_years=25,
        hold_years=10,
        expense_ratio=0.40,
        lease_type="Normal",
        listing_date="2024-01-01",
        city="Ottawa",
        province="ON",
    )
    defaults.update(kwargs)
    return PropertyInput(**defaults)


# ── Full analysis (with rent) ─────────────────────────────────────────────────

class TestAnalyzerWithRent:
    def test_constructs_without_error(self):
        prop = _make_prop(annual_rent=60_000)
        a = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        assert a._has_rent is True

    def test_all_metric_groups_set(self):
        prop = _make_prop(annual_rent=60_000)
        a = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        assert a.income   is not None
        assert a.exit     is not None
        assert a.cashflow is not None
        assert a.debt     is not None
        assert a.returns  is not None
        assert a.market   is not None

    def test_report_returns_list_of_rows(self):
        from models.report_row import ReportRow
        prop = _make_prop(annual_rent=60_000)
        a = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        rows = a.report()
        assert len(rows) > 0
        assert all(isinstance(r, ReportRow) for r in rows)

    def test_report_has_key_metrics(self):
        prop = _make_prop(annual_rent=60_000)
        a = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        metrics = {r.metric for r in a.report()}
        assert "Cap Rate" in metrics
        assert "DSCR" in metrics
        assert "Annual Cash Flow" in metrics

    def test_to_record_keys(self):
        prop = _make_prop(annual_rent=60_000)
        a = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        rec = a.to_record()
        for key in ("address", "mls_number", "status", "asking_price", "results",
                    "city", "province", "property_type", "annual_rent", "analyzed_on"):
            assert key in rec

    def test_to_record_address(self):
        prop = _make_prop(annual_rent=60_000)
        a = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        assert a.to_record()["address"] == "1 Main St, Ottawa, ON"

    def test_to_record_results_not_empty(self):
        prop = _make_prop(annual_rent=60_000)
        a = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        rec = a.to_record()
        assert len(rec["results"]) > 0

    def test_to_record_results_are_dicts(self):
        prop = _make_prop(annual_rent=60_000)
        a = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        for row in a.to_record()["results"]:
            assert "metric" in row and "value" in row and "grade" in row

    def test_to_record_preserves_created_at(self):
        prop = _make_prop(annual_rent=60_000)
        a = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        existing = {"created_at": "2024-06-01"}
        rec = a.to_record(existing=existing)
        assert rec["created_at"] == "2024-06-01"

    def test_to_record_analyzed_on_today(self):
        prop = _make_prop(annual_rent=60_000)
        a = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        assert a.to_record()["analyzed_on"] == date.today().isoformat()

    def test_to_record_persists_explicit_vacancy_rate(self):
        """An explicitly set vacancy_rate is stored so it can be round-tripped."""
        prop = _make_prop(annual_rent=60_000, vacancy_rate=0.08)
        a = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        assert a.to_record()["vacancy_rate"] == pytest.approx(0.08)

    def test_to_record_stores_null_when_vacancy_not_set(self):
        """No explicit vacancy_rate → stored as None so re-analysis re-resolves from constants."""
        prop = _make_prop(annual_rent=60_000)
        a = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        assert a.to_record()["vacancy_rate"] is None

    def test_to_record_persists_noi_growth_rate(self):
        prop = _make_prop(annual_rent=60_000, noi_growth_rate=0.03)
        a = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        assert a.to_record()["noi_growth_rate"] == pytest.approx(0.03)

    def test_prop_not_mutated_by_analyzer(self):
        """Analyzer must not write noi_growth_rate or vacancy_rate back onto PropertyInput."""
        prop = _make_prop(annual_rent=60_000)
        original_growth   = prop.noi_growth_rate  # None
        original_vacancy  = prop.vacancy_rate      # None
        CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        assert prop.noi_growth_rate == original_growth, (
            "Analyzer must not mutate prop.noi_growth_rate"
        )
        assert prop.vacancy_rate == original_vacancy, (
            "Analyzer must not mutate prop.vacancy_rate"
        )

    def test_vacancy_rate_roundtrip_picks_up_updated_default(self):
        """Core regression: after to_record() → reload → re-analyze, a changed
        VACANCY_RATE_DEFAULTS entry must propagate (not be frozen at the original value)."""
        import models.constants as consts

        prop = _make_prop(annual_rent=60_000, property_type="Office")
        a    = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        rec  = a.to_record()

        assert rec["vacancy_rate"] is None, "must store None so defaults can change"

        original_default = consts.VACANCY_RATE_DEFAULTS.get("office", 0.14)
        patched_default  = original_default + 0.05
        consts.VACANCY_RATE_DEFAULTS["office"] = patched_default
        try:
            reloaded = PropertyInput(
                address=rec["address"], mls_number=rec.get("mls_number", ""),
                status=rec.get("status", "active"),
                listing_date=rec.get("listing_date", date.today().isoformat()),
                original_price=rec["original_price"], asking_price=rec["asking_price"],
                total_sq_ft=rec["total_sq_ft"], property_taxes=rec["property_taxes"],
                down_payment_pct=rec["down_payment_pct"], interest_rate=rec["interest_rate"],
                term_years=rec["term_years"], hold_years=rec["hold_years"],
                property_type=rec["property_type"], lease_type=rec.get("lease_type", "Normal"),
                vacancy_rate=rec["vacancy_rate"],  # None — triggers re-resolution
            )
            a2 = CommercialPropertyAnalyzer(reloaded, _make_resolver(60_000))
            assert a2.income.vacancy_rate == pytest.approx(patched_default), (
                "Re-analysis must use the updated default, not the frozen original"
            )
        finally:
            consts.VACANCY_RATE_DEFAULTS["office"] = original_default

    def test_to_record_does_not_persist_resolved_growth_when_prop_has_none(self):
        """When prop has no explicit noi_growth_rate, to_record() must save None so that
        re-analysis re-resolves from demographics (picking up any updates)."""
        prop = _make_prop(annual_rent=60_000, city="UnknownCityXYZ", province="XX")
        a = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        rec = a.to_record()
        assert rec["noi_growth_rate"] is None


# ── Construction cost propagation ─────────────────────────────────────────────

class TestConstructionCostPropagation:
    """Construction cost must flow through cost basis, cash invested, and return metrics."""

    def test_cost_basis_includes_construction(self):
        # asking=480k + construction=50k → cost_basis=530k
        prop = _make_prop(asking_price=480_000, construction_cost=50_000, annual_rent=60_000)
        a = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        assert a.pricing._cost_basis == pytest.approx(530_000)

    def test_cash_invested_includes_construction(self):
        # down_payment = 480k * 0.25 = 120k; cash_invested = 120k + 50k = 170k
        prop = _make_prop(asking_price=480_000, down_payment_pct=0.25,
                          construction_cost=50_000, annual_rent=60_000)
        a = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        assert a.cashflow.cash_invested == pytest.approx(170_000)

    def test_cap_rate_lower_with_construction_cost(self):
        base = _make_prop(asking_price=480_000, construction_cost=0,      annual_rent=60_000)
        cost = _make_prop(asking_price=480_000, construction_cost=100_000, annual_rent=60_000)
        a_base = CommercialPropertyAnalyzer(base, _make_resolver(60_000))
        a_cost = CommercialPropertyAnalyzer(cost, _make_resolver(60_000))
        assert a_cost.income.cap_rate < a_base.income.cap_rate

    def test_irr_lower_with_construction_cost(self):
        # More cash out upfront → worse IRR for the same NOI / exit price
        base = _make_prop(asking_price=480_000, construction_cost=0,      annual_rent=60_000)
        cost = _make_prop(asking_price=480_000, construction_cost=100_000, annual_rent=60_000)
        a_base = CommercialPropertyAnalyzer(base, _make_resolver(60_000))
        a_cost = CommercialPropertyAnalyzer(cost, _make_resolver(60_000))
        assert a_cost.returns.irr < a_base.returns.irr

    def test_construction_cost_shown_in_mortgage_rows(self):
        prop = _make_prop(asking_price=480_000, construction_cost=50_000, annual_rent=60_000)
        a = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        metrics = {r.metric for r in a.mortgage.rows()}
        assert "Construction Cost" in metrics
        assert "Total Cash In" in metrics

    def test_zero_construction_cost_omits_extra_rows(self):
        prop = _make_prop(asking_price=480_000, construction_cost=0, annual_rent=60_000)
        a = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        metrics = {r.metric for r in a.mortgage.rows()}
        assert "Construction Cost" not in metrics
        assert "Total Cash In" not in metrics

    def test_to_record_saves_construction_cost(self):
        prop = _make_prop(asking_price=480_000, construction_cost=75_000, annual_rent=60_000)
        a = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        assert a.to_record()["construction_cost"] == pytest.approx(75_000)


# ── No rent ───────────────────────────────────────────────────────────────────

class TestAnalyzerNoRent:
    def test_has_rent_false(self):
        prop = _make_prop()
        a = CommercialPropertyAnalyzer(prop, _make_resolver(0))
        assert a._has_rent is False

    def test_income_group_is_none(self):
        prop = _make_prop()
        a = CommercialPropertyAnalyzer(prop, _make_resolver(0))
        assert a.income is None

    def test_report_still_returns_rows(self):
        prop = _make_prop()
        a = CommercialPropertyAnalyzer(prop, _make_resolver(0))
        rows = a.report()
        # Mortgage + pricing rows still present
        assert len(rows) > 0

    def test_results_empty_after_filtering(self):
        prop = _make_prop()
        a = CommercialPropertyAnalyzer(prop, _make_resolver(0))
        rec = a.to_record()
        # Results filter to grade != ""
        all_empty_grade = all(r["grade"] == "" for r in rec["results"])
        assert len(rec["results"]) == 0 or not all_empty_grade


# ── Hotel property ─────────────────────────────────────────────────────────────

class TestAnalyzerHotel:
    def test_hotel_group_set(self):
        prop = _make_prop(property_type="Hotel", hotel_rooms=50,
                          hotel_adr=150.0, hotel_occupancy=0.70)
        rev = 50 * 150 * 0.70 * 365
        a = CommercialPropertyAnalyzer(prop, _make_resolver(rev))
        assert a.hotel is not None

    def test_non_hotel_hotel_group_none(self):
        prop = _make_prop(annual_rent=60_000, property_type="Retail")
        a = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        assert a.hotel is None


# ── Industrial property ────────────────────────────────────────────────────────

class TestAnalyzerIndustrial:
    def test_industrial_group_set(self):
        prop = _make_prop(
            property_type="Industrial",
            total_sq_ft=10_000,
            ind_warehouse_sqft=8_000,
            ind_clear_height_ft=24.0,
        )
        a = CommercialPropertyAnalyzer(prop, _make_resolver(120_000))
        assert a.industrial is not None

    def test_non_industrial_group_none(self):
        prop = _make_prop(annual_rent=60_000, property_type="Office")
        a = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        assert a.industrial is None


# ── Regional vacancy pipeline (v3.7): record provenance + no commercial regression ──

class TestVacancyPipelineRecord:
    """Runs against the committed seed data (empty crosswalk -> residential resolves at
    tier 3 provincial; commercial resolves to its per-type default). Verifies the
    record round-trips the source stamp fields and commercial numbers don't regress."""

    def test_record_carries_vacancy_provenance(self):
        prop = _make_prop(annual_rent=60_000, property_type="Multi-Family")
        a = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        rec = a.to_record()
        assert rec["vacancy_source"] == "provincial_avg"   # seed: no region data yet
        assert rec["vacancy_tier"] == 3
        assert rec["vacancy_normal"] is True               # tier 3 is healthy, not an alarm
        assert rec["vacancy_region"].startswith("ON")
        # The displayed Vacancy Rate row embeds the provenance, incl. the honest tier-3
        # "derived unweighted average" caveat (not an official provincial figure).
        vac_row = next(r for r in rec["results"] if r["metric"] == "Vacancy Rate")
        assert "provincial avg" in vac_row["value"]
        assert "derived: unweighted avg of surveyed centres" in vac_row["value"]

    def test_commercial_vacancy_no_regression(self):
        prop = _make_prop(annual_rent=60_000, property_type="Office")
        a = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
        assert a.income.vacancy_rate == pytest.approx(0.14)   # unchanged office default
        rec = a.to_record()
        assert rec["vacancy_source"] == "type_default"
        assert rec["vacancy_normal"] is True

    def test_partial_record_has_null_vacancy_fields(self):
        from analysis.analyzer import build_partial_record
        rec = build_partial_record(_make_prop(property_type="Retail"))
        for k in ("vacancy_source", "vacancy_reliability", "vacancy_region",
                  "vacancy_tier", "vacancy_normal", "vacancy_demoted_from"):
            assert rec[k] is None

    def test_demotion_recorded_in_record_and_row(self, tmp_path, monkeypatch):
        """A 'd'-rated region figure is demoted, and that fact is persisted (record
        field) AND shown (Vacancy Rate row) — not silently swallowed."""
        import json as _json
        import analysis.vacancy_resolver as vr
        crosswalk = {
            "cma_ca": {"505": {"name": "Ottawa - Gatineau", "type": "CMA", "province": "ON"}},
            "csd": {"3506008": {"name": "Ottawa", "cma_ca_code": "505", "province": "ON"}},
            "name_index": {"ottawa|ON": "3506008"},
        }
        vacancy = {
            "_meta": {"attribution": "Adapted from CMHC, RMS, 2025."},
            "regions": {"505": {"vacancy_rate": 0.020, "reliability": "d", "geo_level": "CMA",
                                "name": "Ottawa - Gatineau", "province": "ON"}},
            "provincial": {"ON": {"vacancy_rate": 0.024, "reliability": None}},
            "national": {"vacancy_rate": 0.020},
        }
        (tmp_path / "x.json").write_text(_json.dumps(crosswalk), encoding="utf-8")
        (tmp_path / "v.json").write_text(_json.dumps(vacancy), encoding="utf-8")
        monkeypatch.setattr(vr, "_CROSSWALK_PATH", str(tmp_path / "x.json"))
        monkeypatch.setattr(vr, "_VACANCY_PATH", str(tmp_path / "v.json"))
        vr.reset_cache()
        try:
            prop = _make_prop(annual_rent=60_000, property_type="Multi-Family")  # Ottawa/ON
            a = CommercialPropertyAnalyzer(prop, _make_resolver(60_000))
            rec = a.to_record()
            assert rec["vacancy_source"] == "provincial_avg"   # 505 was 'd' -> demoted
            assert rec["vacancy_demoted_from"] == "Ottawa - Gatineau CMA (rel. d)"
            vac_row = next(r for r in rec["results"] if r["metric"] == "Vacancy Rate")
            assert "demoted from Ottawa - Gatineau CMA (rel. d)" in vac_row["value"]
        finally:
            vr.reset_cache()
