"""
v4.10.0 coverage-audit: small engine-level gap tests for two behaviours the desktop
layer relies on but that weren't directly asserted.

  * to_record() does NOT emit `notes` — which is exactly why the desktop save carries the
    notes field through explicitly (4.7.2).
  * resolve_financing() sources `hold_years` from the global `defaults` for every property
    type — never per-type — so hold period is house-wide (4.9.4 / global financing).
"""
from unittest.mock import MagicMock

from models.property_input import PropertyInput
from analysis.analyzer import CommercialPropertyAnalyzer
from analysis.financing_config import resolve_financing, load_financing_config


def _resolver(rent=60_000):
    r = MagicMock()
    r.resolve.return_value = (rent, ["$60k/yr direct"])
    r._comm_rent = rent
    r._res_rent = 0.0
    r._city_rent_per_sqft = 12.0
    r._comm_sq_ft = None
    return r


def _prop(**kw):
    d = dict(address="1 Main St, Ottawa, ON", mls_number="MLS-1", status="active",
             original_price=500_000, asking_price=480_000, total_sq_ft=5000,
             property_taxes=8_000, down_payment_pct=0.25, interest_rate=0.055,
             term_years=25, hold_years=10, expense_ratio=0.40, lease_type="Normal",
             listing_date="2024-01-01", city="Ottawa", province="ON", annual_rent=60_000)
    d.update(kw)
    return PropertyInput(**d)


def test_to_record_does_not_emit_notes():
    """The analysis record has no `notes` key — the desktop save must carry it explicitly."""
    rec = CommercialPropertyAnalyzer(_prop(), _resolver()).to_record()
    assert "notes" not in rec


def test_to_record_notes_preserved_from_existing_only_if_app_adds_it():
    """Even when an existing record carried a note, to_record doesn't re-emit it (the app
    layer owns notes), confirming the carry-through responsibility sits above the engine."""
    rec = CommercialPropertyAnalyzer(_prop(), _resolver()).to_record(existing={"notes": "keep me"})
    assert "notes" not in rec


def test_hold_years_is_global_across_all_types():
    """hold_years comes from defaults for every type — it is never a per-type override."""
    hy = load_financing_config()["hold_years"]
    for t in ("office", "retail", "hotel", "industrial", "mixed_use", "multi_family", "residential"):
        assert resolve_financing(1_200_000, t)["hold_years"] == hy, t
    # 5+ unit multifamily (CMHC-routed) still uses the global hold_years.
    assert resolve_financing(3_000_000, "multi_family", units=6)["hold_years"] == hy
