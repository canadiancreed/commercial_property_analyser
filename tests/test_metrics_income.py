import pytest
from models.property_input import PropertyInput
from analysis.metrics.income import IncomeMetrics, ExitCapEstimator, ExitMetrics, INCOME_METRIC_NAMES


def _make_prop(**kwargs):
    defaults = dict(
        original_price=500_000, asking_price=500_000,
        total_sq_ft=5000, property_taxes=8000,
        down_payment_pct=0.25, interest_rate=0.055,
        term_years=25, hold_years=10,
        expense_ratio=0.40, lease_type="Normal",
        vacancy_rate=0.0,  # pin to zero so numerical assertions stay exact
    )
    defaults.update(kwargs)
    return PropertyInput(**defaults)


class TestIncomeMetrics:
    def test_noi(self):
        prop = _make_prop()
        m = IncomeMetrics(prop, 60_000, [])
        assert m.est_noi == pytest.approx(60_000 * 0.60)

    def test_cap_rate(self):
        prop = _make_prop(asking_price=500_000)
        m = IncomeMetrics(prop, 60_000, [])
        # NOI = 36000, cap = 36000/500000 * 100 = 7.2
        assert m.cap_rate == pytest.approx(7.2)

    def test_oer_ratio(self):
        prop = _make_prop(expense_ratio=0.40)
        m = IncomeMetrics(prop, 60_000, [])
        assert m.oer_ratio == pytest.approx(40.0)

    def test_entry_cap(self):
        prop = _make_prop(asking_price=500_000, expense_ratio=0.40)
        m = IncomeMetrics(prop, 60_000, [])
        assert m.entry_cap == pytest.approx(0.072)

    def test_cap_rate_includes_construction_cost(self):
        # cost_basis = 500k + 100k = 600k; NOI = 60k * 0.60 = 36k; cap = 36/600 = 6.0%
        prop = _make_prop(asking_price=500_000, construction_cost=100_000, vacancy_rate=0.0)
        m = IncomeMetrics(prop, 60_000, [])
        assert m.cap_rate == pytest.approx(6.0)

    def test_entry_cap_includes_construction_cost(self):
        prop = _make_prop(asking_price=500_000, construction_cost=100_000, vacancy_rate=0.0)
        m = IncomeMetrics(prop, 60_000, [])
        assert m.entry_cap == pytest.approx(0.06)

    def test_construction_cost_lowers_cap_rate_vs_no_cost(self):
        prop_base = _make_prop(asking_price=500_000, construction_cost=0,       vacancy_rate=0.0)
        prop_cost = _make_prop(asking_price=500_000, construction_cost=100_000, vacancy_rate=0.0)
        m_base = IncomeMetrics(prop_base, 60_000, [])
        m_cost = IncomeMetrics(prop_cost, 60_000, [])
        assert m_cost.cap_rate < m_base.cap_rate

    # ── expense grade: NNN ───────────────────────────────────────────────────

    def test_expense_grade_nnn_within_range(self):
        # NNN range 4–15%; 0.08 is within range → GOOD
        prop = _make_prop(lease_type="NNN", expense_ratio=0.08)
        assert IncomeMetrics(prop, 60_000, [])._expense_grade() == "GOOD"

    def test_expense_grade_nnn_below_range(self):
        # NNN range 4–15%; 0.02 is below range → WARNING Low
        prop = _make_prop(lease_type="NNN", expense_ratio=0.02)
        grade = IncomeMetrics(prop, 60_000, [])._expense_grade()
        assert "WARNING" in grade
        assert "Low" in grade

    def test_expense_grade_nnn_above_range(self):
        # NNN range 4–15%; 0.30 is above range → WARNING High
        prop = _make_prop(lease_type="NNN", expense_ratio=0.30)
        grade = IncomeMetrics(prop, 60_000, [])._expense_grade()
        assert "WARNING" in grade
        assert "High" in grade

    # ── expense grade: office (gross lease) ──────────────────────────────────

    def test_expense_grade_office_within_range(self):
        # Office range 32–50%; 0.40 is within range → GOOD
        prop = _make_prop(lease_type="Normal", expense_ratio=0.40, property_type="Office")
        assert IncomeMetrics(prop, 60_000, [])._expense_grade() == "GOOD"

    def test_expense_grade_office_below_range(self):
        # Office range 32–50%; 0.20 is below range → WARNING Low
        prop = _make_prop(lease_type="Normal", expense_ratio=0.20, property_type="Office")
        grade = IncomeMetrics(prop, 60_000, [])._expense_grade()
        assert "WARNING" in grade
        assert "Low" in grade

    def test_expense_grade_office_above_range(self):
        # Office range 32–50%; 0.60 is above range → WARNING High
        prop = _make_prop(lease_type="Normal", expense_ratio=0.60, property_type="Office")
        grade = IncomeMetrics(prop, 60_000, [])._expense_grade()
        assert "WARNING" in grade
        assert "High" in grade

    # ── expense grade: hotel ──────────────────────────────────────────────────

    def test_expense_grade_hotel_within_range(self):
        # Hotel range 55–72%; 0.63 is within range → GOOD
        prop = _make_prop(expense_ratio=0.63, property_type="Hotel")
        assert IncomeMetrics(prop, 60_000, [])._expense_grade() == "GOOD"

    def test_expense_grade_hotel_below_range(self):
        # Hotel range 55–72%; 0.40 is below range → WARNING Low
        prop = _make_prop(expense_ratio=0.40, property_type="Hotel")
        grade = IncomeMetrics(prop, 60_000, [])._expense_grade()
        assert "WARNING" in grade
        assert "Low" in grade

    # ── expense grade: no property type ──────────────────────────────────────

    def test_expense_grade_unknown_type_returns_info(self):
        # No property_type → no range to check → INFO
        prop = _make_prop(lease_type="Normal", expense_ratio=0.40)
        assert IncomeMetrics(prop, 60_000, [])._expense_grade() == "INFO"

    # ── warning message includes the expected range ───────────────────────────

    def test_expense_grade_warning_includes_range(self):
        # Office range 32–50%; a value outside must quote those numbers
        prop = _make_prop(lease_type="Normal", expense_ratio=0.20, property_type="Office")
        grade = IncomeMetrics(prop, 60_000, [])._expense_grade()
        assert "32" in grade and "50" in grade

    def test_oer_grade_nnn_good(self):
        prop = _make_prop(lease_type="NNN", expense_ratio=0.10)
        m = IncomeMetrics(prop, 60_000, [])
        assert m._oer_grade() == "GOOD"

    def test_oer_grade_normal_good(self):
        prop = _make_prop(lease_type="Normal", expense_ratio=0.40)
        m = IncomeMetrics(prop, 60_000, [])
        assert m._oer_grade() == "GOOD"

    def test_rows_count(self):
        prop = _make_prop()
        m = IncomeMetrics(prop, 60_000, ["line1", "line2"])
        rows = m.rows()
        # 2 breakdown + 8 metric rows (Gross Potential Rent, Vacancy Rate, EGI,
        # Expense Ratio, NOI, Cap Rate, Cap Rate Risk Check, Op Expense Ratio)
        assert len(rows) == 10

    def test_hotel_omits_vacancy_rate_row(self):
        prop = _make_prop(property_type="hotel")
        m = IncomeMetrics(prop, 60_000, [])
        row_names = [r.metric for r in m.rows()]
        assert "Vacancy Rate" not in row_names

    def test_breakdown_included_in_rows(self):
        prop = _make_prop()
        m = IncomeMetrics(prop, 60_000, ["Detail line"])
        rows = m.rows()
        assert any("Detail line" in r.value for r in rows)

    def test_cap_rate_grade_good(self):
        prop = _make_prop(asking_price=400_000)
        m = IncomeMetrics(prop, 60_000, [])
        row = next(r for r in m.rows() if r.metric == "Cap Rate")
        # cap = 36000/400000 * 100 = 9% → GOOD (>= 7.5)
        assert row.grade == "GOOD"

    def test_cost_basis_includes_construction(self):
        prop = _make_prop(asking_price=500_000, construction_cost=50_000)
        m = IncomeMetrics(prop, 60_000, [])
        # cap_rate should use 550000 as basis
        assert m.cap_rate == pytest.approx(36_000 / 550_000 * 100)

    def test_income_metric_names_matches_rows(self):
        """INCOME_METRIC_NAMES must be a subset of the metric names rows() actually emits."""
        prop = _make_prop()
        m = IncomeMetrics(prop, 60_000, [])
        emitted = {r.metric for r in m.rows()}
        assert INCOME_METRIC_NAMES.issubset(emitted), (
            f"INCOME_METRIC_NAMES contains names not emitted by rows(): "
            f"{INCOME_METRIC_NAMES - emitted}"
        )


