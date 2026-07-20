"""_reanalyze_all must SURFACE the errors it used to swallow — a per-property
console line plus full tracebacks in a log file — and clear a stale log on a
clean run."""
from unittest.mock import MagicMock
import pytest

from ui.menu import PropertyMenu


def _menu(records):
    store = MagicMock()
    store.load_properties.return_value = records
    return PropertyMenu(store, MagicMock())


def _patch_analyzer_ok(monkeypatch):
    monkeypatch.setattr(
        "ui.menu.CommercialPropertyAnalyzer",
        lambda prop, resolver: MagicMock(to_record=lambda existing=None: {"results": []}),
    )


def test_reanalyze_all_surfaces_and_logs_errors(tmp_path, monkeypatch, capsys):
    records = [
        {"address": "1 Good St, Ottawa, ON", "mls_number": "M1", "property_type": "Office"},
        {"address": "2 Bad St, Ottawa, ON",  "mls_number": "M2", "property_type": "Retail"},
    ]
    menu = _menu(records)
    _patch_analyzer_ok(monkeypatch)

    def fake_record_to_prop(p):
        if "Bad" in p["address"]:
            raise RuntimeError("kaboom")
        return MagicMock()
    monkeypatch.setattr(menu, "_record_to_prop", fake_record_to_prop)

    log = tmp_path / "reanalyze_errors.log"
    monkeypatch.setattr(PropertyMenu, "REANALYZE_ERROR_LOG", str(log))

    menu._reanalyze_all()

    out = capsys.readouterr().out
    assert "1/2 updated" in out
    assert "1 errors" in out
    assert "[M2]" in out and "kaboom" in out          # per-property console line
    assert log.exists()
    body = log.read_text(encoding="utf-8")
    assert "RuntimeError" in body and "kaboom" in body  # full traceback in the log
    assert "2 Bad St, Ottawa, ON" in body
    assert "1 Good St" not in body                       # only the failure is logged


def test_reanalyze_all_clean_run_clears_stale_log(tmp_path, monkeypatch, capsys):
    records = [{"address": "1 Good St, Ottawa, ON", "mls_number": "M1", "property_type": "Office"}]
    menu = _menu(records)
    _patch_analyzer_ok(monkeypatch)
    monkeypatch.setattr(menu, "_record_to_prop", lambda p: MagicMock())

    log = tmp_path / "reanalyze_errors.log"
    log.write_text("stale errors from a previous run", encoding="utf-8")
    monkeypatch.setattr(PropertyMenu, "REANALYZE_ERROR_LOG", str(log))

    menu._reanalyze_all()

    out = capsys.readouterr().out
    assert "errors" not in out.split("updated")[1]      # no error tally after the summary
    assert not log.exists()                             # stale log cleared


def test_missing_rates_still_counted_as_skipped_not_error(tmp_path, monkeypatch, capsys):
    records = [{"address": "1 NoRate St, Nowhere, ON", "mls_number": "M9", "property_type": "Office"}]
    menu = _menu(records)
    monkeypatch.setattr(
        "ui.menu.CommercialPropertyAnalyzer",
        lambda prop, resolver: (_ for _ in ()).throw(ValueError("No commercial rate")),
    )
    monkeypatch.setattr(menu, "_record_to_prop", lambda p: MagicMock())
    monkeypatch.setattr(PropertyMenu, "REANALYZE_ERROR_LOG", str(tmp_path / "reanalyze_errors.log"))

    menu._reanalyze_all()

    out = capsys.readouterr().out
    assert "1 skipped (missing rates)" in out
    assert "errored" not in out
    assert not (tmp_path / "reanalyze_errors.log").exists()
