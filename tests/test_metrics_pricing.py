import pytest
from models.property_input import PropertyInput
from analysis.metrics.pricing import PricingMetrics


def _make_prop(**kwargs):
    defaults = dict(
        original_price=500_000, asking_price=480_000,
        total_sq_ft=5000, property_taxes=9600,
        down_payment_pct=0.25, interest_rate=0.055,
        term_years=25, hold_years=10,
        expense_ratio=0.40, property_type="Retail",
    )
    defaults.update(kwargs)
    return PropertyInput(**defaults)


def _make_metrics(prop=None, loan_balance=200_000, annual_rent=60_000):
    if prop is None:
        prop = _make_prop()
    return PricingMetrics(prop, loan_balance, annual_rent)


class TestPricingMetrics:
    def test_price_per_sqft(self):
        m = _make_metrics()
        # 480000 / 5000 = 96
        assert m.pp_sqft == pytest.approx(96.0)

    def test_price_per_sqft_with_construction(self):
        prop = _make_prop(asking_price=480_000, construction_cost=20_000)
        m = PricingMetrics(prop, 200_000, 60_000)
        assert m.pp_sqft == pytest.approx(100.0)

    def test_grm(self):
        m = _make_metrics()
        # 480000 / 60000 = 8.0
        assert m.grm == pytest.approx(8.0)

    def test_price_drop_pct(self):
        m = _make_metrics()
        # (500000 - 480000) / 500000 * 100 = 4%
        assert m.price_drop_pct == pytest.approx(4.0)

    def test_no_price_drop(self):
        prop = _make_prop(original_price=480_000, asking_price=480_000)
        m = PricingMetrics(prop, 200_000, 60_000)
        assert m.price_drop_pct == pytest.approx(0.0)

    def test_tax_load(self):
        m = _make_metrics()
        # 9600 / 480000 * 100 = 2.0%
        assert m.tax_load == pytest.approx(2.0)

    def test_ltv_ratio(self):
        m = _make_metrics(loan_balance=240_000)
        # 240000 / 480000 * 100 = 50%
        assert m.ltv_ratio == pytest.approx(50.0)

    def test_rows_count(self):
        # Retail shows price/sqft → 5 rows
        rows = _make_metrics().rows()
        assert len(rows) == 5

    def test_rows_count_no_sqft_types(self):
        # Hotel, Residential, Multi-Family suppress price/sqft → 4 rows
        for ptype in ("Hotel", "Residential", "Multi-Family"):
            prop = _make_prop(property_type=ptype)
            rows = PricingMetrics(prop, 200_000, 60_000).rows()
            assert len(rows) == 4, f"{ptype} should have 4 rows, got {len(rows)}"

    def test_rows_metrics_present(self):
        rows = _make_metrics().rows()
        names = {r.metric for r in rows}
        assert any("Price/Sq Ft" in n for n in names)
        assert any("GRM" in n for n in names)
        assert any("Tax Load" in n for n in names)
        assert any("Price Drop" in n for n in names)
        assert any("Loan to Value" in n for n in names)

    def test_sqft_row_absent_for_hotel(self):
        prop = _make_prop(property_type="Hotel")
        rows = PricingMetrics(prop, 200_000, 60_000).rows()
        assert not any("Price/Sq Ft" in r.metric for r in rows)

    def test_sqft_row_absent_for_residential(self):
        prop = _make_prop(property_type="Residential")
        rows = PricingMetrics(prop, 200_000, 60_000).rows()
        assert not any("Price/Sq Ft" in r.metric for r in rows)

    def test_sqft_row_absent_for_multi_family(self):
        prop = _make_prop(property_type="Multi-Family")
        rows = PricingMetrics(prop, 200_000, 60_000).rows()
        assert not any("Price/Sq Ft" in r.metric for r in rows)

    def test_sqft_row_present_for_commercial_types(self):
        for ptype in ("Office", "Retail", "Industrial", "Mixed-Use", "Retail-Office"):
            prop = _make_prop(property_type=ptype)
            rows = PricingMetrics(prop, 200_000, 60_000).rows()
            assert any("Price/Sq Ft" in r.metric for r in rows), \
                f"Price/Sq Ft row missing for {ptype}"

    def test_sqft_threshold_office(self):
        prop = _make_prop(property_type="Office", asking_price=600_000, total_sq_ft=4000)
        m = PricingMetrics(prop, 200_000, 60_000)
        # Office thresholds are 150/300; pp_sqft = 150, should be GOOD
        assert m._sqft_good == 150
        assert m._sqft_poor == 300

    def test_sqft_threshold_industrial(self):
        prop = _make_prop(property_type="Industrial")
        m = PricingMetrics(prop, 200_000, 60_000)
        assert m._sqft_good == 80
        assert m._sqft_poor == 200

    def test_sqft_threshold_default(self):
        prop = _make_prop(property_type=None)
        m = PricingMetrics(prop, 200_000, 60_000)
        assert m._sqft_good == 150
        assert m._sqft_poor == 350

    def test_grm_grade_good(self):
        # GRM < 9 → GOOD (higher_is_better=False)
        prop = _make_prop(asking_price=480_000)
        m = PricingMetrics(prop, 200_000, annual_rent=70_000)
        rows = {r.metric[:3]: r for r in m.rows()}
        grm_row = next(r for r in m.rows() if r.metric == "GRM")
        assert grm_row.grade == "GOOD"

    def test_price_drop_grade_good(self):
        prop = _make_prop(original_price=600_000, asking_price=480_000)
        m = PricingMetrics(prop, 200_000, 60_000)
        row = next(r for r in m.rows() if "Price Drop" in r.metric)
        assert row.grade == "GOOD"  # 20% drop ≥ 10%


