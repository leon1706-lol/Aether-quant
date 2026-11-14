"""evaluation/alpha_proof.py's remaining branches (V6.6.6, #359): the strategy series of a synthetic Lean run, windows with and without deflation,
degenerate Sharpe inputs and the whole report with its verdict."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from evaluation import alpha_proof as ap

SESSIONS = pd.bdate_range("2023-06-01", "2026-06-30")


def _stamp(day) -> float:
    return datetime.fromisoformat(str(day)[:10]).replace(tzinfo=timezone.utc).timestamp()


def _zip(path: Path, prices, scale=1, dates=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(f"{day:%Y%m%d} 00:00,{int(p * scale)},{int(p * scale)},{int(p * scale)},{int(p * scale)},1000" for day, p in zip(dates if dates is not None else SESSIONS, prices))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{path.stem}.csv", rows)
    path.write_bytes(buffer.getvalue())


@pytest.fixture
def world(tmp_path):
    rng = np.random.default_rng(3)
    prices = {name: 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(SESSIONS)))) for name in ("SPY", "AGG", "BTCUSD")}
    _zip(tmp_path / "data" / "equity" / "usa" / "daily" / "spy.zip", prices["SPY"], 10000)
    _zip(tmp_path / "data" / "equity" / "usa" / "daily" / "agg.zip", prices["AGG"], 10000)
    _zip(tmp_path / "data" / "crypto" / "coinbase" / "daily" / "btcusd_trade.zip", prices["BTCUSD"])
    config = {"runtime": {"trading_days_per_year": 365}, "phase1": {"universe": {"assets": [
        {"ticker": "SPY", "security_type": "equity", "data_path": "data/equity/usa/daily/spy.zip"},
        {"ticker": "AGG", "security_type": "equity", "data_path": "data/equity/usa/daily/agg.zip"},
        {"ticker": "BTCUSD", "security_type": "crypto", "data_path": "data/crypto/coinbase/daily/btcusd_trade.zip"}]}}}
    nav = 100000.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.006, len(SESSIONS))))
    points = [[_stamp(day), float(value)] for day, value in zip(SESSIONS, nav)]
    result = {"charts": {"Strategy Equity": {"series": {"Equity": {"values": points}}}}}
    run_dir = tmp_path / "backtests" / "2026-12-31_00-00-00"
    run_dir.mkdir(parents=True)
    (run_dir / "1.json").write_text(json.dumps(result), encoding="utf-8")
    return run_dir, config, tmp_path, {"result": result, "order_events": []}


def test_the_strategy_series_is_the_nav_change_and_a_short_run_has_none(world):
    _, config, root, run = world
    y = ap.strategy_daily_returns(run, config, root)
    assert len(y) == len(SESSIONS) - 1 and y.index[0] > "2023-06-01"
    short = {"result": {"charts": {"Strategy Equity": {"series": {"Equity": {"values": run["result"]["charts"]["Strategy Equity"]["series"]["Equity"]["values"][:2]}}}}}, "order_events": []}
    assert ap.strategy_daily_returns(short, config, root).empty


def test_benchmarks_outside_the_universe_are_skipped_or_refused(world):
    _, config, root, _ = world
    assert ap.benchmark_daily_returns(root, config, ("GHOST",), start="2024-01-01", end="2024-02-01").empty
    with pytest.raises(ValueError, match="not in this run's universe"):
        ap.benchmark_daily_returns(root, config, ("GHOST",), start="2024-01-01", end="2024-02-01", required=True)
    lagged = ap.benchmark_daily_returns(root, config, start="2024-01-01", end="2024-02-01", lag_equity=True)
    assert set(lagged.columns) == {"SPY", "AGG", "BTCUSD"}


def test_degenerate_series_have_no_sharpe_no_interval_and_no_sessions():
    assert ap.to_sessions(pd.Series(dtype=float), ["2024-01-02"]).empty
    assert ap.sharpe(np.array([0.01, 0.01, 0.01]), 252.0) is None and ap.sharpe(np.array([0.01]), 252.0) is None
    flat = pd.Series([0.5] * 30, index=[f"2024-02-{day:02d}" for day in range(1, 31)])
    assert ap.sharpe_bootstrap_ci(flat, annualization=252.0, draws=20) == (None, None)


def test_a_period_report_deflates_with_given_inputs_or_the_trial_list():
    rng = np.random.default_rng(1)
    y = pd.Series(rng.normal(0.001, 0.01, 60), index=[day.strftime("%Y-%m-%d") for day in pd.bdate_range("2024-01-01", periods=60)])
    given = ap.period_report(y, pd.DataFrame(), annualization=252.0, trial_sharpes=[], deflation={"N": 20, "var": 0.4})
    legacy = ap.period_report(y, pd.DataFrame(), annualization=252.0, trial_sharpes=[0.2, 0.5, 0.9])
    tiny = ap.period_report(y.iloc[:2], pd.DataFrame(), annualization=252.0, trial_sharpes=[])
    assert given["dsr_trials"] == 20 and legacy["dsr"] is not None and tiny["dsr"] is None and tiny["alpha"] is None


def test_the_deflated_sharpe_needs_a_variance_and_more_than_one_trial():
    returns = np.array([0.01, -0.005, 0.02, 0.0, 0.01])
    assert ap.deflated_sharpe_from_inputs(returns, num_trials=10, trial_variance=None, annualization=252.0)["value"] is None
    assert ap.deflated_sharpe_from_inputs(returns, num_trials=1, trial_variance=0.3, annualization=252.0)["value"] is None
    assert ap.deflated_sharpe_from_inputs(returns, num_trials=10, trial_variance=0.3, annualization=252.0)["expected_max_sharpe_annual"] is not None


def test_a_window_report_is_empty_outside_the_series_and_deflates_when_asked():
    rng = np.random.default_rng(2)
    days = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2024-01-01", periods=80)]
    y = pd.Series(rng.normal(0.001, 0.01, 80), index=days)
    benchmarks = pd.DataFrame({"SPY": rng.normal(0.0005, 0.01, 80)}, index=days)
    assert ap.window_report(y, benchmarks, start="2030-01-01", end="2030-02-01", annualization=252.0) == {"start": "2030-01-01", "end": "2030-02-01", "n": 0}
    report = ap.window_report(y, benchmarks, start=days[0], end=days[-1], annualization=252.0, deflation={"N": 30, "var": 0.4, "legacy_var": 0.2})
    assert "dsr" in report and "dsr_legacy_variance" in report and report["alpha"] is not None


def test_annualization_is_measured_from_the_rows_of_the_series():
    short = [f"2024-01-{day:02d}" for day in range(1, 11)]
    assert ap.measured_annualization(short, fallback=365.0) == 365.0
    weekdays = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2024-01-01", periods=30)]
    assert ap.measured_annualization(weekdays, fallback=365.0) == 252.0
    assert ap.measured_annualization([day.strftime("%Y-%m-%d") for day in pd.date_range("2024-01-01", periods=30)], fallback=365.0) == 365.0


def test_the_whole_report_covers_every_period_and_gives_a_verdict(world):
    run_dir, config, root, _ = world
    report = ap.alpha_proof_report(run_dir, config, root, trial_sharpes=[0.3, 0.6, 0.9], deflation={"N": 50, "var": 0.3})
    assert set(report["periods"]) >= {"full", "backtest", "holdout", "fresh"} and report["r_alpha1"]["rule"] == "R-ALPHA1" and report["config"] == "config.json"
    assert report["periods"]["fresh"]["judgeable"] in (True, False) and "alpha_session_aligned" in report["periods"]["full"]
    frozen = root / "ml" / "evaluation" / "run_configs"
    frozen.mkdir(parents=True)
    (frozen / f"{run_dir.name}.json").write_text(json.dumps(config), encoding="utf-8")
    again = ap.alpha_proof_report(run_dir, {}, root, trial_sharpes=[])
    assert again["config"].endswith(f"{run_dir.name}.json")


def test_a_run_without_an_equity_curve_has_nothing_to_prove(tmp_path):
    run_dir = tmp_path / "backtests" / "2026-01-01_00-00-00"
    run_dir.mkdir(parents=True)
    (run_dir / "1.json").write_text(json.dumps({"charts": {}}), encoding="utf-8")
    config = {"phase1": {"universe": {"assets": []}}}
    assert ap.alpha_proof_report(run_dir, config, tmp_path, trial_sharpes=[]) == {"run": run_dir.name, "status": "no equity curve"}
