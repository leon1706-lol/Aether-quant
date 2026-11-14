"""The last small branches of evaluation/ (V6.6.6, #359): probability calibration, README statistics, fill prices, round builders, feature parity,
the research cycle's host checks, factor exposure and the backtest audit's time parsing."""

from __future__ import annotations

import json
import sys
import zipfile
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from evaluation import (
    backtest_audit,
    factor_neutralization_check,
    feature_parity,
    fill_price_audit,
    probability_calibration as calibration,
    readme_statistics,
    research_cycle,
    round_builders,
)


def test_calibration_helpers_refuse_what_they_cannot_judge(monkeypatch):
    monkeypatch.setattr(calibration, "reliability_curve", lambda probability, outcome, bins: [])
    assert calibration.expected_calibration_error([0.5], [1]) is None
    few = np.linspace(0.1, 0.9, 6)
    assert calibration.fit_isotonic(few, [0, 1] * 3) is None
    many = np.linspace(0.05, 0.95, 40)
    assert calibration.fit_isotonic(many, [1] * 40) is None
    assert calibration.balanced_accuracy([], []) is None and calibration.balanced_accuracy(many, [1] * 40) is None
    assert calibration.balanced_accuracy([0.2, 0.8, 0.6, 0.4], [0, 1, 1, 0]) == 1.0
    assert calibration.cross_fitted_log_loss(few, [0, 1] * 3, "raw") is None
    outcomes = np.array(([0, 1] * 20))
    assert calibration.cross_fitted_log_loss(many, outcomes, "raw") is not None
    with pytest.raises(ValueError):
        calibration.cross_fitted_log_loss(many, outcomes, "mystery")
    monkeypatch.setattr(calibration, "fit_temperature", lambda p, y: None)
    assert calibration.cross_fitted_log_loss(many, outcomes, "temperature") is None
    monkeypatch.setattr(calibration, "fit_isotonic", lambda p, y: None)
    assert calibration.cross_fitted_log_loss(many, outcomes, "isotonic") is None


def test_readme_statistics_formats_and_degrades(tmp_path):
    assert readme_statistics._format("abc", "int") == "abc" and readme_statistics._format(12345.6, "int") == "12,346"
    path = tmp_path / readme_statistics.STATISTICS_FILE
    path.write_text("{torn", encoding="utf-8")
    assert readme_statistics._load(path) is None
    assert all(body == readme_statistics._NOT_RUN for body in readme_statistics.build_backtest_statistics_blocks(tmp_path).values())
    path.write_text(json.dumps({"status": "OK", "sections": {"general": [{"metric": "m", "portfolio": 1.0, "strategy": 2.0, "fmt": "num"}]}}), encoding="utf-8")
    blocks = readme_statistics.build_backtest_statistics_blocks(tmp_path)
    assert blocks["general"] != readme_statistics._NOT_RUN and blocks[next(name for name in readme_statistics.SECTIONS if name != "general")] == readme_statistics._NOT_RUN
    table = readme_statistics._attribution_table({"classes": [], "unattributed_pnl": 5.0, "components": []}, {})
    assert "unattributed (Lean minus rebuilt)" in table


def _zip(path, text):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(path.stem + ".csv", text)


def test_fill_prices_skip_broken_events_and_rows(tmp_path):
    stamp = datetime(2024, 1, 3, 20, tzinfo=timezone.utc).timestamp()
    run = {"result": {"orders": {}}, "order_events": [
        {"status": "filled", "fillPrice": "x", "fillQuantity": 1, "time": stamp, "symbolValue": "A", "orderId": 1},
        {"status": "filled", "fillPrice": 10.0, "fillQuantity": 0, "time": stamp, "symbolValue": "A", "orderId": 1},
        {"status": "filled", "fillPrice": 10.0, "fillQuantity": 1, "symbolValue": "A", "orderId": 1},
        {"status": "filled", "fillPrice": 10.0, "fillQuantity": 1, "time": stamp, "symbolValue": "A", "orderId": 1}]}
    assert len(fill_price_audit.fills_from_run(run)) == 1
    factor = tmp_path / "a.csv"
    factor.write_text("short,1\n20240102,x,1.0,10\n20240103,1.0,1.0,10\n", encoding="utf-8")
    assert len(fill_price_audit.read_factor_file(factor)) == 1
    assert np.isnan(fill_price_audit._quantile([], 0.5)) and fill_price_audit._distribution([]) == {"n": 0}


def test_a_traded_symbol_without_a_zip_has_no_open(tmp_path, monkeypatch):
    monkeypatch.setattr(fill_price_audit, "lean_daily_zip_path", lambda root, symbol, asset_class: None)
    assert fill_price_audit.zip_opens_for_fills([{"symbol": "ZZZ", "asset_class": "equity"}], tmp_path) == {}


