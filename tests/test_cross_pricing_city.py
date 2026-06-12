"""
Cross-file tests for city-aware price/sqft thresholds — issue #10.

PricingMetrics derives city-level price/sqft thresholds from the city's rent/sqft
rate multiplied by the per-type GRM thresholds (price/sqft ≈ GRM × rent/sqft).
Tests pass city_rent_per_sqft explicitly so they don't depend on the JSON files.
"""

import pytest
from models.property_input import PropertyInput
from analysis.metrics.pricing import PricingMetrics


def _prop(**kwargs):
    defaults = dict(
        original_price=500_000, asking_price=500_000,
        total_sq_ft=5_000, property_taxes=8_000,
        down_payment_pct=0.25, interest_rate=0.055,
        term_years=25, hold_years=5,
    )
    defaults.update(kwargs)
    return PropertyInput(**defaults)


# ── Issue #10: price/sqft thresholds must have city-level benchmarks ──────────

class TestPricePerSqftMarketAware:

    def test_type_thresholds_applied_when_no_city_data(self):
        """Regression baseline: type-level threshold still works when city rent is unknown."""
        prop = _prop(asking_price=400_000, total_sq_ft=5_000,
                     property_type="Retail", city=None)
        # pp_sqft = 80 → below hardcoded retail good threshold of 200
        m   = PricingMetrics(prop, 160_000, 50_000, city_rent_per_sqft=None)
        row = next(r for r in m.rows() if "Price/Sq Ft" in r.metric)
        assert row.grade == "GOOD"

    def test_same_sqft_grades_differently_by_city(self):
        """
        $400/sqft retail is GOOD in Vancouver (rent=$72/sqft) but FAIR in Edmonton (rent=$28/sqft).
        Vancouver: good_thresh = 12 * 72 = $864  → $400 ≤ $864 → GOOD
        Edmonton:  good_thresh = 12 * 28 = $336  → $400 > $336, poor = 18*28=$504 → FAIR
        """
        prop_van = _prop(asking_price=2_000_000, total_sq_ft=5_000, property_type="Retail")
        prop_edm = _prop(asking_price=2_000_000, total_sq_ft=5_000, property_type="Retail")

        row_van = next(r for r in PricingMetrics(prop_van, 800_000, 200_000, city_rent_per_sqft=72).rows()
                       if "Price/Sq Ft" in r.metric)
        row_edm = next(r for r in PricingMetrics(prop_edm, 800_000, 200_000, city_rent_per_sqft=28).rows()
                       if "Price/Sq Ft" in r.metric)

        assert row_van.grade != row_edm.grade, (
            f"Vancouver and Edmonton both graded {row_van.grade!r} for $400/sqft retail; "
            "city-level thresholds must differentiate high- vs. low-cost markets"
        )

    def test_high_cost_city_pp_sqft_grades_good(self):
        """$400/sqft retail in Vancouver (rent=$72/sqft) should grade GOOD."""
        prop = _prop(asking_price=2_000_000, total_sq_ft=5_000, property_type="Retail")
        m   = PricingMetrics(prop, 800_000, 200_000, city_rent_per_sqft=72)
        row = next(r for r in m.rows() if "Price/Sq Ft" in r.metric)
        assert row.grade == "GOOD", (
            f"$400/sqft retail in Vancouver graded {row.grade!r}; "
            "Vancouver market rates (rent=$72/sqft → good_thresh=$864) should make this GOOD"
        )

    def test_low_cost_city_pp_sqft_grades_fair(self):
        """$400/sqft retail in Edmonton (rent=$28/sqft) should grade FAIR."""
        prop = _prop(asking_price=2_000_000, total_sq_ft=5_000, property_type="Retail")
        m   = PricingMetrics(prop, 800_000, 200_000, city_rent_per_sqft=28)
        row = next(r for r in m.rows() if "Price/Sq Ft" in r.metric)
        assert row.grade == "FAIR", (
            f"$400/sqft retail in Edmonton graded {row.grade!r}; "
            "Edmonton market rates (rent=$28/sqft → good=$336, poor=$504) should make this FAIR"
        )
