"""scripts/fetch_cash_sweep_data.py (V6.6.6): the sweep ETF's bars, trimmed to the window, dry run unless --apply. Yahoo and
the zip writer are stand-ins."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from script_loader import ROOT, load_script, run_script


def _patch(monkeypatch, rows):
    import data_pipeline.yfinance_backfill as yahoo

    calls = {}
    monkeypatch.setattr(yahoo, "fetch_yahoo_ohlcv", lambda ticker, start, end: calls.update(fetch=(ticker, start, end)) or rows)
    monkeypatch.setattr(yahoo, "write_lean_zip", lambda target, ticker, rows, merge_with_existing: calls.update(write=(Path(target), ticker, len(rows))))
    return calls


def _bar(day, close):
    return {"date": day, "open": close, "high": close, "low": close, "close": close, "volume": 1}


def test_a_dry_run_reports_and_writes_nothing(monkeypatch, capsys):
    rows = [_bar(date(2026, 9, 29), 91.0), _bar(date(2026, 9, 30), 91.5), _bar(date(2026, 10, 1), 92.0)]
    calls = _patch(monkeypatch, rows)
    assert run_script("fetch_cash_sweep_data", [], monkeypatch) == 0
    out = capsys.readouterr().out
    assert "2 rows" in out and "dry run" in out and "write" not in calls and calls["fetch"][2] == "2026-10-01"


def test_apply_writes_the_zip_beside_the_universe(tmp_path, monkeypatch, capsys):
    module = load_script("fetch_cash_sweep_data")
    monkeypatch.setattr(module, "ROOT_DIR", tmp_path)
    (tmp_path / "config.json").write_text((ROOT / "config.json").read_text(encoding="utf-8"), encoding="utf-8")
    calls = _patch(monkeypatch, [_bar(date(2026, 9, 29), 91.0), _bar(date(2026, 9, 30), 91.5)])
    monkeypatch.setattr(module.sys, "argv", ["x", "--apply"])
    assert module.main() == 0
    target, ticker, count = calls["write"]
    assert target.is_relative_to(tmp_path) and target.parent.is_dir() and count == 2 and "written" in capsys.readouterr().out


def test_nothing_from_yahoo_is_a_failure(monkeypatch, capsys):
    _patch(monkeypatch, [])
    assert run_script("fetch_cash_sweep_data", [], monkeypatch) == 1
    assert "returned nothing" in capsys.readouterr().out
