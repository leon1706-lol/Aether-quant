"""data_pipeline/dividend_backfill.py and factor_file_backfill.py's remaining branches (V6.6.6, #359): the Yahoo calls and both commands."""

from __future__ import annotations

import json
import sys
from datetime import date
from types import ModuleType, SimpleNamespace

import pandas as pd

from data_pipeline import dividend_backfill as db
from data_pipeline import factor_file_backfill as ff


def _yahoo(monkeypatch, ticker):
    module = ModuleType("yfinance")
    module.Ticker = ticker
    monkeypatch.setitem(sys.modules, "yfinance", module)


def test_dividend_history_is_sorted_empty_or_fails_open(monkeypatch):
    series = pd.Series([0.5, 0.4], index=pd.to_datetime(["2025-03-01", "2025-01-01"]))
    _yahoo(monkeypatch, lambda symbol: SimpleNamespace(dividends=series))
    assert db.fetch_dividend_history("AAA") == [{"ex_date": date(2025, 1, 1), "amount": 0.4}, {"ex_date": date(2025, 3, 1), "amount": 0.5}]
    _yahoo(monkeypatch, lambda symbol: SimpleNamespace(dividends=pd.Series(dtype=float)))
    assert db.fetch_dividend_history("AAA") == []
    _yahoo(monkeypatch, lambda symbol: (_ for _ in ()).throw(RuntimeError("down")))
    assert db.fetch_dividend_history("AAA") == []


def test_the_dividend_command_reports_each_ticker(tmp_path, monkeypatch, capsys):
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    histories = {"AAA": [{"ex_date": date(2025, 1, 1), "amount": 0.4}], "BBB": []}
    monkeypatch.setattr(db, "fetch_dividend_history", lambda ticker: histories[ticker])
    monkeypatch.setattr(db, "option_underlying_tickers", lambda cfg: ["AAA", "BBB"])
    written = []
    monkeypatch.setattr(db, "write_dividend_schedule", lambda cache, ticker, history, as_of: written.append(ticker))
    monkeypatch.setattr(sys, "argv", ["dividends", "--config-path", str(config), "--cache-dir", str(tmp_path / "c")])
    db.main()
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "AAA: dry_run, events_fetched=1" in out and "BBB: no_data_returned" in out and "Dry run only" in out and not written
    monkeypatch.setattr(sys, "argv", ["dividends", "--apply", "--tickers", "AAA", "--config-path", str(config), "--cache-dir", str(tmp_path / "c")])
    db.main()
    assert "AAA: written" in capsys.readouterr().out and written == ["AAA"]


def test_the_reference_ratio_skips_unreadable_zip_rows():
    rows = [["20250102", "0", "0", "0", "bad"], ["20250103"], ["20250104", "0", "0", "0", "20000"]]
    factors = [{"reference_price": "2.0", "factor_date": "20250104"}, {"reference_price": "0", "factor_date": "20250102"}]
    assert ff.reference_ratio_median(rows, factors) == 1.0


def test_a_short_factor_file_line_is_skipped(tmp_path):
    path = tmp_path / "aaa.csv"
    path.write_text("20250104,1,1\n20250105,1.0,1.0,100.0\n", encoding="utf-8")
    assert len(ff.read_factor_file_rows(path)) == 1


def test_corporate_actions_come_from_yahoo_or_none(monkeypatch):
    frame = pd.DataFrame({"Close": [1.0]}, index=pd.to_datetime(["2025-01-02"]))
    _yahoo(monkeypatch, lambda symbol: SimpleNamespace(history=lambda **kwargs: frame))
    assert ff.fetch_corporate_actions("AAA") is frame
    _yahoo(monkeypatch, lambda symbol: SimpleNamespace(history=lambda **kwargs: pd.DataFrame()))
    assert ff.fetch_corporate_actions("AAA") is None
    _yahoo(monkeypatch, lambda symbol: (_ for _ in ()).throw(RuntimeError("down")))
    assert ff.fetch_corporate_actions("AAA") is None


def test_the_factor_file_command_skips_what_needs_no_file_and_writes_the_rest(tmp_path, monkeypatch, capsys):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"phase1": {"universe": {"assets": [{"ticker": "ADJ", "data_path": "adj.zip"}, {"ticker": "NONE"}, {"ticker": "FLAT"}, {"ticker": "OK"}]}}}), encoding="utf-8")
    monkeypatch.setattr(ff, "ROOT", tmp_path)
    monkeypatch.setattr(ff, "tickers_missing_factor_file", lambda tickers, directory: ["ADJ", "NONE", "FLAT", "OK"])
    monkeypatch.setattr(ff, "configured_equity_tickers", lambda cfg: [])
    monkeypatch.setattr(ff, "read_zip_daily_rows", lambda path: [["x"]])
    monkeypatch.setattr(ff, "zip_written_by_yfinance_backfill", lambda rows: bool(rows))
    # only ADJ has a zip path, so only it reads rows; the others see no rows
    histories = {"NONE": None, "FLAT": object(), "OK": object()}
    monkeypatch.setattr(ff, "fetch_corporate_actions", lambda ticker: histories[ticker])
    monkeypatch.setattr(ff, "compute_lean_factor_rows", lambda history: [] if history is histories["FLAT"] else [{"a": 1}, {"a": 2}])
    written = []
    monkeypatch.setattr(ff, "write_factor_file", lambda directory, ticker, rows: written.append(ticker))
    monkeypatch.setattr(sys, "argv", ["factors", "--config-path", str(config), "--output-dir", str(tmp_path / "out")])
    assert ff.main() == 0
    out = capsys.readouterr().out
    assert "ADJ: skipped_zip_already_adjusted" in out and "NONE: no_data_returned" in out and "FLAT: skipped_no_corporate_actions" in out and "OK: dry_run, factor_rows=1" in out and "Dry run only" in out
    monkeypatch.setattr(sys, "argv", ["factors", "--apply", "--config-path", str(config), "--output-dir", str(tmp_path / "out")])
    assert ff.main() == 0 and written == ["OK"]
