"""data_pipeline/yfinance_backfill.py's remaining branches (V6.6.6, #359): the price overrides, the OHLC sanitiser, blank lines in stored
zips, the Yahoo download's failure shapes, the empty-fetch action and the command line."""

from __future__ import annotations

import json
import sys
from datetime import date
from types import ModuleType
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest

from data_pipeline import yfinance_backfill as yb


def _row(day, **fields):
    return {"date": day, "open": 10.0, "high": 12.0, "low": 9.0, "close": 11.0, "volume": 100.0, **fields}


def test_overrides_replace_only_the_dated_fields():
    rows = [_row(date(2025, 1, 2)), _row("2025-01-03")]
    out, changed = yb.apply_price_overrides(rows, [{"date": "2025-01-02", "set": {"close": 5}}, {"date": "2025-01-03T00:00", "set": {"high": 13}}])
    assert changed == 2 and out[0]["close"] == 5.0 and out[1]["high"] == 13.0 and rows[0]["close"] == 11.0
    assert yb.apply_price_overrides(rows, None) == (rows, 0)
    assert yb.apply_price_overrides(rows, [{"date": "2030-01-01", "set": {"close": 1}}])[1] == 0


def test_the_sanitiser_widens_high_and_low_to_contain_open_and_close():
    out, changed = yb.sanitize_ohlc([_row(date(2025, 1, 2), high=10.5, low=10.8), _row(date(2025, 1, 3))])
    assert changed == 1 and out[0]["high"] == 11.0 and out[0]["low"] == 10.0 and out[1]["high"] == 12.0


def _zip(path, text):
    with ZipFile(path, "w") as archive:
        archive.writestr(path.stem + ".csv", text)


def test_stored_zips_with_blank_lines_read_back(tmp_path):
    daily = tmp_path / "d.zip"
    _zip(daily, "20250102 00:00,1,2,0.5,1.5,10\n\n20250103 00:00,1,2,0.5,1.5,10\n")
    assert [row["date"] for row in yb._read_existing_lean_rows(daily)] == [date(2025, 1, 2), date(2025, 1, 3)]
    quote = "20250102 00:00,1,2,0.5,1.5,0,1,2,0.5,1.5,0\n\n"
    forex, crypto = tmp_path / "f.zip", tmp_path / "c.zip"
    _zip(forex, quote)
    _zip(crypto, quote)
    assert len(yb._read_existing_lean_forex_rows(forex)) == 1 and len(yb._read_existing_lean_crypto_quote_rows(crypto)) == 1


def _install_yfinance(monkeypatch, download):
    module = ModuleType("yfinance")
    module.download = download
    monkeypatch.setitem(sys.modules, "yfinance", module)


def test_a_failed_or_empty_download_gives_no_rows_and_bad_rows_are_dropped(monkeypatch):
    _install_yfinance(monkeypatch, lambda *a, **k: (_ for _ in ()).throw(RuntimeError("rate limited")))
    assert yb.fetch_yahoo_ohlcv("BTC-USD", "2025-01-01", "2025-01-05") == []
    _install_yfinance(monkeypatch, lambda *a, **k: pd.DataFrame())
    assert yb.fetch_yahoo_ohlcv("BTC-USD", "2025-01-01", "2025-01-05") == []
    index = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-04"])
    columns = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Volume"], ["BTC-USD"]])
    frame = pd.DataFrame(np.array([[1, 2, 0.5, 1.5, 10], [np.nan] * 5, [1, 2, 0.5, 1.5, 10]], dtype=float), index=index, columns=columns)
    _install_yfinance(monkeypatch, lambda *a, **k: frame)
    rows = yb.fetch_yahoo_ohlcv("BTC-USD", "2025-01-01", "2025-01-05")
    assert [row["date"] for row in rows] == [date(2025, 1, 2), date(2025, 1, 4)]
    odd = pd.DataFrame({"Open": ["x"], "High": [2.0], "Low": [1.0], "Close": [1.5], "Volume": [1.0]}, index=index[:1])
    _install_yfinance(monkeypatch, lambda *a, **k: odd)
    assert yb.fetch_yahoo_ohlcv("BTC-USD", "2025-01-01", "2025-01-05") == []
    missing = pd.DataFrame({"Open": [1.0]}, index=index[:1])
    _install_yfinance(monkeypatch, lambda *a, **k: missing)
    assert yb.fetch_yahoo_ohlcv("BTC-USD", "2025-01-01", "2025-01-05") == []