# ── Issue #9: GRM thresholds must vary by property type ───────────────────────

class TestGRMTypeAware:

    @staticmethod
    def _grm_row(prop_type, asking, rent):
        prop = _make_prop(asking_price=asking, property_type=prop_type)
        m    = PricingMetrics(prop, asking * 0.70, annual_rent=rent)
        return next(r for r in m.rows() if r.metric == "GRM"), m.grm

    def test_multi_family_grm_11_grades_good(self):
        """
        Multi-family GRM benchmarks in Canada sit ~14–18 (good threshold=14).
        A GRM of ~11.1 (asking=600k, rent=54k) is below the good threshold → GOOD.
        """
        row, grm = self._grm_row("Multi-Family", asking=600_000, rent=54_000)
        assert row.grade == "GOOD", (
            f"Multi-family GRM of {grm:.1f} should be GOOD; got {row.grade!r}"
        )

    def test_retail_and_multi_family_differ_at_same_grm(self):
        """GRM=13 is FAIR for Retail (good=12) but GOOD for Multi-Family (good=14)."""
        # asking=780_000, rent=60_000 → GRM = 13
        row_mf,  _ = self._grm_row("Multi-Family", asking=780_000, rent=60_000)
        row_ret, _ = self._grm_row("Retail",       asking=780_000, rent=60_000)
        assert row_mf.grade == "GOOD",  f"Multi-family GRM=13 should be GOOD; got {row_mf.grade!r}"
        assert row_ret.grade == "FAIR", f"Retail GRM=13 should be FAIR; got {row_ret.grade!r}"

    def test_grm_row_present_for_all_property_types(self):
        """GRM row must exist for every type in PROPERTY_TYPES."""
        from models.constants import PROPERTY_TYPES
        for ptype in PROPERTY_TYPES:
            row, _ = self._grm_row(ptype, asking=500_000, rent=50_000)
            assert row is not None, f"GRM row missing for '{ptype}'"

    # Per-type boundary checks: one "good" GRM value per asset class.
    # Each value is chosen to sit clearly below the type's good threshold.
    @pytest.mark.parametrize("ptype,asking,rent,expected_grade", [
        # GRM ~11.1 — below office good threshold of 14
        ("Office",        600_000,  54_000, "GOOD"),
        # GRM ~11.1 — below retail good threshold of 12
        ("Retail",        600_000,  54_000, "GOOD"),
        # GRM ~9.1 — below industrial good threshold of 10
        ("Industrial",    500_000,  55_000, "GOOD"),
        # GRM ~11.1 — below mixed-use good threshold of 12
        ("Mixed-Use",     600_000,  54_000, "GOOD"),
        # GRM ~11.1 — below retail-office good threshold of 12
        ("Retail-Office", 600_000,  54_000, "GOOD"),
        # GRM ~11.1 — below multi-family good threshold of 14
        ("Multi-Family",  600_000,  54_000, "GOOD"),
        # GRM ~8.3 — below residential good threshold of 9
        ("Residential",   500_000,  60_000, "GOOD"),
        # GRM ~17.1 — below hotel good threshold of 18
        ("Hotel",         600_000,  35_000, "GOOD"),
        # GRM ~15.0 — between retail thresholds 12/18 → FAIR
        ("Retail",        750_000,  50_000, "FAIR"),
        # GRM ~22.0 — above retail poor threshold of 18 → POOR
        ("Retail",        660_000,  30_000, "POOR"),
    ])
    def test_grm_grade_by_type(self, ptype, asking, rent, expected_grade):
        row, grm = self._grm_row(ptype, asking=asking, rent=rent)
        assert row.grade == expected_grade, (
            f"{ptype} GRM={grm:.1f} expected {expected_grade!r}; got {row.grade!r}"
        )
