"""scripts/build_holdout_data.py's runtime (V6.6.6, #359): the Yahoo symbol of each asset, the staging path, and the dry-run or applied command over a three-asset
universe, with Yahoo, FRED and the Lean writers stood in."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

from script_loader import load_script


@pytest.fixture
def module(monkeypatch, tmp_path):
    holdout = load_script("build_holdout_data")
    monkeypatch.setattr(holdout, "ROOT_DIR", tmp_path)
    return holdout


def _row(day, close=10.0):
    return {"date": date.fromisoformat(day), "open": close, "high": close, "low": close, "close": close, "volume": 1}


def test_the_staging_path_drops_the_data_folder_prefix(module, tmp_path):
    assert module.holdout_zip_path(tmp_path / "stage", {"data_path": "data/equity/usa/daily/aaa.zip"}) == tmp_path / "stage" / "equity" / "usa" / "daily" / "aaa.zip"


def test_a_yahoo_symbol_is_explicit_renamed_or_the_class_default(module):
    assert module.yahoo_symbol({"ticker": "AAA", "security_type": "equity", "backfill": {"symbol": "AAA.X"}}) == "AAA.X"
    assert module.yahoo_symbol({"ticker": "FB", "security_type": "equity"}) == "META"
    assert module.yahoo_symbol({"ticker": "BTCUSD", "security_type": "crypto"}) == "BTC-USD"


def _world(module, monkeypatch, tmp_path, *, overrides):
    config = {"phase1": {"universe": {"assets": [
        {"ticker": "AAA", "security_type": "equity", "data_path": "data/equity/usa/daily/aaa.zip"},
        {"ticker": "BTCUSD", "security_type": "crypto", "data_path": "data/crypto/coinbase/daily/btcusd_trade.zip"},
        {"ticker": "GONE", "security_type": "equity", "data_path": "data/equity/usa/daily/gone.zip"},
        {"ticker": "OPT", "security_type": "option", "data_path": "data/option/x.zip"},
        {"ticker": "EURUSD", "security_type": "forex", "data_path": "data/forex/oanda/daily/eurusd.zip"}]}}}
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    if overrides:
        (tmp_path / "data_pipeline").mkdir()
        (tmp_path / "data_pipeline" / "price_overrides.json").write_text(json.dumps({"AAA": {"x": 1}}), encoding="utf-8")
    written = []
    monkeypatch.setattr(module, "fetch_yahoo_ohlcv", lambda symbol, start, end: [] if symbol == "GONE" else [_row("2020-01-02"), _row("2020-01-03")])
    monkeypatch.setattr(module, "apply_price_overrides", lambda rows, override: (rows, 1 if override else 0))
    monkeypatch.setattr(module, "sanitize_ohlc", lambda rows: (rows, 0))
    monkeypatch.setattr(module, "scale_for_lean", lambda rows, security_type: rows)
    monkeypatch.setattr(module, "write_lean_zip", lambda path, ticker, rows, merge_with_existing: written.append(("zip", path.name)))
    monkeypatch.setattr(module, "write_lean_crypto_quote_zip", lambda trade, quote, ticker, merge_with_existing: written.append(("quote", quote.name)))
    monkeypatch.setattr(module, "ASSET_CLASS_CONFIG", {"stock": {"yahoo_symbol_fn": lambda ticker: ticker}, "crypto": {"yahoo_symbol_fn": lambda ticker: ticker, "write_fn": lambda path, ticker, rows, merge_with_existing: written.append(("crypto", path.name))},
                                                       "forex": {"yahoo_symbol_fn": lambda ticker: ticker}})
    monkeypatch.setattr(module, "reference_series", lambda config_, scope: {"dgs10": "DGS10", "empty": "EMPTY"})
    monkeypatch.setattr(module, "fetch_fred_series", lambda series_id, start, end: [] if series_id == "EMPTY" else [("2020-01-02", 1.0)])
    fred = []
    monkeypatch.setattr(module, "write_fred_series_cache", lambda folder, key, rows: fred.append((folder.name, key)))
    return written, fred


def test_a_dry_run_reports_every_asset_and_writes_nothing(module, monkeypatch, tmp_path, capsys):
    written, fred = _world(module, monkeypatch, tmp_path, overrides=False)
    monkeypatch.setattr(sys, "argv", ["build_holdout_data"])
    assert module.main() == 0
    out = capsys.readouterr().out
    assert written == [] and fred == [] and "NO DATA" in out and "3 assets ok, 2 without holdout data" in out and not (tmp_path / "data_v6_staging").exists()


def test_an_applied_run_writes_the_zips_the_crypto_quote_file_the_fred_caches_and_a_report(module, monkeypatch, tmp_path):
    written, fred = _world(module, monkeypatch, tmp_path, overrides=True)
    monkeypatch.setattr(sys, "argv", ["build_holdout_data", "--apply", "--root", "stage", "--report-name", "refresh.json"])
    assert module.main() == 0
    assert ("zip", "aaa.zip") in written and ("crypto", "btcusd_trade.zip") in written and ("quote", "btcusd_quote.zip") in written and ("zip", "eurusd.zip") in written and fred == [("fred_series", "dgs10")]
    report = json.loads((tmp_path / "stage" / "refresh.json").read_text(encoding="utf-8"))
    assert report["assets"]["AAA"]["price_overrides_applied"] == 1 and report["assets"]["OPT"]["status"] == "skipped_security_type" and report["fred_rows"] == {"dgs10": 1, "empty": 0}


def test_the_ticker_filter_and_skip_fred_narrow_the_run(module, monkeypatch, tmp_path, capsys):
    written, fred = _world(module, monkeypatch, tmp_path, overrides=False)
    monkeypatch.setattr(sys, "argv", ["build_holdout_data", "--apply", "--tickers", "AAA", "--skip-fred", "--root", "stage"])
    assert module.main() == 0
    assert written == [("zip", "aaa.zip")] and fred == [] and "FRED rows: {}" in capsys.readouterr().out and Path(tmp_path / "stage" / "holdout_report.json").exists()