def test_a_backfill_with_no_rows_reports_no_data(tmp_path):
    plan = [{"ticker": "X", "security_type": "crypto", "yahoo_symbol": "X-USD", "data_path": str(tmp_path / "x.zip"), "gap": {"needs_backfill": True, "fetch_start": date(2025, 1, 1), "fetch_end": date(2025, 1, 5)}}]
    report = yb.run_backfill({}, plan, apply=True, fetch_fn=lambda symbol, start, end: [])
    assert report["entries"][0]["action"] == "no_data_returned" and report["entries"][0]["suggested_available_from"] is None


def _config(tmp_path, assets):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"phase1": {"universe": {"assets": assets}}}), encoding="utf-8")
    return path


def test_the_quote_command_synthesises_or_skips_by_what_exists(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(yb, "ROOT", tmp_path)
    trade = tmp_path / "data" / "btcusd_trade.zip"
    trade.parent.mkdir()
    _zip(trade, "20250102 00:00,1,2,0.5,1.5,10\n")
    assets = [{"ticker": "BTCUSD", "security_type": "crypto", "data_path": "data/btcusd_trade.zip"}, {"ticker": "ETHUSD", "security_type": "crypto", "data_path": "data/ethusd_trade.zip"}]
    config = _config(tmp_path, assets)
    monkeypatch.setattr(sys, "argv", ["yf", "--quotes", "--config-path", str(config)])
    yb.main()
    out = capsys.readouterr().out
    assert "SKIPPED (trade zip missing" in out and "quote=missing (would create)" in out and "Dry run only" in out
    monkeypatch.setattr(sys, "argv", ["yf", "--quotes", "--apply", "--config-path", str(config), "--tickers", "BTCUSD"])
    yb.main()
    assert "written 1 row(s)" in capsys.readouterr().out and (tmp_path / "data" / "btcusd_quote.zip").exists()
    monkeypatch.setattr(sys, "argv", ["yf", "--quotes", "--config-path", str(config), "--tickers", "NOPE"])
    yb.main()
    assert "No crypto assets found" in capsys.readouterr().out


def test_the_backfill_command_plans_runs_and_prints(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(yb, "ROOT", tmp_path)
    config = _config(tmp_path, [{"ticker": "BTCUSD", "security_type": "crypto", "data_path": "data/btcusd_trade.zip"}])
    monkeypatch.setattr(sys, "argv", ["yf", "--config-path", str(config)])
    yb.main()
    assert "No assets with a 'backfill' config block" in capsys.readouterr().out
    plan = [{"ticker": "BTCUSD", "yahoo_symbol": "BTC-USD"}]
    monkeypatch.setattr(yb, "plan_backfill", lambda config, tickers=None: plan)
    report = {"entries": [{"ticker": "BTCUSD", "yahoo_symbol": "BTC-USD", "action": "dry_run", "rows_fetched": 2, "suggested_available_from": date(2025, 1, 2), "suggested_available_to": date(2025, 1, 3), "data_path": "p"}]}
    monkeypatch.setattr(yb, "run_backfill", lambda config, plan, apply: report)
    yb.main()
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "BTCUSD (BTC-USD): dry_run, rows_fetched=2" in out and "Dry run only" in out
    monkeypatch.setattr(sys, "argv", ["yf", "--apply", "--config-path", str(config)])
    yb.main()
    assert "APPLY" in capsys.readouterr().out
    assert pytest is not None
