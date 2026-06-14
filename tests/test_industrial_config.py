"""Unit tests for the industrial size-band / premium / confidence logic."""
import pytest
import analysis.industrial_config as cfg
from analysis.industrial_config import (
    resolve_size_band, industrial_confidence, load_premiums, load_size_bands,
    _read, _downgrade_level, _DEFAULT_BANDS, _DEFAULT_PREMIUMS,
)


# ── Size bands ────────────────────────────────────────────────────────────────

class TestResolveSizeBand:
    def test_small_bay_premium(self):
        label, mult, downgrade = resolve_size_band(10_000)
        assert label == "small-bay"
        assert mult == pytest.approx(1.08)
        assert downgrade is False

    def test_mid_size_trough(self):
        label, mult, _ = resolve_size_band(60_000)
        assert label == "mid-size"
        assert mult == pytest.approx(0.95)

    def test_big_box(self):
        label, mult, _ = resolve_size_band(150_000)
        assert label == "big-box"
        assert mult == pytest.approx(1.00)

    def test_boundary_25k_is_mid(self):
        # 25_000 is the small/mid boundary; sqft_max is exclusive on small-bay.
        label, _, _ = resolve_size_band(25_000)
        assert label == "mid-size"

    def test_boundary_100k_is_big_box(self):
        label, _, _ = resolve_size_band(100_000)
        assert label == "big-box"

    def test_zero_sqft_first_band(self):
        label, _, downgrade = resolve_size_band(0)
        assert label == "small-bay"
        assert downgrade is False  # no override on zero footprint

    def test_multitenant_override_by_doors(self):
        # Large footprint but heavy door density → reclassify to small-bay, flag.
        label, mult, downgrade = resolve_size_band(
            200_000, dock_doors=30, drive_in_doors=10)
        assert label == "small-bay"
        assert mult == pytest.approx(1.08)
        assert downgrade is True

    def test_multitenant_override_by_office_ratio(self):
        # 40% office on a big-box footprint → small-bay multi-tenant signal.
        label, _, downgrade = resolve_size_band(150_000, office_sqft=60_000)
        assert label == "small-bay"
        assert downgrade is True

    def test_no_override_when_signals_low(self):
        label, _, downgrade = resolve_size_band(
            150_000, dock_doors=2, drive_in_doors=0, office_sqft=5_000)
        assert label == "big-box"
        assert downgrade is False


# ── Premiums ──────────────────────────────────────────────────────────────────

class TestLoadPremiums:
    def test_has_all_keys(self):
        prem = load_premiums()
        for k in ("clear_height_premium_per_ft", "office_premium_ratio",
                  "yard_rate_ratio", "dock_door_annual", "drive_in_door_annual"):
            assert k in prem and "value" in prem[k]

    def test_clear_height_has_cap(self):
        prem = load_premiums()
        assert prem["clear_height_premium_per_ft"]["cap_pct"] > 0


# ── Confidence matrix ─────────────────────────────────────────────────────────

class TestIndustrialConfidence:
    def test_src_with_details_high(self):
        assert industrial_confidence("Src", is_detailed=True) == "HIGH"

    def test_src_no_details_med(self):
        assert industrial_confidence("Src", is_detailed=False) == "MED"

    def test_est_with_details_med(self):
        assert industrial_confidence("Est", is_detailed=True) == "MED"

    def test_est_no_details_low(self):
        assert industrial_confidence("Est", is_detailed=False) == "LOW"

    def test_none_source_no_details_low(self):
        assert industrial_confidence(None, is_detailed=False) == "LOW"

    def test_downgrade_high_to_med(self):
        assert industrial_confidence("Src", True, size_downgrade=True) == "MED"

    def test_downgrade_med_to_low(self):
        assert industrial_confidence("Est", True, size_downgrade=True) == "LOW"

    def test_downgrade_low_stays_low(self):
        assert industrial_confidence("Est", False, size_downgrade=True) == "LOW"


def test_size_bands_file_loads():
    bands = load_size_bands()
    assert len(bands) >= 3
    assert {b["label"] for b in bands} >= {"small-bay", "mid-size", "big-box"}


# ── Defensive fallbacks (missing/malformed config) ────────────────────────────

class TestFallbacks:
    def test_read_missing_file_returns_none(self):
        assert _read("does/not/exist.json") is None

    def test_load_size_bands_falls_back_to_defaults(self, monkeypatch):
        monkeypatch.setattr(cfg, "_read", lambda path: None)
        assert load_size_bands() == _DEFAULT_BANDS

    def test_load_premiums_falls_back_when_no_file(self, monkeypatch):
        monkeypatch.setattr(cfg, "_read", lambda path: None)
        prem = load_premiums()
        assert prem["office_premium_ratio"]["value"] == _DEFAULT_PREMIUMS["office_premium_ratio"]["value"]

    def test_load_premiums_ignores_malformed_entries(self, monkeypatch):
        # Non-dict / value-less entries are skipped; defaults retained.
        monkeypatch.setattr(cfg, "_read", lambda path: {
            "office_premium_ratio": "not-a-dict",
            "yard_rate_ratio": {"no_value_key": 1},
        })
        prem = load_premiums()
        assert prem["office_premium_ratio"]["value"] == _DEFAULT_PREMIUMS["office_premium_ratio"]["value"]
        assert prem["yard_rate_ratio"]["value"] == _DEFAULT_PREMIUMS["yard_rate_ratio"]["value"]

    def test_resolve_size_band_no_match_uses_last_band(self, monkeypatch):
        monkeypatch.setattr(cfg, "_read", lambda path: {
            "bands": [{"label": "huge", "sqft_min": 1_000_000, "sqft_max": None, "multiplier": 1.0}]
        })
        # 0 sqft matches no band's minimum → falls back to the last band.
        label, mult, downgrade = resolve_size_band(0)
        assert label == "huge"
        assert mult == pytest.approx(1.0)
        assert downgrade is False

    def test_override_without_small_bay_band_still_flags(self, monkeypatch):
        # Override triggers on a big footprint, but there is no small-bay band
        # to reclassify into — label stays, downgrade still flags the conflict.
        monkeypatch.setattr(cfg, "_read", lambda path: {
            "bands": [{"label": "big", "sqft_min": 0, "sqft_max": None, "multiplier": 1.0}],
            "_meta": {"doors_per_10k_small_bay": 1.5, "office_ratio_small_bay": 0.30},
        })
        label, mult, downgrade = resolve_size_band(200_000, dock_doors=40)
        assert label == "big"
        assert downgrade is True

    def test_downgrade_level_invalid_returns_low(self):
        assert _downgrade_level("BOGUS") == "LOW"
