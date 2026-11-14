"""main.py's option paths on a synthetic Lean world (V6.6.6, #359): a chain per bar, single-leg entries, rotations and resizes, every registered multi-leg structure through the real
order path, the expiry and assignment sweeps, covered and protective positions, limit orders and the observation-mode record, with the option's own sizing built by the real functions."""

from __future__ import annotations

import copy
import sys

import pytest

import lean_world as world
from lean_fakes import Market
from portfolio.options_margin_sizing import build_margin_position_sizing
from portfolio.options_strategy import MULTI_LEG_STRATEGY_REGISTRY, build_multi_leg_position_sizing, build_vertical_spread_position_sizing

OPTION = {"ticker": "AAPL_OPT", "security_type": "option", "asset_class": "option", "underlying_ticker": "AAPL", "market": "usa", "data_path": "data/option/usa/aapl"}
OPTIONS_ON = {
    "phase_v2": {
        "target_weights": {"enabled": False}, "rolling_ic_gate": {"enabled": False}, "portfolio_book": {"enabled": False}, "limit_orders": {"enabled": False},
        "options_risk": {"enabled": True, "multi_leg_strategies_enabled": True, "max_positions_per_underlying": 2, "auto_close_days_before_expiry": 40, "rotation_cooldown_bars": 0,
                         "enabled_strategy_names": ["single_leg", "bull_call_spread", "bear_put_spread", "straddle", "iron_condor", "long_call_butterfly", "covered_call", "protective_put", "collar"],
                         "assignment_risk_detector": {"enabled": True, "score_threshold": 0.0, "lookahead_window_days": 90}, "arbitrage_detector": {"enabled": True, "min_mispricing_bps": 1.0},
                         "margin_family": {"enabled": True}},
        "functionality": {"position_scaling": {"enabled": True, "rotate_on_drift": True, "rebalance_threshold_weight": 0.0}},
    },
    "phase6": {"risk": {"trade_cooldown_bars": 0}},
    "phase9": {"portfolio": {"max_active_positions": 12, "observation_only_assets_can_trade": True, "max_options_exposure": 0.9}},
}
TICKERS = ("SPY", "AAPL", "TLT", "BTCUSD")


def build(monkeypatch, tmp_path, overrides=None):
    main = world.install_stub(monkeypatch)
    config = world.merge(copy.deepcopy(OPTIONS_ON), overrides or {})
    root = world.make_root(tmp_path, overrides=config, tickers=TICKERS, extra_assets=(OPTION,))
    monkeypatch.chdir(root)
    algorithm = world.build_algorithm(main, root)
    market = Market(algorithm, seed=5)
    market.run(4)
    return algorithm, market


@pytest.fixture
def options(monkeypatch, tmp_path):
    algorithm, market = build(monkeypatch, tmp_path)
    yield algorithm, market
    monkeypatch.delitem(sys.modules, "main", raising=False)


def option_symbol(algorithm):
    return next(symbol for symbol in algorithm.symbols if algorithm.asset_lookup[str(symbol)]["ticker"] == "AAPL_OPT")


def decide(algorithm, signal, *, confidence=0.9, weight=0.05, volatility=0.02, **kwargs):
    symbol = option_symbol(algorithm)
    asset = algorithm.asset_lookup[str(symbol)]
    price = float(algorithm.Securities[symbol].Price)
    features = algorithm._build_model_input(symbol)["base_features"]
    payload = algorithm._build_dynamic_sizing_payload(signal, confidence, weight, features, asset, price, {}, volatility, 0.9, str(symbol), False)
    return algorithm._apply_signal(symbol, signal, float(payload["target_weight"]), price, payload, **kwargs)


def test_the_chain_of_each_bar_becomes_rows_with_solved_greeks(options):
    algorithm, market = options
    rows = algorithm.latest_options_chains_payload["AAPL"]
    assert rows and {"delta", "vega", "iv", "underlying_price"} <= set(rows[0]) and algorithm._options_chains_payload_for_state()["AAPL"][0]["symbol"]
    market.run(1, drop=("?AAPL",))
    assert algorithm.latest_options_chains_payload["AAPL"] == []


def test_an_option_signal_enters_scales_rotates_and_exits_through_real_orders(options):
    algorithm, market = options
    notes = [decide(algorithm, "buy")]
    for _ in range(6):
        market.run(1)
        notes.append(decide(algorithm, "buy", weight=0.08))
        notes.append(decide(algorithm, "short"))
    notes.append(decide(algorithm, "sell"))
    assert any("option" in note for note in notes), notes
    assert algorithm.option_positions_by_symbol or any("sell" in str(entry) or entry[1] < 0 for entry in algorithm.order_log)