def test_round_builders_name_what_is_missing(tmp_path):
    known = pd.DataFrame({"A": [1.0, 2.0]}, index=["2024-01-02", "2024-01-03"])
    cell = SimpleNamespace(root=tmp_path, data_dir="data", features={"a": 1}, context=SimpleNamespace(panel=SimpleNamespace(known=known)))
    reference = tmp_path / "data" / "reference"
    reference.mkdir(parents=True)
    pd.DataFrame({"ticker": ["A"]}).to_csv(reference / "edgar_fundamentals.csv.gz", index=False, compression="gzip")
    pd.DataFrame({"ticker": ["B"]}).to_csv(reference / "edgar_fundamentals_ext.csv.gz", index=False, compression="gzip")
    assert list(round_builders._fundamentals(cell)["ticker"]) == ["A", "B"] and round_builders._feature(cell, "a") == 1
    with pytest.raises(round_builders.MissingInput):
        round_builders._feature(cell, "missing")
    with pytest.raises(round_builders.MissingInput, match="without a data root"):
        round_builders._fred_known(SimpleNamespace(root=None, data_dir="data"))
    with pytest.raises(round_builders.MissingInput, match="is not here"):
        round_builders._fred_known(cell)
    series = reference / "fred_series"
    series.mkdir()
    for key, value in (("treasury_10yr", 4.0), ("treasury_3mo", 5.0), ("credit_spread_baa10y", 1.5)):
        (series / f"{key}.csv").write_text(f"2024-01-02,{value}" + chr(10), encoding="utf-8")
    assert not round_builders._fred_known(cell).empty


def test_a_feature_comparison_reports_mismatches_and_saturation():
    stored = np.array([0.0, 0.5, np.nan, 1.0])
    raw = np.array([0.0, 1.0, 2.0, 99.0])
    result = feature_parity.summarize_comparison(stored, raw, mean=0.0, scale=1.0, clip=1.0, warmup_excluded=2)
    assert result["n_compared"] == 3 and result["warmup_excluded_per_ticker"] == 2 and result["verdict"] in ("PASS", "FAIL") and result["n_saturated_at_clip"] >= 1
    assert feature_parity.summarize_comparison(np.array([np.nan]), np.array([np.nan]), 0.0, 1.0, 1.0)["max_abs_delta"] is None


def test_host_checks_read_posix_memory_and_name_unknown_platforms(monkeypatch):
    monkeypatch.setattr(research_cycle.sys, "platform", "linux")
    monkeypatch.setattr(research_cycle.os, "sysconf", lambda name: 4096 if name == "SC_PAGE_SIZE" else 1000, raising=False)
    assert research_cycle.total_memory_bytes() == 4096 * 1000
    monkeypatch.setattr(research_cycle.os, "sysconf", lambda name: (_ for _ in ()).throw(OSError("no")), raising=False)
    assert research_cycle.total_memory_bytes() is None
    monkeypatch.setattr(research_cycle, "total_memory_bytes", lambda: None)
    assert research_cycle.ram_preflight("local")["ok"] is False
    with pytest.raises(ValueError):
        research_cycle.install_command("plan9", task_file="x")


def test_a_wound_down_generation_is_due_for_retirement():
    entries = {"g1": {"stage": "winding_down"}}
    judged = {"generations": {}, "latest_allocation": {"shares": {"g1": 0.0}}}
    actions = research_cycle.due_actions(entries, judged, session="2026-11-02", sessions_behind=0, sessions_since_retrain=1, broker_keys=True, record_started=True, policy_enabled=True)
    assert any("--to retired" in action["action"] for action in actions)


def test_factor_exposure_uses_sector_series_and_names_a_singular_design(monkeypatch):
    rng = np.random.default_rng(0)
    index = pd.bdate_range("2024-01-01", periods=60)
    market = pd.Series(rng.normal(0, 0.01, 60), index=index)
    book = 0.5 * market + pd.Series(rng.normal(0, 0.002, 60), index=index)
    sectors = {"tech": pd.Series(rng.normal(0, 0.01, 60), index=index)}
    result = factor_neutralization_check.compute_factor_exposure(book, market, sector_returns=sectors)
    assert "sector_tech" in result["loadings"]
    monkeypatch.setattr(factor_neutralization_check.np.linalg, "solve", lambda a, b: (_ for _ in ()).throw(np.linalg.LinAlgError("singular")))
    assert factor_neutralization_check.compute_factor_exposure(book, market)["error"] == "singular design matrix"


def test_the_backtest_audit_parses_bad_times_and_odd_symbols():
    assert backtest_audit._parse_time("not a time") is None
    assert backtest_audit._symbol_value({"symbol": None}) == "" and backtest_audit._symbol_value({"symbol": "BTCUSD"}) == "BTCUSD"
    stamp = datetime(2024, 1, 2, tzinfo=timezone.utc).timestamp()
    chart = {"charts": {"Strategy Equity": {"series": {"Equity": {"values": [["junk", 1.0], ["2024-01-02T00:00:00Z", 1001.0]]}}}}}
    assert backtest_audit.daily_equity_from_chart(chart) == [("2024-01-02", 1001.0)]
    assert backtest_audit.holding_period_histogram([{"entryTime": "2024-01-01T00:00:00Z"}, {"entryTime": "2024-01-01T00:00:00Z", "exitTime": "2024-01-05T00:00:00Z"}])
    assert stamp > 0 and sys is not None


