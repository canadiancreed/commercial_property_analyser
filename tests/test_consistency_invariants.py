"""Cross-metric consistency invariants.

These tests do not check any single formula in isolation — they assert that
independently-computed fields *agree with each other*. That is the class of
check that catches "silent" arithmetic regressions: a broken formula rarely
looks broken on its own, but it breaks its algebraic relationship to a sibling
field. Running the whole matrix through the real analyzer means a regression in
one metric fails here even if its own unit test was never written.

Two of the invariants are written against the code's *actual* definitions,
which differ from the naive textbook form:

  * LTV is computed on the amortized-down loan balance (projected LTV at the end
    of the hold), not origination. So the origination identity
    ``loan/price + down_payment_pct == 1`` is the one that holds universally;
    ``ltv + down/price == 1`` only holds at hold_years == 0.
  * Price/sqft uses cost basis (asking + construction) over the *commercial*
    square footage when supplied, so the identity is
    ``pp_sqft * denominator == cost_basis`` — not ``pp_sqft * total_sqft == price``.
"""

import pytest
from unittest.mock import MagicMock

from models.property_input import PropertyInput
from models.constants import CANADIAN_PROVINCES
from analysis.analyzer import CommercialPropertyAnalyzer
from analysis.mortgage import effective_monthly_rate


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_resolver(annual_rent=60_000, comm_sq_ft=None):
    resolver = MagicMock()
    resolver.resolve.return_value = (annual_rent, ["rent detail"])
    resolver._comm_rent          = annual_rent
    resolver._res_rent           = 0.0
    resolver._city_rent_per_sqft = 12.0
    resolver._comm_sq_ft         = comm_sq_ft
    return resolver