class TestExitCapEstimator:
    def test_no_market_cap(self):
        est = ExitCapEstimator(entry_cap=0.07, hold_years=5)
        result = est.estimate()
        # aging = 5 * 10/10000 = 0.005, drift = 0.0025
        expected = round(0.07 + 0.005 + 0.0025, 4)
        assert result == pytest.approx(expected)

    def test_capped_at_10_years(self):
        est10 = ExitCapEstimator(entry_cap=0.07, hold_years=10)
        est20 = ExitCapEstimator(entry_cap=0.07, hold_years=20)
        # aging should be the same for both
        assert est10.estimate() == est20.estimate()

    def test_with_market_cap(self):
        est = ExitCapEstimator(entry_cap=0.07, hold_years=5, market_cap_rate=0.08)
        formula = 0.07 + 0.005 + 0.0025
        expected = round((formula + 0.08) / 2, 4)
        assert est.estimate() == pytest.approx(expected)

    def test_result_higher_than_entry(self):
        est = ExitCapEstimator(entry_cap=0.065, hold_years=10)
        assert est.estimate() > 0.065


class TestExitMetrics:
    def _make(self, entry_cap=0.07, est_noi=36_000, loan_balance=0, **prop_kwargs):
        prop = _make_prop(asking_price=500_000, hold_years=10, **prop_kwargs)
        return ExitMetrics(prop, entry_cap, est_noi, loan_balance)

    def test_exit_price_positive(self):
        m = self._make()
        assert m.exit_price > 0

    def test_exit_cap_ratio(self):
        m = self._make(entry_cap=0.07)
        assert m.exit_cap_ratio == pytest.approx(0.07 / m.exit_cap)

    def test_exit_cap_grade_good(self):
        # spread of 0 → GOOD
        prop = _make_prop(asking_price=500_000, exit_cap_rate=0.07, hold_years=10)
        m = ExitMetrics(prop, 0.07, 36_000, 0)
        assert m._exit_cap_grade() == "GOOD"

    def test_exit_cap_grade_poor(self):
        prop = _make_prop(asking_price=500_000, exit_cap_rate=0.12, hold_years=10)
        m = ExitMetrics(prop, 0.07, 36_000, 0)
        assert m._exit_cap_grade() == "POOR"

    def test_exit_price_grade_with_loan_balance_good(self):
        # exit_price well above loan_balance * 1.2
        prop = _make_prop(asking_price=500_000, exit_cap_rate=0.06, hold_years=10)
        m = ExitMetrics(prop, 0.06, 80_000, loan_balance=100_000)
        row = next(r for r in m.rows() if "Exit Price" in r.metric)
        assert row.grade == "GOOD"  # 80000/0.06 >> 100000 * 1.2

    def test_exit_price_grade_without_loan_balance_good(self):
        prop = _make_prop(asking_price=300_000, exit_cap_rate=0.07, hold_years=10)
        m = ExitMetrics(prop, 0.07, 60_000, loan_balance=0)
        row = next(r for r in m.rows() if "Exit Price" in r.metric)
        # exit_price = 60000/0.07 ≈ 857k > 300k cost basis → GOOD
        assert row.grade == "GOOD"

    def test_rows_returns_three(self):
        m = self._make()
        assert len(m.rows()) == 3

    def test_explicit_exit_cap_used(self):
        prop = _make_prop(asking_price=500_000, exit_cap_rate=0.09, hold_years=10)
        m = ExitMetrics(prop, 0.07, 36_000, 0)
        assert m.exit_cap == pytest.approx(0.09)


