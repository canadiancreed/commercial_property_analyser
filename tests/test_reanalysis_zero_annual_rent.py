"""
Regression tests for a stored annual_rent=0 freezing rent at $0 on re-analysis.

Context: _record_to_prop coerces falsy commercial_rent and residential_rent to
None ("not recorded — recompute from market rates"), but annual_rent used to
pass a literal 0 through.  The resolver's short-circuit checks
`prop.annual_rent is not None`, so 0 was returned as "rent provided directly",
every income metric was skipped, and to_record() wrote the 0 straight back —
a self-perpetuating $0 record that no re-analysis could heal.

Three layers are tested:
  1. _record_to_prop  — annual_rent=0 converts to None, non-zero survives
  2. RentResolver     — None falls through to market rates, non-zero short-circuits
  3. End-to-end       — a zero-rent record recomputes instead of staying frozen
"""

import pytest
from unittest.mock import MagicMock

from models.property_input import PropertyInput
from analysis.rent_resolver import RentResolver
from analysis.analyzer import CommercialPropertyAnalyzer
from ui.menu import PropertyMenu


# ── Helpers ───────────────────────────────────────────────────────────────────

RETAIL_RATE = 30.0   # $/sqft/yr
SQ_FT       = 3_000


def _resolver():
    comm = MagicMock()
    comm.get_rent_per_sqft.return_value = RETAIL_RATE
    res = MagicMock()
    res.get_rates.return_value = None
    return RentResolver(comm, res)


def _stored_record(**overrides):
    """Minimal stored JSON record for a unit-less Retail with a frozen $0 rent."""
    base = {
        "address":          "100 Main St, Peterborough, ON",
        "mls_number":       "X10000001",
        "status":           "active",
        "listing_date":     "2025-01-01",
        "asking_price":     500_000,
        "original_price":   500_000,
        "total_sq_ft":      SQ_FT,
        "city":             "Peterborough",
        "province":         "ON",
        "property_type":    "Retail",
        "property_taxes":   5_000,
        "down_payment_pct": 0.20,
        "interest_rate":    0.055,
        "term_years":       25,
        "hold_years":       30,
        "expense_ratio":    0.40,
        "lease_type":       "Normal",
        "construction_cost": 0,
        "annual_rent":      0,            # the trap: literal zero, not null
        "commercial_rent":  0.0,
        "residential_rent": 0.0,
        "vacancy_rate":     0.05,
        "noi_growth_rate":  None,
        "unit_mix": {
            "bachelor": 0, "one_br": 0, "two_br": 0,
            "three_br": 0, "four_br": 0, "unknown": 0,
            "floors": 1,
        },
        "floors": 1,
        "results": [],
    }
    base.update(overrides)
    return base


# ── Layer 1: _record_to_prop ──────────────────────────────────────────────────

class TestRecordToPropAnnualRent:

    def test_zero_annual_rent_becomes_none(self):
        """annual_rent=0 stored in JSON → prop.annual_rent is None, matching
        the falsy-to-None convention of commercial/residential rent."""
        prop = PropertyMenu._record_to_prop(_stored_record())
        assert prop.annual_rent is None

    def test_null_annual_rent_stays_none(self):
        prop = PropertyMenu._record_to_prop(_stored_record(annual_rent=None))
        assert prop.annual_rent is None

    def test_positive_annual_rent_preserved(self):
        """A genuine provided rent must survive the conversion untouched."""
        prop = PropertyMenu._record_to_prop(_stored_record(annual_rent=88_000.0))
        assert prop.annual_rent == pytest.approx(88_000.0)

    def test_annual_rent_still_suppressed_by_component_rents(self):
        """When commercial/residential rents exist they take precedence and
        annual_rent is nulled (pre-existing behaviour, must not regress)."""
        prop = PropertyMenu._record_to_prop(
            _stored_record(annual_rent=88_000.0, commercial_rent=50_000.0)
        )
        assert prop.annual_rent is None


# ── Layer 2: RentResolver ─────────────────────────────────────────────────────

class TestResolverZeroAnnualRent:

    def _prop(self, annual_rent):
        return PropertyInput(
            address="100 Main St, Peterborough, ON",
            mls_number="X10000001", status="active",
            original_price=500_000, asking_price=500_000,
            total_sq_ft=SQ_FT, property_taxes=5_000,
            down_payment_pct=0.20, interest_rate=0.055,
            term_years=25, hold_years=30,
            city="Peterborough", province="ON",
            property_type="Retail",
            annual_rent=annual_rent,
        )

    def test_none_annual_rent_falls_through_to_market_rates(self):
        r = _resolver()
        rent, _ = r.resolve(self._prop(None))
        assert rent == pytest.approx(RETAIL_RATE * SQ_FT)
        r._commercial.get_rent_per_sqft.assert_called_once()

    def test_provided_annual_rent_short_circuits(self):
        """Non-zero provided rent is returned as-is with no market lookup."""
        r = _resolver()
        rent, breakdown = r.resolve(self._prop(88_000.0))
        assert rent == pytest.approx(88_000.0)
        r._commercial.get_rent_per_sqft.assert_not_called()
        assert any("directly" in line.lower() for line in breakdown)


# ── Layer 3: End-to-end re-analysis ───────────────────────────────────────────

class TestEndToEndZeroRentRecovery:

    def _analyze(self, record):
        prop     = PropertyMenu._record_to_prop(record)
        analyzer = CommercialPropertyAnalyzer(prop, _resolver())
        return analyzer.to_record(existing=record)

    def test_frozen_zero_rent_record_recomputes(self):
        """The original bug: a record stuck at annual_rent=0 must come back
        from re-analysis with a market-computed rent, not $0."""
        out = self._analyze(_stored_record())
        assert out["annual_rent"] == pytest.approx(RETAIL_RATE * SQ_FT)

    def test_income_metrics_restored(self):
        """With rent recomputed, income metrics must be produced again."""
        out = self._analyze(_stored_record())
        metrics = {r["metric"] for r in out["results"]}
        assert "NOI" in metrics
        assert "Cap Rate" in metrics

    def test_recovery_is_idempotent(self):
        """Once healed, a second re-analysis keeps the recomputed rent."""
        first  = self._analyze(_stored_record())
        second = self._analyze(first)
        assert second["annual_rent"] == pytest.approx(first["annual_rent"])

    def test_provided_rent_record_unchanged(self):
        """A record with a genuine annual_rent must keep it verbatim."""
        out = self._analyze(_stored_record(annual_rent=88_000.0))
        assert out["annual_rent"] == pytest.approx(88_000.0)