def test_the_audit_summarises_each_requested_period():
    stamps = [datetime(2024, 1, day, tzinfo=timezone.utc).timestamp() for day in range(1, 6)]
    result = {"charts": {"Strategy Equity": {"series": {"Equity": {"values": [[stamp, 1000.0 + 10 * index] for index, stamp in enumerate(stamps)]}}}}, "orders": {}, "totalPerformance": {"closedTrades": []}, "statistics": {}}
    audit = backtest_audit.audit_backtest_run({"result": result, "run_id": "1", "order_events": [], "engine_log": ""}, [], periods=[("2024-01-02", "2024-01-04")])
    assert len(audit["periods"]) == 1


def test_a_liquidity_replica_falls_back_below_two_bars_and_estimates_after():
    frame = pd.DataFrame({"close": [10.0, 11.0, 12.0], "volume": [100.0, 100.0, 100.0], "high": [10.5, 11.5, 12.6], "low": [9.5, 10.4, 11.4]})
    replica = feature_parity.compute_liquidity_replica(frame, security_type="equity")
    assert replica["liquidity_spread_proxy"][0] > 0 and len(replica["liquidity_log_dollar_volume"]) == 3


def test_a_stale_ledger_is_flagged_for_the_schedule():
    actions = research_cycle.due_actions({}, {}, session="2026-01-01", sessions_behind=99, sessions_since_retrain=1, broker_keys=True, record_started=True, policy_enabled=True)
    assert any("workflow enable" in action["action"] for action in actions)


def test_the_book_factor_exposure_skips_thin_or_marketless_data_and_regresses_otherwise():
    rng = np.random.default_rng(4)
    index = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2023-01-02", periods=120)]
    pivot = pd.DataFrame(100.0 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, (120, 12)), axis=0)), index=index, columns=["SPY"] + [f"T{n}" for n in range(11)])
    assert factor_neutralization_check.compute_book_factor_exposure(index, [0.0] * 120, pd.DataFrame())["status"] == "SKIPPED"
    assert "not in dataset" in factor_neutralization_check.compute_book_factor_exposure(index, [0.0] * 120, pivot.drop(columns="SPY"))["reason"]
    assert "aligned dates" in factor_neutralization_check.compute_book_factor_exposure(index[:10], [0.001] * 10, pivot)["reason"]
    returns = list(rng.normal(0.0005, 0.005, 119)) + [0.0]
    result = factor_neutralization_check.compute_book_factor_exposure(index, returns, pivot)
    assert result["status"] == "OK" and result["market_ticker"] == "SPY"
    assert factor_neutralization_check.market_forward_returns(pivot.drop(columns="SPY")).empty
    assert factor_neutralization_check.momentum_factor_forward_returns(pivot.iloc[:, :1]).empty


def test_a_momentum_factor_joins_the_regression():
    rng = np.random.default_rng(5)
    index = pd.bdate_range("2024-01-01", periods=60)
    market = pd.Series(rng.normal(0, 0.01, 60), index=index)
    book = market * 0.4 + pd.Series(rng.normal(0, 0.002, 60), index=index)
    result = factor_neutralization_check.compute_factor_exposure(book, market, momentum_factor=pd.Series(rng.normal(0, 0.01, 60), index=index))
    assert "momentum" in result["loadings"]


def test_a_ledger_that_never_started_is_flagged_first():
    actions = research_cycle.due_actions({}, {}, session=None, sessions_behind=0, sessions_since_retrain=None, broker_keys=False, record_started=False, policy_enabled=False)
    assert any("record not started" in action["why"] for action in actions)


def test_host_memory_is_read_from_windows_through_the_kernel_call(monkeypatch):
    import types

    # a stand-in for ctypes.windll, so the Windows branch runs on any machine
    monkeypatch.setattr(research_cycle.sys, "platform", "win32")
    monkeypatch.setattr(research_cycle.ctypes, "windll", types.SimpleNamespace(kernel32=types.SimpleNamespace(GlobalMemoryStatusEx=lambda reference: 1)), raising=False)
    assert research_cycle.total_memory_bytes() == 0  # the stand-in fills nothing in, so the struct reads zero
    monkeypatch.setattr(research_cycle.ctypes, "windll", types.SimpleNamespace(kernel32=types.SimpleNamespace(GlobalMemoryStatusEx=lambda reference: 0)), raising=False)
    assert research_cycle.total_memory_bytes() is None
