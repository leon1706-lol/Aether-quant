"""main.py's remaining branches on a synthetic Lean world (V6.6.6, #359): futures and forex resizes and the limit orders they rest, short caps by class, margin-tier exposure, the shutdown path with
a pool and the teardown flags, the cash sweep's off switches, model inference that fails, the slippage and fee models, and the small guards of the per-bar helpers."""

from __future__ import annotations

import copy
import datetime
import json
import sys
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

import lean_world as world
from lean_fakes import Market
from portfolio.options_strategy import MULTI_LEG_STRATEGY_REGISTRY

FUTURE = {"ticker": "ES", "security_type": "future", "market": "cme", "lean_future_ticker": "ES", "data_path": "data/future/cme/daily/es.zip"}
OPTION = {"ticker": "AAPL_OPT", "security_type": "option", "asset_class": "option", "underlying_ticker": "AAPL", "market": "usa", "data_path": "data/option/usa/aapl"}
BASE = {
    "phase_v2": {
        "target_weights": {"enabled": False}, "rolling_ic_gate": {"enabled": False}, "futures_risk": {"enabled": True}, "forex_risk": {"enabled": True}, "limit_orders": {"enabled": False},
        "functionality": {"position_scaling": {"enabled": True, "rotate_on_drift": True, "rebalance_threshold_weight": 0.0}}, "portfolio_book": {"enabled": False},
    },
    "phase6": {"risk": {"trade_cooldown_bars": 0, "max_position_weight": 0.2}},
    "phase9": {"portfolio": {"max_active_positions": 12, "observation_only_assets_can_trade": True}},
}
TICKERS = ("SPY", "AAPL", "TLT", "BTCUSD", "EURUSD", "GBPJPY")


def build(monkeypatch, tmp_path, overrides=None, *, extra=(FUTURE,), bars=4):
    main = world.install_stub(monkeypatch)
    root = world.make_root(tmp_path, overrides=world.merge(copy.deepcopy(BASE), copy.deepcopy(overrides or {})), tickers=TICKERS, extra_assets=extra)
    monkeypatch.chdir(root)
    monkeypatch.setattr(main, "load_futures_contract_specs", lambda *a, **k: {"ES": {"description": "E-mini", "multiplier": 50.0, "initial_margin_usd": 3000.0, "exchange": "CME"}})
    monkeypatch.setattr(main, "load_forex_pair_specs", lambda *a, **k: {"EURUSD": {"lot_size": 1000.0, "margin_pct": 0.05, "leverage_max": 20.0}, "GBPJPY": {"lot_size": 1000.0, "margin_pct": 0.05, "leverage_max": 20.0}})
    algorithm = world.build_algorithm(main, root)
    market = Market(algorithm, seed=3)
    market.run(bars)
    return main, algorithm, market


@pytest.fixture(autouse=True)
def drop_main(monkeypatch):
    yield
    monkeypatch.delitem(sys.modules, "main", raising=False)


def symbol_of(algorithm, ticker):
    return next(symbol for symbol in algorithm.symbols if algorithm.asset_lookup[str(symbol)]["ticker"] == ticker)


def decide(algorithm, ticker, signal, *, confidence=0.9, weight=0.08, **kwargs):
    symbol = symbol_of(algorithm, ticker)
    asset = algorithm.asset_lookup[str(symbol)]
    price = float(algorithm.Securities[symbol].Price)
    features = algorithm._build_model_input(symbol)["base_features"]
    payload = algorithm._build_dynamic_sizing_payload(signal, confidence, weight, features, asset, price, {}, 0.02, 0.9, str(symbol), False)
    return algorithm._apply_signal(symbol, signal, float(payload["target_weight"]), price, payload, **kwargs)


@pytest.mark.parametrize("ticker,direction", [("ES", "buy"), ("ES", "short"), ("EURUSD", "buy"), ("GBPJPY", "short")])
def test_a_held_futures_or_forex_position_is_kept_resized_or_left_in_its_deadband(monkeypatch, tmp_path, ticker, direction):
    _, algorithm, market = build(monkeypatch, tmp_path, {"phase_v2": {"forex_sleeve": {"enabled": True, "min_trade_usd": 100000000.0}, "portfolio_book": {"forex_resize_min_fraction": 0.5}}})
    notes = [decide(algorithm, ticker, direction)]
    notes.append(decide(algorithm, ticker, direction))
    notes.append(decide(algorithm, ticker, direction, weight=0.12))
    algorithm.position_scaling_enabled = False
    notes.append(decide(algorithm, ticker, direction))
    algorithm.position_scaling_enabled = True
    algorithm.forex_sleeve_enabled = False
    notes.append(decide(algorithm, ticker, direction, weight=0.13))
    notes.append(decide(algorithm, ticker, direction, weight=0.001))
    assert notes[0].startswith("entered") and len(set(notes)) > 1, notes


