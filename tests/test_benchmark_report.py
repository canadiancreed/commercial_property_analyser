"""Tests for BenchmarkReportGenerator and the benchmark_rows computation."""
from unittest.mock import patch

from reporting.benchmark_report import (
    BenchmarkReportGenerator,
    benchmark_rows,
)


def _row(address="1 Main St", city="Ottawa", province="ON", ptype="Retail",
         asking=500_000, sqft=5000, cap=7.0):
    return {
        "address": address, "city": city, "province": province, "type": ptype,
        "asking": asking, "total_sq_ft": sqft, "status": "active",
        "cap_rate": cap,
    }


class TestBenchmarkRows:
    def test_excludes_self_from_peer_average(self):
        # Two identical-city/type comps at $100 and $200 /sqft.
        rows = [
            _row("Cheap", asking=100_000, sqft=1000),   # $100/sqft
            _row("Dear",  asking=200_000, sqft=1000),   # $200/sqft
        ]
        out = {e["row"]["address"]: e for e in benchmark_rows(rows)}
        # "Cheap" is compared only to "Dear" ($200), not to itself.
        assert out["Cheap"]["peer_ppsf"] == 200.0
        assert out["Dear"]["peer_ppsf"] == 100.0

    def test_ppsf_delta_sign(self):
        rows = [
            _row("Cheap", asking=100_000, sqft=1000),   # $100, peer avg 200 -> -50%
            _row("Dear",  asking=200_000, sqft=1000),   # $200, peer avg 100 -> +100%
        ]
        out = {e["row"]["address"]: e for e in benchmark_rows(rows)}
        assert out["Cheap"]["ppsf_delta"] == -50.0
        assert out["Dear"]["ppsf_delta"] == 100.0

    def test_verdicts(self):
        rows = [
            _row("Cheap", asking=100_000, sqft=1000),
            _row("Dear",  asking=200_000, sqft=1000),
        ]
        out = {e["row"]["address"]: e for e in benchmark_rows(rows)}
        assert out["Cheap"]["verdict"] == "under"
        assert out["Dear"]["verdict"] == "over"

    def test_at_market_within_threshold(self):
        # $/sqft 100 and 105 -> deltas ~ -2.4% / +5% : both inside ±10%.
        rows = [
            _row("A", asking=100_000, sqft=1000),
            _row("B", asking=105_000, sqft=1000),
        ]
        out = {e["row"]["address"]: e for e in benchmark_rows(rows)}
        assert out["A"]["verdict"] == "market"
        assert out["B"]["verdict"] == "market"

    def test_basis_prefers_city_then_province_then_type(self):
        rows = [
            _row("OttawaA", city="Ottawa",     province="ON", asking=100_000, sqft=1000),
            _row("OttawaB", city="Ottawa",     province="ON", asking=120_000, sqft=1000),
            _row("Kingston", city="Kingston",  province="ON", asking=300_000, sqft=1000),
            _row("Vancouver", city="Vancouver", province="BC", asking=400_000, sqft=1000),
        ]
        out = {e["row"]["address"]: e for e in benchmark_rows(rows)}
        # Ottawa pair benchmark city-to-city.
        assert out["OttawaA"]["basis"] == "city"
        # Kingston has no city+type peer but shares province+type with Ottawa.
        assert out["Kingston"]["basis"] == "province"
        # Vancouver is the lone BC Retail, so it falls back to type-wide.
        assert out["Vancouver"]["basis"] == "type"

    def test_no_peers_when_unique_type(self):
        rows = [
            _row("OnlyOne", ptype="Hotel"),
            _row("Other",   ptype="Retail"),
        ]
        out = {e["row"]["address"]: e for e in benchmark_rows(rows)}
        # Each is the sole member of its type -> no comps, no verdict.
        assert out["OnlyOne"]["basis"] is None
        assert out["OnlyOne"]["verdict"] is None

    def test_cap_delta_uses_peers(self):
        rows = [
            _row("HiCap", cap=9.0, asking=100_000, sqft=1000),
            _row("LoCap", cap=5.0, asking=100_000, sqft=1000),
        ]
        out = {e["row"]["address"]: e for e in benchmark_rows(rows)}
        assert out["HiCap"]["cap_delta"] == 4.0   # 9 vs peer 5
        assert out["LoCap"]["cap_delta"] == -4.0

    def test_missing_cap_treated_as_none(self):
        rows = [
            _row("NoCap", cap=0, asking=100_000, sqft=1000),
            _row("Comp",  cap=7.0, asking=120_000, sqft=1000),
        ]
        out = {e["row"]["address"]: e for e in benchmark_rows(rows)}
        assert out["NoCap"]["cap"] is None
        assert out["NoCap"]["cap_delta"] is None

    def test_skips_rows_without_sqft_or_price(self):
        rows = [
            _row("Good"),
            _row("NoSqft", sqft=0),
            _row("NoPrice", asking=0),
        ]
        addrs = [e["row"]["address"] for e in benchmark_rows(rows)]
        assert "NoSqft" not in addrs
        assert "NoPrice" not in addrs

    def test_sorted_most_underpriced_first(self):
        rows = [
            _row("Dear",  asking=200_000, sqft=1000),
            _row("Cheap", asking=100_000, sqft=1000),
        ]
        order = [e["row"]["address"] for e in benchmark_rows(rows)]
        assert order[0] == "Cheap"

    def test_accepts_prebuilt_sqft_key(self):
        # Rows from _build_report_row use 'sqft', not 'total_sq_ft'.
        rows = [
            {"address": "A", "city": "X", "province": "ON", "type": "Retail",
             "asking": 100_000, "sqft": 1000, "cap_rate": 7.0},
            {"address": "B", "city": "X", "province": "ON", "type": "Retail",
             "asking": 200_000, "sqft": 1000, "cap_rate": 7.0},
        ]
        out = benchmark_rows(rows)
        assert len(out) == 2