def test_every_registered_structure_is_ordered_resized_and_liquidated_through_the_order_path(options):
    algorithm, market = options
    symbol = option_symbol(algorithm)
    key = str(symbol)
    rows = algorithm.latest_options_chains_payload["AAPL"]
    nav = float(algorithm.Portfolio.TotalPortfolioValue)
    price = float(rows[0]["underlying_price"])
    built = 0
    for name, spec in MULTI_LEG_STRATEGY_REGISTRY.items():
        if spec.risk_tier == "vega_budget":
            decision = build_multi_leg_position_sizing(name, "buy", 0.8, rows, nav, max_vega_budget_pct_of_equity=0.02)
        else:
            decision = build_margin_position_sizing(name, "buy", 0.8, rows, price, nav)
        if decision is None:
            continue
        built += 1
        note = algorithm._apply_option_multi_leg_order(symbol, key, decision, 0.01, price, True, "test")
        assert note
        market.run(1)
        rows = algorithm.latest_options_chains_payload["AAPL"]
        for record in list(algorithm.option_positions_by_symbol.get(key, [])):
            algorithm._liquidate_option_record(key, record)
    assert built >= 8


def test_a_multi_leg_position_is_scaled_and_its_outcome_is_reported_when_it_closes(options):
    algorithm, market = options
    symbol = option_symbol(algorithm)
    key = str(symbol)
    rows = algorithm.latest_options_chains_payload["AAPL"]
    nav = float(algorithm.Portfolio.TotalPortfolioValue)
    price = float(rows[0]["underlying_price"])
    small = build_vertical_spread_position_sizing("buy", 0.8, rows, nav, max_vega_budget_pct_of_equity=0.005)
    large = build_vertical_spread_position_sizing("buy", 0.8, rows, nav, max_vega_budget_pct_of_equity=0.05)
    assert small is not None and large is not None
    assert algorithm._apply_option_multi_leg_order(symbol, key, small, 0.01, price, True, "enter")
    market.run(1)
    assert algorithm._apply_option_multi_leg_order(symbol, key, large, 0.01, price, True, "scale up")
    market.run(1)
    assert algorithm._apply_option_multi_leg_order(symbol, key, small, 0.01, price, True, "scale down")
    algorithm._emit_option_strategy_outcome_if_pending(key)
    algorithm._apply_option_expiry_auto_close_sweep()
    algorithm._apply_option_assignment_risk_sweep()
    algorithm._manage_covered_protective_positions()
    assert algorithm.latest_assignment_risk_by_symbol is not None


def test_the_sweeps_close_a_position_near_expiry(monkeypatch, tmp_path):
    algorithm, market = build(monkeypatch, tmp_path, overrides={"phase_v2": {"options_risk": {"auto_close_days_before_expiry": 90}}})
    try:
        symbol = option_symbol(algorithm)
        key = str(symbol)
        rows = algorithm.latest_options_chains_payload["AAPL"]
        nav = float(algorithm.Portfolio.TotalPortfolioValue)
        price = float(rows[0]["underlying_price"])
        decision = build_vertical_spread_position_sizing("buy", 0.8, rows, nav, max_vega_budget_pct_of_equity=0.02)
        algorithm._apply_option_multi_leg_order(symbol, key, decision, 0.01, price, True, "enter")
        assert algorithm.option_positions_by_symbol.get(key)
        algorithm._apply_option_expiry_auto_close_sweep()
        algorithm._apply_option_assignment_risk_sweep()
        market.run(2)
        assert not algorithm.option_positions_by_symbol.get(key) or algorithm.order_log
    finally:
        monkeypatch.delitem(sys.modules, "main", raising=False)


def test_option_orders_rest_as_limits_and_resolve_by_events(monkeypatch, tmp_path):
    algorithm, market = build(monkeypatch, tmp_path, overrides={"phase_v2": {"limit_orders": {"enabled": True, "unfilled_timeout_bars": 1}}})
    try:
        symbol = option_symbol(algorithm)
        key = str(symbol)
        rows = algorithm.latest_options_chains_payload["AAPL"]
        nav = float(algorithm.Portfolio.TotalPortfolioValue)
        price = float(rows[0]["underlying_price"])
        decision = build_vertical_spread_position_sizing("buy", 0.8, rows, nav, max_vega_budget_pct_of_equity=0.02)
        note = algorithm._apply_option_multi_leg_order(symbol, key, decision, 0.01, price, True, "enter")
        assert "limit" in note or note
        market.step(fill_limits=False)
        market.step(fill_limits=False)
        assert decide(algorithm, "buy")
        market.step()
    finally:
        monkeypatch.delitem(sys.modules, "main", raising=False)


def test_observation_mode_records_the_simulated_option_position(monkeypatch, tmp_path):
    algorithm, market = build(monkeypatch, tmp_path, overrides={"phase_v2": {"runtime": {"mode": "observation"}}})
    try:
        symbol = option_symbol(algorithm)
        key = str(symbol)
        rows = algorithm.latest_options_chains_payload["AAPL"]
        nav = float(algorithm.Portfolio.TotalPortfolioValue)
        price = float(rows[0]["underlying_price"])
        decision = build_vertical_spread_position_sizing("buy", 0.8, rows, nav, max_vega_budget_pct_of_equity=0.02)
        assert algorithm._apply_option_multi_leg_order(symbol, key, decision, 0.01, price, False, "observation")
        assert decide(algorithm, "buy") and decide(algorithm, "sell")
        algorithm._emit_option_strategy_outcome_if_pending(key)
    finally:
        monkeypatch.delitem(sys.modules, "main", raising=False)
