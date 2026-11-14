"""scripts/data_append_refresh.py's runtime (V6.6.6, #359): the stored closes, one asset's splice and append, the FRED caches and the dry-run or applied `main()`,
with Yahoo, FRED and the Lean writers replaced by fakes."""

from __future__ import annotations

import json
import sys
from datetime import date

import pytest

from script_loader import load_script


@pytest.fixture
def refresh(monkeypatch, tmp_path):
    module = load_script("data_append_refresh")
    monkeypatch.setattr(module, "ROOT_DIR", tmp_path)
    return module


def _row(day, close, **extra):
    return {"date": date.fromisoformat(day), "open": close, "high": close, "low": close, "close": close, "volume": 5, **extra}


def test_stored_closes_are_in_real_units_for_each_security_type(refresh, monkeypatch, tmp_path):
    monkeypatch.setattr(refresh, "_read_existing_lean_rows", lambda path: [_row("2020-01-02", 1_000_000.0), _row("2020-01-03", 1_010_000.0)] if "empty" not in str(path) else [])
    monkeypatch.setattr(refresh, "_read_existing_lean_forex_rows", lambda path: [{"date": date(2020, 1, 2), "bid_close": 1.1}])
    closes, newest = refresh.stored_closes(tmp_path / "aaa.zip", "equity")
    assert closes["2020-01-03"] == 101.0 and newest == date(2020, 1, 3)
    crypto, _ = refresh.stored_closes(tmp_path / "btc.zip", "crypto")
    assert crypto["2020-01-02"] == 1_000_000.0
    assert refresh.stored_closes(tmp_path / "fx.zip", "forex") == ({"2020-01-02": 1.1}, date(2020, 1, 2))
    assert refresh.stored_closes(tmp_path / "empty.zip", "equity") == ({}, None)


def _asset(tmp_path, security_type="equity", name="aaa.zip", *, create=True):
    path = tmp_path / "data" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if create:
        path.write_bytes(b"zip")
    return {"ticker": "AAA", "security_type": security_type, "data_path": f"data/{name}"}


def _world(refresh, monkeypatch, *, fetched, written):
    monkeypatch.setattr(refresh, "stored_closes", lambda path, security_type: ({"2020-01-02": 100.0, "2020-01-03": 101.0}, date(2020, 1, 3)))
    monkeypatch.setattr(refresh, "yahoo_symbol", lambda asset: "AAA")
    monkeypatch.setattr(refresh, "fetch_yahoo_ohlcv", lambda symbol, start, end: fetched)
    monkeypatch.setattr(refresh, "apply_price_overrides", lambda rows, override: (rows, 0))
    monkeypatch.setattr(refresh, "sanitize_ohlc", lambda rows: (rows, 0))
    monkeypatch.setattr(refresh, "scale_for_lean", lambda rows, security_type: rows)
    monkeypatch.setattr(refresh, "write_lean_zip", lambda path, ticker, rows, merge_with_existing: written.append(("default", path.name, len(rows))))
    monkeypatch.setattr(refresh, "write_lean_crypto_quote_zip", lambda trade, quote, ticker, merge_with_existing: written.append(("quote", quote.name)))
    monkeypatch.setattr(refresh, "ASSET_CLASS_CONFIG", {"stock": {"write_fn": lambda path, ticker, rows, merge_with_existing: written.append(("stock", path.name, len(rows)))}, "crypto": {}, "forex": {}})


def test_an_assets_missing_empty_or_dataless_state_is_reported_without_writing(refresh, monkeypatch, tmp_path):
    written = []
    _world(refresh, monkeypatch, fetched=[], written=written)
    assert refresh.refresh_asset(_asset(tmp_path, create=False), tmp_path, "2020-02-01", {}, apply=True) == {"status": "no_stored_file"}
    monkeypatch.setattr(refresh, "stored_closes", lambda path, security_type: ({}, None))
    assert refresh.refresh_asset(_asset(tmp_path), tmp_path, "2020-02-01", {}, apply=True) == {"status": "empty_stored_file"}
    _world(refresh, monkeypatch, fetched=[], written=written)
    assert refresh.refresh_asset(_asset(tmp_path), tmp_path, "2020-02-01", {}, apply=True) == {"status": "no_data", "yahoo_symbol": "AAA"} and written == []


def test_new_rows_are_scaled_onto_the_stored_basis_and_written_only_when_applied(refresh, monkeypatch, tmp_path):
    written = []
    fetched = [_row("2020-01-02", 50.0), _row("2020-01-03", 50.5), _row("2020-01-06", 51.0), _row("2020-01-07", 52.0)]
    _world(refresh, monkeypatch, fetched=fetched, written=written)
    dry = refresh.refresh_asset(_asset(tmp_path), tmp_path, "2020-02-01", {}, apply=False)
    assert dry["status"] == "ok" and dry["new_rows"] == 2 and dry["last_new"] == "2020-01-07" and dry["suspicious_ratio"] is True and dry["ratio_anchor"] == "2020-01-03" and written == []
    applied = refresh.refresh_asset(_asset(tmp_path), tmp_path, "2020-02-01", {}, apply=True)
    assert written == [("stock", "aaa.zip", 2)] and applied["new_rows"] == 2