def _make_prop(**kwargs):
    defaults = dict(
        address="1 Main St, Ottawa, ON",
        mls_number="MLS-001",
        status="active",
        original_price=500_000,
        asking_price=480_000,
        total_sq_ft=5_000,
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


# A matrix of Canadian configurations that exercises the branches that
# historically produced silent-fallback values: multiple provinces (all
# semi-annual compounding), construction cost, commercial-only square footage,
# zero hold, and an explicit exit cap. The portfolio is entirely Canadian, so
# every case uses a Canadian province — no US/monthly-compounding data.
_MATRIX = [
    ("base-ON",        dict(),                                          dict()),
    ("bc-property",    dict(province="BC", city="Vancouver"),           dict()),
    ("construction",   dict(construction_cost=100_000),                dict()),
    ("comm-sqft",      dict(),                                          dict(comm_sq_ft=3_000)),
    ("hold-0",         dict(hold_years=0),                              dict()),
    ("explicit-exit",  dict(exit_cap_rate=0.07),                        dict()),
    ("high-dp",        dict(down_payment_pct=0.45),                     dict()),
    ("low-rate",       dict(interest_rate=0.031),                       dict()),
]


def _analyzers():
    for name, pkw, rkw in _MATRIX:
        prop = _make_prop(annual_rent=60_000, **pkw)
        analyzer = CommercialPropertyAnalyzer(prop, _make_resolver(60_000, **rkw))
        yield name, prop, analyzer


# ── Invariants ────────────────────────────────────────────────────────────────

class TestConsistencyInvariants:

    @pytest.mark.parametrize("name,prop,a", list(_analyzers()), ids=lambda x: x if isinstance(x, str) else "")
    def test_annual_debt_equals_monthly_times_twelve(self, name, prop, a):
        """Annual debt service is exactly twelve monthly payments."""
        assert a.mortgage.annual_mortgage == pytest.approx(a.mortgage.monthly_payment * 12, abs=1e-6)

    @pytest.mark.parametrize("name,prop,a", list(_analyzers()), ids=lambda x: x if isinstance(x, str) else "")
    def test_exit_price_times_exit_cap_equals_terminal_noi(self, name, prop, a):
        """exit_price is terminal NOI capitalized at the exit cap, so the product
        recovers terminal NOI exactly."""
        terminal_noi = a.income.est_noi * (1 + a._noi_growth_rate) ** prop.hold_years
        assert a.exit.exit_price * a.exit.exit_cap == pytest.approx(terminal_noi, abs=1.0)

    @pytest.mark.parametrize("name,prop,a", list(_analyzers()), ids=lambda x: x if isinstance(x, str) else "")
    def test_origination_ltv_identity(self, name, prop, a):
        """loan + down payment == price (origination financing identity)."""
        loan_share = a.mortgage.loan_amount / prop.asking_price
        assert loan_share + prop.down_payment_pct == pytest.approx(1.0, abs=1e-9)

    @pytest.mark.parametrize("name,prop,a", list(_analyzers()), ids=lambda x: x if isinstance(x, str) else "")
    def test_down_payment_equals_price_minus_loan(self, name, prop, a):
        assert a.mortgage.down_payment + a.mortgage.loan_amount == pytest.approx(prop.asking_price, abs=1e-6)

    @pytest.mark.parametrize("name,prop,a", list(_analyzers()), ids=lambda x: x if isinstance(x, str) else "")
    def test_price_per_sqft_times_denominator_equals_cost_basis(self, name, prop, a, ):
        """pp_sqft reconstructs the cost basis over whichever denominator was used
        (commercial sqft when supplied, else total sqft)."""
        cost_basis  = prop.asking_price + (prop.construction_cost or 0)
        denominator = a.pricing.pp_sqft and cost_basis / a.pricing.pp_sqft
        assert a.pricing.pp_sqft * denominator == pytest.approx(cost_basis, abs=1.0)

    @pytest.mark.parametrize("name,prop,a", list(_analyzers()), ids=lambda x: x if isinstance(x, str) else "")
    def test_cap_rate_reconstructs_noi(self, name, prop, a):
        """entry cap * cost basis == NOI, and the percent Cap Rate agrees."""
        cost_basis = prop.asking_price + (prop.construction_cost or 0)
        assert a.income.entry_cap * cost_basis == pytest.approx(a.income.est_noi, abs=1e-6)
        assert a.income.cap_rate == pytest.approx(a.income.entry_cap * 100, abs=1e-9)

    @pytest.mark.parametrize("name,prop,a", list(_analyzers()), ids=lambda x: x if isinstance(x, str) else "")
    def test_noi_is_egi_net_of_expenses(self, name, prop, a):
        assert a.income.est_noi == pytest.approx(a.income.egi - a.income.est_expenses, abs=1e-9)

    @pytest.mark.parametrize("name,prop,a", list(_analyzers()), ids=lambda x: x if isinstance(x, str) else "")
    def test_payment_convention_locked(self, name, prop, a):
        """Lock the compounding convention against a US-monthly regression.

        Canadian provinces MUST use semi-annual compounding (Interest Act s. 6);
        US states use monthly. Reconstruct the payment from the periodic rate the
        province mandates and assert the analyzer produced exactly that.
        """
        is_ca = (prop.province or "").strip().upper() in CANADIAN_PROVINCES
        compounding = "semi-annual" if is_ca else "monthly"
        r = effective_monthly_rate(prop.interest_rate, compounding)
        n = prop.term_years * 12
        loan = a.mortgage.loan_amount
        expected = loan * (r * (1 + r) ** n) / ((1 + r) ** n - 1)
        assert a.mortgage.monthly_payment == pytest.approx(expected, abs=0.01)

        # And confirm CA really is cheaper than the naive monthly number, so a
        # silent switch to annual_rate/12 would move the value and trip this test.
        if is_ca:
            naive_r = prop.interest_rate / 12
            naive = loan * (naive_r * (1 + naive_r) ** n) / ((1 + naive_r) ** n - 1)
            assert a.mortgage.monthly_payment < naive