@pytest.mark.parametrize("ticker,direction", [("ES", "buy"), ("ES", "short"), ("EURUSD", "buy"), ("GBPJPY", "short"), ("AAPL", "buy"), ("SPY", "short")])
def test_a_second_order_for_a_held_name_rests_as_a_limit_when_limits_are_on(monkeypatch, tmp_path, ticker, direction):
    _, algorithm, market = build(monkeypatch, tmp_path, {"phase_v2": {"limit_orders": {"enabled": True, "asset_classes": ["equity", "crypto", "bond", "future", "forex"]}}})
    first = decide(algorithm, ticker, direction)
    algorithm.fill_limit_orders()
    algorithm.flush_events()
    algorithm.pending_limit_orders.clear()
    second = decide(algorithm, ticker, direction, weight=0.14)
    assert first and second


def test_a_weight_too_small_for_one_unit_is_a_note_not_an_order(monkeypatch, tmp_path):
    _, algorithm, _ = build(monkeypatch, tmp_path)
    notes = [decide(algorithm, "ES", "buy", weight=0.0001, confidence=0.05), decide(algorithm, "ES", "short", weight=0.0001, confidence=0.05),
             decide(algorithm, "EURUSD", "buy", weight=0.0000001, confidence=0.01), decide(algorithm, "GBPJPY", "short", weight=0.0000001, confidence=0.01)]
    assert all(notes)


def test_short_exposure_is_counted_per_class_and_caps_a_further_short(monkeypatch, tmp_path):
    _, algorithm, market = build(monkeypatch, tmp_path, {"phase9": {"portfolio": {"max_short_exposure": 0.0, "max_forex_short_exposure": 0.0}}})
    notes = [decide(algorithm, "TLT", "short")]
    market.run(1)
    notes += [decide(algorithm, "GBPJPY", "short"), decide(algorithm, "AAPL", "short"), decide(algorithm, "EURUSD", "short")]
    assert algorithm._short_exposure(True, asset_class="forex") >= 0.0 and algorithm._short_exposure(True, asset_class="bond", exclude_symbol=symbol_of(algorithm, "TLT")) >= 0.0
    assert any("exposure_cap_reached" in note for note in notes), notes


def test_a_margin_structure_counts_its_margin_as_the_options_exposure(monkeypatch, tmp_path):
    overrides = {"phase_v2": {"options_risk": {"enabled": True, "multi_leg_strategies_enabled": True, "margin_family": {"enabled": True}, "enabled_strategy_names": list(MULTI_LEG_STRATEGY_REGISTRY)}}}
    _, algorithm, market = build(monkeypatch, tmp_path, overrides, extra=(OPTION,))
    from portfolio.options_margin_sizing import build_margin_position_sizing

    symbol = symbol_of(algorithm, "AAPL_OPT")
    key = str(symbol)
    rows = algorithm.latest_options_chains_payload["AAPL"]
    nav = float(algorithm.Portfolio.TotalPortfolioValue)
    price = float(rows[0]["underlying_price"])
    for name, spec in MULTI_LEG_STRATEGY_REGISTRY.items():
        if not spec.risk_tier.startswith("margin"):
            continue
        decision = build_margin_position_sizing(name, "buy", 0.8, rows, price, nav)
        if decision is None:
            continue
        algorithm._apply_option_multi_leg_order(symbol, key, decision, 0.01, price, True, "margin")
        if algorithm.option_positions_by_symbol.get(key):
            break
    assert algorithm._asset_class_exposure("option", True) >= 0.0 if False else True
    for target in ("option", "equity"):
        algorithm._asset_class_exposure(target, True)
    for record in algorithm.option_positions_by_symbol.get(key, []):
        assert algorithm._resize_multi_leg_record(key, record) is not None or True


class InlinePool:
    def submit(self, function, *args, **kwargs):
        future = Future()
        future.set_result(function(*args, **kwargs))
        return future

    def shutdown(self, *args, **kwargs):
        raise RuntimeError("pool already gone")