def test_a_crypto_trade_file_also_refreshes_its_quote_file_and_an_up_to_date_asset_writes_nothing(refresh, monkeypatch, tmp_path):
    written = []
    _world(refresh, monkeypatch, fetched=[_row("2020-01-03", 101.0), _row("2020-01-06", 102.0)], written=written)
    report = refresh.refresh_asset(_asset(tmp_path, "crypto", "btcusd_trade.zip"), tmp_path, "2020-02-01", {}, apply=True)
    assert written == [("default", "btcusd_trade.zip", 1), ("quote", "btcusd_quote.zip")] and report["suspicious_ratio"] is False
    written.clear()
    monkeypatch.setattr(refresh, "fetch_yahoo_ohlcv", lambda symbol, start, end: [_row("2020-01-03", 101.0)])
    quiet = refresh.refresh_asset(_asset(tmp_path, "crypto", "btcusd_trade.zip"), tmp_path, "2020-02-01", {}, apply=True)
    assert quiet["new_rows"] == 0 and quiet["last_new"] is None and written == []
    other = refresh.refresh_asset(_asset(tmp_path, "crypto", "ethusd.zip"), tmp_path, "2020-02-01", {}, apply=True)
    assert other["status"] == "ok"
    no_overlap = []
    monkeypatch.setattr(refresh, "fetch_yahoo_ohlcv", lambda symbol, start, end: [_row("2020-02-03", 9.0)])
    assert refresh.refresh_asset(_asset(tmp_path), tmp_path, "2020-03-01", {}, apply=False)["no_overlap"] is True and no_overlap == []


def test_fred_caches_are_appended_after_the_cutoff_only(refresh, monkeypatch, tmp_path):
    cache = tmp_path / "data" / "reference" / "fred_series"
    cache.mkdir(parents=True)
    (cache / "have.csv").write_text("date,value\n2020-01-01,1.0\n", encoding="utf-8")
    (cache / "empty.csv").write_text("date,value\n2020-01-01,1.0\n", encoding="utf-8")
    monkeypatch.setattr(refresh, "reference_series", lambda config, scope: {"have": "H", "empty": "E", "gone": "G"})
    monkeypatch.setattr(refresh, "fetch_fred_series", lambda series_id, start, end: [] if series_id == "E" else [("2020-02-01", 2.0)])
    monkeypatch.setattr(refresh, "rows_to_cache_csv", lambda rows: "date,value\n" + "".join(f"{day},{value}\n" for day, value in rows))
    dry = refresh.refresh_fred({}, tmp_path, "2020-03-01", "2020-01-31", apply=False)
    assert dry == {"have": {"status": "ok", "rows_added": 1}, "empty": {"status": "no_data"}, "gone": {"status": "no_stored_file"}}
    assert "2020-02-01" not in (cache / "have.csv").read_text(encoding="utf-8")
    refresh.refresh_fred({}, tmp_path, "2020-03-01", "2020-01-31", apply=True)
    assert "2020-02-01,2.0" in (cache / "have.csv").read_text(encoding="utf-8")


def _main_world(refresh, monkeypatch, tmp_path, *, overrides=True):
    config = {"phase1": {"universe": {"assets": [{"ticker": "AAA", "security_type": "equity", "data_path": "x"}, {"ticker": "BIL", "security_type": "equity", "data_path": "y"},
                                                 {"ticker": "OPT", "security_type": "option", "data_path": "z"}]}}}
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    if overrides:
        (tmp_path / "data_pipeline").mkdir()
        (tmp_path / "data_pipeline" / "price_overrides.json").write_text("{}", encoding="utf-8")
    seen = []
    statuses = {"AAA": {"status": "ok", "new_rows": 3, "last_new": "2020-02-03", "ratio": 1.2, "suspicious_ratio": True, "no_overlap": False},
                "BIL": {"status": "no_data"}, "SPY": {"status": "ok", "new_rows": 1, "last_new": "2020-02-03", "ratio": 1.0, "suspicious_ratio": False, "no_overlap": False}}
    monkeypatch.setattr(refresh, "refresh_asset", lambda asset, root, end, overrides_, apply: seen.append((asset["ticker"], apply)) or statuses[asset["ticker"]])
    monkeypatch.setattr(refresh, "refresh_fred", lambda config_, root, end, cutoff, apply: {"a": {"status": "ok"}, "b": {"status": "no_data"}})
    return seen


def test_a_dry_run_reports_every_supported_asset_and_the_two_outside_the_universe(refresh, monkeypatch, tmp_path, capsys):
    seen = _main_world(refresh, monkeypatch, tmp_path, overrides=False)
    monkeypatch.setattr(sys, "argv", ["refresh", "--end", "2020-03-01"])
    assert refresh.main() == 0
    out = capsys.readouterr().out
    assert seen == [("AAA", False), ("BIL", False), ("SPY", False)] and "SUSPICIOUS" in out and "3 assets, 2 flagged: ['AAA', 'BIL']; FRED: 1 series" in out
    assert not (tmp_path / "ml").exists()


def test_an_applied_run_filters_tickers_skips_fred_on_request_and_writes_its_report(refresh, monkeypatch, tmp_path, capsys):
    seen = _main_world(refresh, monkeypatch, tmp_path)
    report = tmp_path / "out" / "refresh.json"
    monkeypatch.setattr(sys, "argv", ["refresh", "--apply", "--tickers", "AAA", "--skip-fred", "--report", str(report), "--end", "2020-03-01"])
    assert refresh.main() == 0
    written = json.loads(report.read_text(encoding="utf-8"))
    assert seen == [("AAA", True)] and written["fred"] == {} and set(written["assets"]) == {"AAA"} and written["end"] == "2020-03-01"