def _embedded_data(html):
    import json, re
    m = re.search(r"const DATA = (\[.*?\]);", html, re.DOTALL)
    assert m, "embedded DATA array not found"
    return json.loads(m.group(1))


class TestBenchmarkReportGenerator:
    def test_render_html_skeleton(self):
        html = BenchmarkReportGenerator().render([_row()])
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html
        assert "Benchmarking" in html

    def test_embeds_property_with_comparison_fields(self):
        data = _embedded_data(BenchmarkReportGenerator().render(
            [_row("Bench Plaza", asking=100_000, sqft=1000),
             _row("Comp St", asking=120_000, sqft=1000)]))
        d = next(x for x in data if x["address"] == "Bench Plaza")
        for key in ("ppsf", "peer_ppsf", "ppsf_delta", "verdict", "basis", "comps"):
            assert key in d

    def test_verdicts_embedded(self):
        data = _embedded_data(BenchmarkReportGenerator().render([
            _row("Cheap", asking=100_000, sqft=1000),
            _row("Dear",  asking=200_000, sqft=1000),
        ]))
        byaddr = {d["address"]: d for d in data}
        assert byaddr["Cheap"]["verdict"] == "under"
        assert byaddr["Dear"]["verdict"] == "over"

    def test_has_verdict_and_comps_filters(self):
        html = BenchmarkReportGenerator().render([_row()])
        assert 'id="f-verdict"' in html
        assert 'id="f-comps"' in html

    def test_columns_are_click_sortable(self):
        html = BenchmarkReportGenerator().render([_row()])
        assert "function sortBy(" in html
        for col in ("ppsf_delta", "ppsf", "cap", "cap_delta", "comps"):
            assert f"sortBy('{col}'" in html

    def test_default_sort_is_ppsf_delta_ascending(self):
        html = BenchmarkReportGenerator().render([_row()])
        assert "let sortCol = 'ppsf_delta';" in html
        assert "let sortDir = 1;" in html

    def test_empty_input(self):
        data = _embedded_data(BenchmarkReportGenerator().render([]))
        assert data == []

    def test_address_escaped_in_browser(self):
        html = BenchmarkReportGenerator().render([_row("<x> St"), _row("Comp")])
        assert "function esc(" in html

    def test_open_in_browser_writes_and_opens(self):
        gen = BenchmarkReportGenerator()
        with patch("webbrowser.open") as mock_open:
            gen.open_in_browser([_row(), _row("Comp")])
            assert mock_open.called