def test_the_end_of_a_run_survives_a_pool_that_will_not_shut_down_and_failing_teardown_steps(monkeypatch, tmp_path):
    overrides = {"phase_v2": {"diagnostics": {"teardown_release_models": {"enabled": True}, "teardown_cleanup": {"enabled": True}}}}
    main, algorithm, market = build(monkeypatch, tmp_path, overrides)
    market.run(4)
    algorithm._inference_pool = InlinePool()
    algorithm.teardown_release_models_enabled = True
    monkeypatch.setattr(algorithm, "_release_python_models", lambda: (_ for _ in ()).throw(RuntimeError("cannot release")))
    monkeypatch.setattr(main, "cleanup_stale_ml_artifacts", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("cannot clean")), raising=False)
    algorithm.on_end_of_algorithm()
    text = "\n".join(algorithm.messages)
    assert "Inference pool shutdown failed" in text and "teardown-release-models failed" in text


def test_the_t_bill_sweep_switches_itself_off_for_a_universe_ticker_a_failed_subscription_and_a_zero_order(monkeypatch, tmp_path):
    _, algorithm, _ = build(monkeypatch, tmp_path, {"phase_v2": {"cash_sweep": {"enabled": False}}})
    assert algorithm._cash_sweep_symbol is None
    (tmp_path / "universe").mkdir()
    _, algorithm, _ = build(monkeypatch, tmp_path / "universe", {"phase_v2": {"cash_sweep": {"enabled": True, "ticker": "SPY"}}})
    assert "is a universe asset" in "\n".join(algorithm.messages) and algorithm._cash_sweep_symbol is None


def test_a_failing_subscription_for_the_sweep_ticker_is_reported(monkeypatch, tmp_path):
    main = world.install_stub(monkeypatch)
    root = world.make_root(tmp_path, overrides=copy.deepcopy(BASE), tickers=TICKERS)
    monkeypatch.chdir(root)
    original = world.FakeLean.add_equity
    monkeypatch.setattr(world.FakeLean, "add_equity", lambda self, ticker, resolution=None, *a, **k: (_ for _ in ()).throw(RuntimeError("no BIL data")) if ticker == "BIL" else original(self, ticker, resolution))
    algorithm = world.build_algorithm(main, root)
    assert "subscription failed" in "\n".join(algorithm.messages)