# ── Issue #7: NOI must be reduced by a vacancy rate, not 100% collected ───────

class TestVacancyModelling:

    def test_noi_reduced_by_vacancy(self):
        """10% vacancy must produce lower NOI than a fully-occupied property."""
        annual_rent = 60_000
        m_full = IncomeMetrics(_make_prop(expense_ratio=0.40, vacancy_rate=0.0),  annual_rent, [])
        m_vac  = IncomeMetrics(_make_prop(expense_ratio=0.40, vacancy_rate=0.10), annual_rent, [])
        assert m_vac.est_noi < m_full.est_noi

    def test_egi_derived_from_vacancy_adjusted_rent(self):
        """EGI = annual_rent × (1 − vacancy_rate); NOI = EGI × (1 − expense_ratio)."""
        annual_rent  = 100_000
        vacancy      = 0.10
        prop         = _make_prop(expense_ratio=0.40, vacancy_rate=vacancy)
        m            = IncomeMetrics(prop, annual_rent, [])
        expected_egi = annual_rent * (1 - vacancy)
        expected_noi = expected_egi * (1 - 0.40)
        assert m.egi     == pytest.approx(expected_egi, rel=1e-4)
        assert m.est_noi == pytest.approx(expected_noi, rel=1e-4)

    def test_zero_vacancy_noi_equals_full_rent_times_margin(self):
        """With vacancy_rate=0.0, NOI = annual_rent × (1 − expense_ratio)."""
        annual_rent = 80_000
        prop        = _make_prop(expense_ratio=0.40, vacancy_rate=0.0)
        m           = IncomeMetrics(prop, annual_rent, [])
        assert m.est_noi == pytest.approx(annual_rent * 0.60, rel=1e-6)

    @pytest.mark.parametrize("prop_type,expected_key", [
        ("Office",        "office"),
        ("Retail",        "retail"),
        ("Industrial",    "industrial"),
        ("Mixed-Use",     "mixed-use"),
        ("Retail-Office", "retail-office"),
        ("Multi-Family",  "multi-family"),
        ("Residential",   "residential"),
        ("Hotel",         "hotel"),
    ])
    def test_property_type_vacancy_defaults_resolved(self, prop_type, expected_key):
        """_resolve_vacancy_rate picks the correct VACANCY_RATE_DEFAULTS entry per type."""
        from models.constants import VACANCY_RATE_DEFAULTS
        from analysis.analyzer import _resolve_vacancy_rate
        prop = PropertyInput(
            original_price=500_000, asking_price=500_000, total_sq_ft=5000,
            property_taxes=8000, down_payment_pct=0.25, interest_rate=0.055,
            term_years=25, hold_years=10, lease_type="Normal",
            property_type=prop_type,
        )
        assert prop.vacancy_rate is None
        assert _resolve_vacancy_rate(prop) == pytest.approx(VACANCY_RATE_DEFAULTS[expected_key])

    def test_unknown_property_type_vacancy_fallback(self):
        """An unrecognised property type falls back to 5%."""
        from analysis.analyzer import _resolve_vacancy_rate
        prop = PropertyInput(
            original_price=500_000, asking_price=500_000, total_sq_ft=5000,
            property_taxes=8000, down_payment_pct=0.25, interest_rate=0.055,
            term_years=25, hold_years=10, lease_type="Normal",
            property_type="Warehouse",
        )
        assert _resolve_vacancy_rate(prop) == pytest.approx(0.05)

    def test_explicit_vacancy_rate_not_overridden(self):
        """A caller-supplied vacancy_rate is returned as-is by _resolve_vacancy_rate."""
        from analysis.analyzer import _resolve_vacancy_rate
        prop = PropertyInput(
            original_price=500_000, asking_price=500_000, total_sq_ft=5000,
            property_taxes=8000, down_payment_pct=0.25, interest_rate=0.055,
            term_years=25, hold_years=10, lease_type="Normal",
            property_type="Office", vacancy_rate=0.20,
        )
        assert prop.vacancy_rate == pytest.approx(0.20)
        assert _resolve_vacancy_rate(prop) == pytest.approx(0.20)
