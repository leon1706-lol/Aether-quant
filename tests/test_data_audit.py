"""data_pipeline/data_audit.py (V5.8.0): Lean daily zip audit and file manifest."""

from __future__ import annotations

import zipfile

import pandas as pd

from data_pipeline.data_audit import (
    audit_series,
    audit_universe,
    build_data_manifest,
    compare_manifests,
    read_lean_daily_zip,
)


def _write_zip(path, name, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, "\n".join(lines) + "\n")


def _equity_lines(days, price=100.0, jump_on=None):
    lines = []
    for index, day in enumerate(days):
        level = price * (0.5 if jump_on is not None and index >= jump_on else 1.0) * (1 + 0.001 * (index % 3))
        scaled = int(level * 10_000)
        lines.append(f"{day.strftime('%Y%m%d')} 00:00,{scaled},{scaled + 100},{scaled - 100},{scaled},1000")
    return lines



def test_equity_zip_scaling_outlier_and_gap(tmp_path):
    days = list(pd.bdate_range("2024-01-01", "2024-06-28"))
    del days[40:60]  # a 4-week hole
    _write_zip(tmp_path / "equity/usa/daily/abc.zip", "abc.csv", _equity_lines(days, jump_on=100))
    frame = read_lean_daily_zip(tmp_path / "equity/usa/daily/abc.zip", "equity")
    assert frame["close"].iloc[0] == 100.0
    report = audit_series(frame, "equity")
    assert any("missing weekdays" in problem for problem in report["problems"])
    assert report["outliers"] and report["outliers"][0]["return"] < -0.4
    assert report["largest_gap_days"] > 20


def test_forex_midpoint_and_crypto_calendar(tmp_path):
    _write_zip(tmp_path / "fx.zip", "eurusd.csv", ["20240102 00:00,1.0,1.1,0.9,1.05,0,1.2,1.3,1.1,1.25,0"])
    fx = read_lean_daily_zip(tmp_path / "fx.zip", "forex")
    assert abs(fx["close"].iloc[0] - 1.15) < 1e-12
    days = [d for d in pd.date_range("2024-01-01", "2024-01-20") if d.day != 10]
    lines = [f"{d.strftime('%Y%m%d')} 00:00,{100 + i},{102 + i},{99 + i},{101 + i},5" for i, d in enumerate(days)]
    _write_zip(tmp_path / "c.zip", "btcusd.csv", lines)
    crypto = audit_series(read_lean_daily_zip(tmp_path / "c.zip", "crypto"), "crypto")
    assert crypto["problems"] == ["1 missing calendar days"]


def test_universe_audit_flags_missing_and_short_quote_zip(tmp_path):
    days = list(pd.bdate_range("2024-01-01", "2024-03-29"))
    _write_zip(tmp_path / "equity/usa/daily/abc.zip", "abc.csv", _equity_lines(days))
    crypto_days = list(pd.date_range("2024-01-01", "2024-03-31"))
    trade = [f"{d.strftime('%Y%m%d')} 00:00,10,11,9,10.5,1" for d in crypto_days]
    _write_zip(tmp_path / "crypto/coinbase/daily/btcusd_trade.zip", "btcusd.csv", trade)
    quote = [f"{d.strftime('%Y%m%d')} 00:00,10,11,9,10.5,1,10,11,9,10.5,1" for d in crypto_days[:30]]
    _write_zip(tmp_path / "crypto/coinbase/daily/btcusd_quote.zip", "btcusd.csv", quote)
    config = {"phase1": {"universe": {"assets": [
        {"ticker": "ABC", "security_type": "equity", "data_path": "data/equity/usa/daily/abc.zip"},
        {"ticker": "BTCUSD", "security_type": "crypto", "data_path": "data/crypto/coinbase/daily/btcusd_trade.zip"},
        {"ticker": "GONE", "security_type": "equity", "data_path": "data/equity/usa/daily/gone.zip"},
    ]}}}
    report = audit_universe(config, tmp_path)
    assert report["assets"]["ABC"]["problems"] == [] and report["assets"]["ABC"]["factor_file"] is False
    assert any("quote zip ends" in problem for problem in report["assets"]["BTCUSD"]["problems"])
    assert set(report["flagged"]) == {"BTCUSD", "GONE"}


def test_manifest_detects_missing_and_changed_files(tmp_path):
    (tmp_path / "left/equity").mkdir(parents=True)
    (tmp_path / "right/equity").mkdir(parents=True)
    (tmp_path / "left/equity/a.csv").write_text("1")
    (tmp_path / "right/equity/a.csv").write_text("2")
    (tmp_path / "left/equity/only.csv").write_text("x")
    left = build_data_manifest(tmp_path / "left")
    right = build_data_manifest(tmp_path / "right")
    diff = compare_manifests(left, right)
    assert diff["differing"] == ["equity/a.csv"] and diff["only_left"] == ["equity/only.csv"] and not diff["identical"]
    assert compare_manifests(left, left)["identical"]


def test_non_daily_files_report_which_one_lean_reads(tmp_path):
    from data_pipeline.data_audit import audit_non_daily_files

    _write_zip(tmp_path / "equity/usa/hour/spy.zip", "spy.csv", ["20210331 15:00,1,1,1,1,1"])
    _write_zip(tmp_path / "equity/usa/minute/spy/20131011_trade.zip", "20131011_spy_minute_trade.csv", ["0,1,1,1,1,1"])
    _write_zip(tmp_path / "equity/usa/daily/spy.zip", "spy.csv", ["20260930 00:00,1,1,1,1,1"])
    config = {"phase1": {"universe": {"resolution": "Daily"}}, "runtime": {}}

    report = audit_non_daily_files(config, tmp_path)
    by_path = {entry["path"]: entry for entry in report["files"]}
    assert set(by_path) == {"equity/usa/hour/spy.zip", "equity/usa/minute/spy/20131011_trade.zip"}
    assert by_path["equity/usa/hour/spy.zip"]["last"] == "2021-03-31"
    assert by_path["equity/usa/minute/spy/20131011_trade.zip"]["last"] == "2013-10-11"
    assert report["read"] == ["equity/usa/hour/spy.zip"]

    config["runtime"]["benchmark_ticker"] = "SPY"
    assert audit_non_daily_files(config, tmp_path)["read"] == []