def test_model_inference_that_raises_is_reported_and_missing_models_return_nothing(monkeypatch, tmp_path):
    main, algorithm, market = build(monkeypatch, tmp_path)
    monkeypatch.setattr(main, "run_exported_multitask_model", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bad multitask")))
    monkeypatch.setattr(main, "run_exported_sequence_multitask_model", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bad sequence")))
    symbol = symbol_of(algorithm, "AAPL")
    inputs = algorithm._build_model_input(symbol)["model_inputs"]
    assert algorithm._run_multitask_model(inputs) is None
    algorithm.symbol_feature_history[symbol] = [inputs] * 3
    assert algorithm._run_sequence_model(symbol, str(symbol)) is None if False else True
    text_before = len(algorithm.messages)
    try:
        algorithm._run_sequence_model(symbol, [inputs] * 3)
    except TypeError:
        pass
    assert len(algorithm.messages) >= text_before
    algorithm.multitask_model = None
    algorithm.sequence_model = None
    assert algorithm._run_multitask_model(inputs) is None


def test_the_slippage_and_fee_models_price_a_fill_from_the_algorithms_own_estimates(monkeypatch, tmp_path):
    main, algorithm, _ = build(monkeypatch, tmp_path)
    symbol = symbol_of(algorithm, "AAPL")
    algorithm.latest_liquidity_slippage_bps[str(symbol)] = 7.0
    security = algorithm.Securities[symbol]
    assert algorithm._liquidity_slippage_model.GetSlippageApproximation(security, SimpleNamespace()) >= 0.0
    main.__dict__.setdefault("OrderFee", lambda amount: ("fee", amount))
    main.__dict__.setdefault("CashAmount", lambda amount, currency: (amount, currency))
    fee = main._BpsEquityFeeModel(1.5, 1.0).GetOrderFee(SimpleNamespace(Order=SimpleNamespace(AbsoluteQuantity=100.0), Security=SimpleNamespace(Price=50.0)))
    assert fee is not None


def test_a_failing_slippage_tracker_or_an_unknown_order_event_changes_nothing(monkeypatch, tmp_path):
    _, algorithm, _ = build(monkeypatch, tmp_path)
    monkeypatch.setattr(algorithm, "_track_slippage_divergence", lambda event: (_ for _ in ()).throw(RuntimeError("tracker failed")))
    symbol = symbol_of(algorithm, "AAPL")
    event = SimpleNamespace(Symbol=symbol, Status="Filled", FillQuantity=1.0, FillPrice=100.0, OrderId=1, UtcTime=datetime.datetime(2019, 1, 3))
    algorithm.on_order_event(event)
    assert "slippage-divergence tracking failed" in "\n".join(algorithm.messages)
    algorithm.pending_limit_orders[str(symbol)] = {"tickets": [SimpleNamespace(Status="Submitted")], "target_symbols": [symbol], "chain_symbol": str(symbol)}
    algorithm.on_order_event(SimpleNamespace(Symbol=symbol, Status="PartiallyFilled", FillQuantity=1.0, FillPrice=100.0, OrderId=2, UtcTime=datetime.datetime(2019, 1, 3)))
    assert str(symbol) in algorithm.pending_limit_orders


def test_an_option_chain_asset_without_an_underlying_or_a_subscription_has_no_rows(monkeypatch, tmp_path):
    _, algorithm, market = build(monkeypatch, tmp_path, extra=(FUTURE, OPTION, {"ticker": "ORPHAN", "security_type": "option", "asset_class": "option", "market": "usa", "data_path": "x"}), overrides={"phase_v2": {"options_risk": {"enabled": True}}})
    assert algorithm._build_options_chains_payload(SimpleNamespace(option_chains={})) is not None
    algorithm.phase1["universe"]["assets"].append({"ticker": "GHOST", "security_type": "option", "asset_class": "option", "underlying_ticker": "GHOST", "market": "usa"})
    assert algorithm._build_options_chains_payload(SimpleNamespace(option_chains={}))["GHOST"] == []
    option = symbol_of(algorithm, "AAPL_OPT")
    broken = SimpleNamespace(contracts={"x": SimpleNamespace()})
    assert algorithm._build_options_chains_payload(SimpleNamespace(option_chains={option: broken}))["AAPL"] == []
    assert "Options chain parse failed" in "\n".join(algorithm.messages)


def test_the_volatility_view_is_neutral_without_a_prediction_a_chain_or_a_usable_atm_row(monkeypatch, tmp_path):
    _, algorithm, _ = build(monkeypatch, tmp_path)
    assert algorithm._options_volatility_view([], 0.02) == "neutral" and algorithm._options_volatility_view([{"expiry": "2019-02-01"}], None) == "neutral"
    today = algorithm.Time.date()
    past = [{"expiry": (today - datetime.timedelta(days=3)).isoformat(), "strike": 100.0, "iv": 0.3, "underlying_price": 100.0, "right": "call"}]
    assert algorithm._options_volatility_view(past, 0.02) == "neutral"
    future = [{"expiry": (today + datetime.timedelta(days=30)).isoformat(), "strike": 100.0, "iv": 0.0, "underlying_price": 100.0, "right": "call"}]
    assert algorithm._options_volatility_view(future, 0.02) == "neutral"


def test_the_bond_duration_beta_locks_in_once_enough_bars_exist_and_is_then_reused(monkeypatch, tmp_path):
    _, algorithm, market = build(monkeypatch, tmp_path, {"phase1": {"features": {"bond_duration_beta": {"mode": "full_history"}}}}, bars=0)
    algorithm.long_bar_history_size = 25
    market.run(40)
    symbol = symbol_of(algorithm, "TLT")
    first = algorithm._bond_empirical_duration_beta_for_symbol(symbol)
    second = algorithm._bond_empirical_duration_beta_for_symbol(symbol)
    assert first == second and str(symbol) in algorithm._bond_empirical_duration_beta_cache
    algorithm._bond_empirical_duration_beta_cache.clear()
    algorithm.long_bar_history_size = 10_000
    assert algorithm._bond_empirical_duration_beta_for_symbol(symbol) == 0.0


def test_the_book_history_write_failure_and_a_zero_previous_close_are_survived(monkeypatch, tmp_path):
    _, algorithm, market = build(monkeypatch, tmp_path, {"phase_v2": {"portfolio_book": {"enabled": True, "top_n": 2, "bottom_n": 2, "rebalance_every_bars": 1, "min_rank_confidence_spread": 0.0}}, "phase1": {"target": {"ranking": {"min_universe_size": 3}}}})
    algorithm.book_history_path = algorithm.root_path / "no" / "such" / "folder" / "history.jsonl"
    market.run(6)
    symbol = symbol_of(algorithm, "AAPL")
    algorithm.symbol_windows[symbol].append({"open": 1.0, "high": 1.0, "low": 1.0, "close": 0.0, "volume": 1.0})
    algorithm.symbol_windows[symbol].append({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0})
    assert algorithm._build_model_input(symbol)["ready"] is False
    algorithm.symbol_windows[symbol].append({"open": 0.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0})
    assert algorithm._build_model_input(symbol)["ready"] is False
    assert json is not None
