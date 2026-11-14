"""scripts/v660_venue_study.py (V6.6.6): the spot-ETF proxies' bars, their tracking of the coins, and one Lean run config."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from script_loader import ROOT, load_script


def test_proxy_rows_keep_btc_and_eth_from_the_first_full_date():
    module = load_script("v660_venue_study")
    weights = {"2024-07-01": {"BTCUSD": 0.1}, "2024-08-02": {"BTCUSD": 0.1, "ETHUSD": 0.05, "LTCUSD": 0.02}, "2024-09-03": {}}
    assert module.proxy_rows(weights) == {"2024-08-02": {"IBIT": 0.1, "ETHA": 0.05}, "2024-09-03": {}}


def test_fetch_writes_each_proxy_that_has_bars(tmp_path, monkeypatch):
    module = load_script("v660_venue_study")
    bars = {"IBIT": [{"date": pd.Timestamp("2024-08-01"), "close": 1.0}, {"date": pd.Timestamp("2024-08-02"), "close": 1.1}], "ETHA": []}
    monkeypatch.setattr(module, "fetch_adjusted_and_raw", lambda ticker, start, end: (bars[ticker], None))
    monkeypatch.setattr(module, "sanitize_ohlc", lambda rows: (rows, 0))
    written = []
    monkeypatch.setattr(module, "scale_for_lean", lambda rows, kind: rows)
    monkeypatch.setattr(module, "write_lean_zip", lambda path, ticker, rows, merge_with_existing: written.append((path.name, len(rows))))
    report = module.fetch_proxies(tmp_path)
    assert report["IBIT"] == {"status": "ok", "first": "2024-08-01T00:00:00", "last": "2024-08-02T00:00:00", "rows": 2} and report["ETHA"] == {"status": "no bars"}
    assert written == [("ibit.zip", 2)] and (tmp_path / "equity" / "usa" / "daily").is_dir()


def _closes(seed):
    dates = pd.bdate_range("2024-08-01", periods=40)
    prices = 100.0 * np.cumprod(1.0 + np.random.default_rng(seed).normal(0.0, 0.02, len(dates)))
    return pd.DataFrame({"date": dates, "close": prices})


def test_tracking_reports_daily_and_weekly_links(tmp_path, monkeypatch):
    module = load_script("v660_venue_study")
    monkeypatch.setattr(module, "read_lean_daily_zip", lambda path, kind: _closes(1 if kind == "equity" else 2))
    report = module.tracking(tmp_path)
    assert set(report) == {"IBIT", "ETHA"} and report["IBIT"]["coin"] == "BTCUSD" and report["IBIT"]["sessions"] > 30
    assert -1.0 <= report["ETHA"]["weekly_correlation"] <= 1.0 and report["ETHA"]["weekly_tracking_error_annual"] > 0


def test_make_writes_the_weights_the_run_and_the_report(tmp_path, monkeypatch, capsys):
    module = load_script("v660_venue_study")
    (tmp_path / "config.json").write_text((ROOT / "config.json").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "OUT", tmp_path)
    monkeypatch.setattr(module, "WEIGHTS", tmp_path / "weights")
    monkeypatch.setattr(module, "fetch_proxies", lambda root: {"IBIT": {"status": "ok"}})
    monkeypatch.setattr(module, "tracking", lambda root: {"IBIT": {"weekly_correlation": 0.9}})
    monkeypatch.setattr(module, "load_weight_file", lambda path, sha: {"2024-08-02": {"BTCUSD": 0.1}})
    seen = {}
    monkeypatch.setattr(module, "target_path_config", lambda config, **kwargs: seen.update(config=config, **kwargs) or {"run": True})
    monkeypatch.setattr(module, "write_run", lambda name, run, data_root: {"name": name, "data_root": data_root})
    monkeypatch.setattr(module.sys, "argv", ["x", "make"])
    assert module.main() == 0
    report = json.loads((tmp_path / "venue_study.json").read_text(encoding="utf-8"))
    assert report["run"]["name"] == "v660_venue_etf" and report["run"]["role"] == "plumbing" and report["tracking"]["IBIT"]["weekly_correlation"] == 0.9
    assert [asset["ticker"] for asset in seen["config"]["phase1"]["universe"]["assets"]] == ["SPY", "AGG", "IBIT", "ETHA"]
    assert (tmp_path / "weights" / "v660_venue_etf.csv").exists() and '"routes"' in capsys.readouterr().out
