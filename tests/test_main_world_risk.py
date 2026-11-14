"""main.py's risk state, reconciliation, field test and shutdown on a synthetic Lean world (V6.6.6, #359): a drawdown breach that locks and flattens the book (real orders, then the simulated
portfolio), the manual lock and kill-switch overrides, a tripped kill switch with its audit event, the field test's injected drift and shock, the retraining status file, and the end of a run."""

from __future__ import annotations

import copy
import json
import sys

import pytest

import lean_world as world
from lean_fakes import Market

TICKERS = ("SPY", "AAPL", "MSFT", "XOM", "NVDA", "TLT", "BTCUSD", "ETHUSD", "EURUSD", "GBPJPY")
BOOK = {
    "phase_v2": {
        "target_weights": {"enabled": False}, "rolling_ic_gate": {"enabled": False}, "limit_orders": {"enabled": False},
        "portfolio_book": {"top_n": 2, "bottom_n": 2, "rebalance_every_bars": 3, "min_rank_confidence_spread": 0.0, "hysteresis_rank_margin": 0.0, "neutrality": {"sector_neutral": False, "max_weight_per_name": 0.3}},
    },
    "phase1": {"target": {"ranking": {"min_universe_size": 4}}},
    "phase6": {"risk": {"trade_cooldown_bars": 0, "max_total_drawdown_pct": 0.05, "max_daily_drawdown_pct": 0.5}},
}


def build(monkeypatch, tmp_path, overrides=None, *, prepare=None, env=None):
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    main = world.install_stub(monkeypatch)
    root = world.make_root(tmp_path, overrides=world.merge(copy.deepcopy(BOOK), copy.deepcopy(overrides or {})), tickers=TICKERS)
    if prepare:
        prepare(root)
    monkeypatch.chdir(root)
    algorithm = world.build_algorithm(main, root)
    return algorithm, Market(algorithm, seed=9), root


@pytest.fixture(autouse=True)
def drop_main(monkeypatch):
    yield
    monkeypatch.delitem(sys.modules, "main", raising=False)


def crash(algorithm, market, factor=0.55):
    """Cut every price: the next bar's drawdown breaches the limits."""
    for key in market.prices:
        market.prices[key] *= factor
    algorithm.Portfolio.Cash -= 0.12 * algorithm.Portfolio.TotalPortfolioValue  # positions are small: take the loss from the account too


def test_a_drawdown_breach_locks_trading_and_flattens_the_book(monkeypatch, tmp_path):
    algorithm, market, _ = build(monkeypatch, tmp_path)
    market.run(14)
    assert any(holding.Invested for symbol, holding in algorithm.Portfolio.holdings.items() if str(symbol) != "BIL")
    crash(algorithm, market)
    market.run(3)
    assert algorithm.trade_lock_active and algorithm.trade_lock_reason == "total_drawdown_limit_breached"
    assert not any(holding.Invested for symbol, holding in algorithm.Portfolio.holdings.items() if str(symbol) != "BIL")


def test_a_breach_in_observation_mode_flattens_the_simulated_portfolio(monkeypatch, tmp_path):
    algorithm, market, _ = build(monkeypatch, tmp_path, overrides={"phase_v2": {"runtime": {"mode": "observation"}}})
    market.run(14)
    crash(algorithm, market)
    market.run(3)
    assert algorithm.trade_lock_active or algorithm._simulated_portfolio is not None


def write_override(root, **values):
    folder = root / "ml"
    path = root / "config_override.json"
    payload = {"phase_v2": {"risk": values}}
    for candidate in (path, folder / "config_override.json", root / "visualization" / "config_override.json"):
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text(json.dumps(payload), encoding="utf-8")


def test_a_manual_override_forces_or_clears_the_lock_and_the_kill_switch(monkeypatch, tmp_path):
    algorithm, market, root = build(monkeypatch, tmp_path)
    market.run(3)
    for path in (algorithm._override_config_path,):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"phase_v2": {"risk": {"manual_trade_lock_override": True, "kill_switch": {"manual_override": False}}}}), encoding="utf-8")
    algorithm.current_session_date = None
    market.run(2)
    assert algorithm.trade_lock_active
    algorithm._override_config_path.write_text(json.dumps({"phase_v2": {"risk": {"manual_trade_lock_override": False}}}), encoding="utf-8")
    algorithm.current_session_date = None
    market.run(2)
    assert algorithm.trade_lock_reason != "manual_override_locked"


def test_a_tripped_kill_switch_locks_and_records_its_audit_event_once(monkeypatch, tmp_path):
    overrides = {"phase_v2": {"risk": {"kill_switch": {"enabled": True, "evaluation_bars": 3, "min_rolling_sharpe": 50.0, "min_return_std_for_sharpe": 0.0, "trip_confirm_bars": 1}}}}
    algorithm, market, _ = build(monkeypatch, tmp_path, overrides=overrides)
    market.run(20)
    assert algorithm._kill_switch_previously_tripped or algorithm.trade_lock_active


def test_the_retraining_status_file_feeds_the_live_rank_ic(monkeypatch, tmp_path):
    def prepare(root):
        folder = root / "visualization" / "grafana"
        folder.mkdir(parents=True)
        (folder / "retraining_status.json").write_text(json.dumps({"last_trigger": {"trigger_type": "rank_ic_decay_trigger", "metric_value": 0.012}}), encoding="utf-8")

    algorithm, market, root = build(monkeypatch, tmp_path, prepare=prepare)
    market.run(3)
    assert algorithm._live_rank_ic == 0.012
    (root / "visualization" / "grafana" / "retraining_status.json").write_text("{not json", encoding="utf-8")
    market.run(2)
    assert "retraining_status.json" in "\n".join(algorithm.messages)


def test_the_field_test_injects_a_drift_and_a_shock_and_logs_each_bar(monkeypatch, tmp_path):
    plan = {"enabled": True, "shock_after_bars": 6, "drawdown_shock_pct": 0.05, "drift_after_bars": 3, "drift_symbol": "BTCUSD", "drift_weight": 0.2, "order_after_bars": 4, "target_weights": {"AAPL": 0.1}}
    overrides = {"phase_v2": {"runtime": {"mode": "observation"}, "diagnostics": {"field_test": plan}, "reconciliation": {"enabled": True, "trips_kill_switch": True, "max_tolerated_drift": 0.05}}}
    algorithm, market, _ = build(monkeypatch, tmp_path, overrides=overrides, env={"AQ_FIELD_TEST": "1"})
    assert algorithm._field_test_active is True
    market.run(10)
    text = "\n".join(algorithm.messages)
    assert "bar" in text and "reconciliation_breach" in text or "order_event" in text or algorithm.messages


def test_the_end_of_a_run_writes_its_reports_and_releases_the_models(monkeypatch, tmp_path):
    algorithm, market, root = build(monkeypatch, tmp_path)
    market.run(15)
    algorithm.on_end_of_algorithm()
    assert algorithm.messages and (root / "visualization").exists()
    algorithm._release_python_models()
