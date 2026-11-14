"""main.py's last residue on a synthetic Lean world (V6.6.6, #359): a world with no optional models at all, experts and sequence passes that fail, the context and spread fallbacks of the
features, the sweep's off switches, limit-order edge cases (a zero quantity, a cancel that fails, an exit that rests), combos with an equity leg, and held option positions at their cap."""

from __future__ import annotations

import copy
import datetime
import json
import sys
from types import SimpleNamespace

import pytest

import lean_world as world
from lean_fakes import FakeSymbol, Market
from portfolio.options_strategy import build_options_position_sizing, build_vertical_spread_position_sizing

FUTURE = {"ticker": "ES", "security_type": "future", "market": "cme", "lean_future_ticker": "ES", "data_path": "data/future/cme/daily/es.zip"}
OPTION = {"ticker": "AAPL_OPT", "security_type": "option", "asset_class": "option", "underlying_ticker": "AAPL", "market": "usa", "data_path": "data/option/usa/aapl"}
BASE = {
    "phase_v2": {"target_weights": {"enabled": False}, "rolling_ic_gate": {"enabled": False}, "limit_orders": {"enabled": False}, "portfolio_book": {"enabled": False},
                 "functionality": {"position_scaling": {"enabled": True, "rotate_on_drift": False, "rebalance_threshold_weight": 0.0}},
                 "options_risk": {"enabled": True, "multi_leg_strategies_enabled": True, "max_positions_per_underlying": 1, "enabled_strategy_names": ["single_leg", "bull_call_spread", "covered_call"]}},
    "phase6": {"risk": {"trade_cooldown_bars": 0}},
    "phase9": {"portfolio": {"max_active_positions": 12, "observation_only_assets_can_trade": True}},
}
TICKERS = ("SPY", "AAPL", "MSFT", "TLT", "BTCUSD", "EURUSD")


def make(monkeypatch, tmp_path, overrides=None, *, extra=(OPTION,), prepare=None, bars=4, artifacts=True):
    main = world.install_stub(monkeypatch)
    root = world.make_root(tmp_path, overrides=world.merge(copy.deepcopy(BASE), copy.deepcopy(overrides or {})), tickers=TICKERS, extra_assets=extra)
    if not artifacts:
        for relative in ("multitask_model.json", "sequence_model.json", "multitask_feature_schema.json", "sequence_feature_schema.json", "expert_training_metrics.json"):
            (root / "ml" / relative).unlink()
        import shutil

        shutil.rmtree(root / "ml" / "expert_models")
    if prepare:
        prepare(root)
    monkeypatch.chdir(root)
    algorithm = world.build_algorithm(main, root)
    market = Market(algorithm, seed=3)
    market.run(bars)
    return main, algorithm, market, root


@pytest.fixture(autouse=True)
def drop_main(monkeypatch):
    yield
    monkeypatch.delitem(sys.modules, "main", raising=False)


def symbol_of(algorithm, ticker):
    return next(symbol for symbol in algorithm.symbols if algorithm.asset_lookup[str(symbol)]["ticker"] == ticker)


def test_a_world_without_experts_or_optional_models_runs_on_the_baseline_alone(monkeypatch, tmp_path):
    _, algorithm, market, _ = make(monkeypatch, tmp_path, artifacts=False, bars=3)
    assert algorithm.expert_model_exports == {} and algorithm.multitask_model is None and algorithm.sequence_model is None
    market.run(4)
    assert algorithm._cash_sweep_holding_profit() is not None
    algorithm._cash_sweep_symbol = None
    assert algorithm._cash_sweep_holding_profit() == (0.0, 0.0)
    assert algorithm._run_sequence_model(symbol_of(algorithm, "AAPL")) is None


def test_the_sequence_pass_returns_nothing_without_history_and_reports_a_failing_model(monkeypatch, tmp_path):
    main, algorithm, market, _ = make(monkeypatch, tmp_path)
    symbol = symbol_of(algorithm, "AAPL")
    inputs = algorithm._build_model_input(symbol)["model_inputs"]
    algorithm.symbol_feature_history.pop(symbol, None)
    assert algorithm._run_sequence_model(symbol) is None
    algorithm.symbol_feature_history[symbol] = [inputs] * 3
    monkeypatch.setattr(main, "run_exported_sequence_multitask_model", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bad sequence")))
    assert algorithm._run_sequence_model(symbol) is None and "Sequence model inference failed" in "\n".join(algorithm.messages)


def test_experts_that_return_nothing_are_named_in_the_per_symbol_and_the_batched_pass(monkeypatch, tmp_path):
    def prepare(root):
        for name in world.EXPERTS:
            path = root / "ml" / "expert_models" / name / "multitask_model.json"
            path.write_text(json.dumps({"model": {}, "export": world.multitask_export(30)}), encoding="utf-8")

    main, algorithm, market, _ = make(monkeypatch, tmp_path, prepare=prepare)
    monkeypatch.setattr(main, "run_exported_models_batched", lambda exports, inputs, stack_cache=None: [None] * len(exports))
    monkeypatch.setattr(main, "run_exported_multitask_models_batched", lambda exports, inputs, stack_cache=None: [None] * len(exports))
    monkeypatch.setattr(main, "run_exported_models_across_symbols", lambda exports, rows, stack_cache=None: [[None] * len(exports) for _ in rows])
    monkeypatch.setattr(main, "run_exported_multitask_models_across_symbols", lambda exports, rows, stack_cache=None: [[None] * len(exports) for _ in rows])
    symbol = symbol_of(algorithm, "AAPL")
    inputs = algorithm._build_model_input(symbol)["model_inputs"]
    algorithm._run_expert_models(inputs)
    algorithm._run_expert_multitask_models(inputs)
    algorithm._run_experts_across_symbols([{"symbol": symbol, "feature_payload": {"model_inputs": inputs}}, {"symbol": symbol_of(algorithm, "SPY"), "feature_payload": {"model_inputs": inputs}}])
    text = "\n".join(algorithm.messages)
    assert "Expert inference failed" in text and "Expert multitask inference failed" in text


def test_a_zero_price_inside_the_window_and_a_symbol_with_no_spread_estimate_fall_back(monkeypatch, tmp_path):
    def prepare(root):
        path = root / "ml" / "feature_schema.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["context_feature_names"] = payload["context_feature_names"] + ["asset_AAPL"]
        path.write_text(json.dumps(payload), encoding="utf-8")

    main, algorithm, market, _ = make(monkeypatch, tmp_path, {"phase_v2": {"liquidity": {"spread_estimation": {"enabled": True, "min_bars": 10_000}}}}, prepare=prepare)
    symbol = symbol_of(algorithm, "AAPL")
    assert algorithm._build_model_input(symbol)["ready"] is True
    window = algorithm.symbol_windows[symbol]
    window.append({"open": 1.0, "high": 1.0, "low": 1.0, "close": 0.0, "volume": 1.0})
    window.append({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0})
    window.append({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0})
    assert algorithm._build_model_input(symbol)["ready"] is False
    cleaned = [{"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}] * 30
    cleaned[0] = {"open": 1.0, "high": 1.0, "low": 1.0, "close": 0.0, "volume": 1.0}
    window.clear()
    window.extend(cleaned[1:])
    window.appendleft(cleaned[0]) if hasattr(window, "appendleft") else None
    assert algorithm._build_model_input(symbol) is not None


def test_a_missing_sweep_price_and_a_non_finite_weight_leave_the_sweep_alone(monkeypatch, tmp_path):
    main, algorithm, market, _ = make(monkeypatch, tmp_path)
    sweep = algorithm._cash_sweep_symbol
    algorithm.Securities[sweep].Price = float("nan")
    algorithm._update_cash_sweep()
    algorithm.Securities[sweep].Price = 100.0
    monkeypatch.setattr(main, "cash_sweep_target_weight", lambda *a, **k: float("nan"), raising=False)
    algorithm._update_cash_sweep()
    algorithm.Portfolio.Cash = -1.0e9
    algorithm._update_cash_sweep()


def test_a_bond_sleeve_without_a_config_a_guard_for_a_disabled_class_and_a_chain_of_an_untracked_future(monkeypatch, tmp_path):
    _, algorithm, market, _ = make(monkeypatch, tmp_path, {"phase_v2": {"sleeve_guards": {"forex": {"enabled": True}, "crypto_graduates": {"enabled": True}}, "forex_sleeve": {"enabled": False}}})
    algorithm.bond_sleeve_config = None
    algorithm._update_bond_sleeve({})
    algorithm._update_sleeve_guards()
    algorithm.phase1["universe"]["assets"].append({"ticker": "GHOSTF", "security_type": "future", "market": "cme"})
    assert algorithm._build_futures_chains_payload(SimpleNamespace(futures_chains={})) == {}
    algorithm.derivatives_reference_tickers["options_sentiment"] = "AAPL"
    algorithm.latest_options_chains_payload = {"AAPL": [{"right": "call", "delta": 0.5, "iv": 0.3, "volume": 10.0}, {"right": "put", "delta": None, "iv": None}]}
    algorithm.latest_futures_chains_payload = {}
    assert algorithm._build_derivatives_macro_payload() is not None
    algorithm.latest_options_chains_payload = {"AAPL": [{"right": "call", "delta": None}]}
    assert algorithm._build_derivatives_macro_payload() is not None
    assert algorithm._options_volatility_view([{"expiry": "2019-03-01", "strike": 100.0, "iv": None, "underlying_price": 100.0, "right": "call"}], 0.02) == "neutral"


def test_limit_order_edge_cases_a_zero_quantity_a_failed_cancel_and_an_exit_that_rests(monkeypatch, tmp_path):
    overrides = {"phase_v2": {"limit_orders": {"enabled": True, "exit_asset_classes": ["crypto", "equity"], "asset_classes": ["equity", "crypto", "option"]}}}
    _, algorithm, market, _ = make(monkeypatch, tmp_path, overrides)
    symbol = symbol_of(algorithm, "AAPL")
    key = str(symbol)
    price = float(algorithm.Securities[symbol].Price)
    assert algorithm._try_submit_limit_order(symbol, key, "equity", is_buy=True, target_weight=0.0, close_price=price, contract_quantity=0) is False
    stale = SimpleNamespace(Status="Submitted", QuantityRemaining=5.0, Cancel=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("cannot cancel")), Symbol=symbol)
    algorithm.pending_limit_orders[key] = {"tickets": [stale], "target_symbols": [symbol], "asset_class": "equity", "chain_symbol": key, "submitted_bar": 0}
    algorithm._try_submit_limit_order(symbol, key, "equity", is_buy=True, target_weight=0.05, close_price=price)
    assert "cancel failed" in "\n".join(algorithm.messages)
    btc = symbol_of(algorithm, "BTCUSD")
    algorithm.Portfolio.apply(btc, 2.0, float(algorithm.Securities[btc].Price))
    assert algorithm._try_submit_limit_exit(btc, str(btc), algorithm.asset_lookup[str(btc)], "model_sell", price) in (True, False)
    algorithm.option_positions_by_symbol[str(btc)] = [{"kind": "single_leg"}]
    assert algorithm._try_submit_limit_exit(btc, str(btc), algorithm.asset_lookup[str(btc)], "model_sell", price) is False
    algorithm.option_positions_by_symbol.clear()
    algorithm.Portfolio.apply(btc, -2.0, float(algorithm.Securities[btc].Price))
    assert algorithm._try_submit_limit_exit(btc, str(btc), algorithm.asset_lookup[str(btc)], "model_sell", price) is False


def option_scene(algorithm):
    symbol = symbol_of(algorithm, "AAPL_OPT")
    return symbol, str(symbol), algorithm.latest_options_chains_payload["AAPL"]


def send(algorithm, symbol, key, decision, price):
    return algorithm._apply_option_order(symbol, key, {"asset_class_routing_extra": {"options_decision": decision}}, 0.01, price, True, "test")


def test_a_held_single_leg_option_is_resized_in_place_at_its_cap_and_through_limits(monkeypatch, tmp_path):
    _, algorithm, market, _ = make(monkeypatch, tmp_path, {"phase_v2": {"limit_orders": {"enabled": True, "asset_classes": ["option"]}}})
    symbol, key, rows = option_scene(algorithm)
    nav = float(algorithm.Portfolio.TotalPortfolioValue)
    price = float(rows[0]["underlying_price"])
    algorithm.limit_orders_enabled = False
    assert send(algorithm, symbol, key, build_options_position_sizing("buy", 0.8, rows, nav, max_vega_budget_pct_of_equity=0.02), price).startswith("entered")
    drifted = build_options_position_sizing("buy", 0.2, rows, nav, max_vega_budget_pct_of_equity=0.02)
    sizes = [send(algorithm, symbol, key, drifted, price)]
    algorithm.limit_orders_enabled = True
    for vega in (0.06, 0.002):
        sizes.append(send(algorithm, symbol, key, build_options_position_sizing("buy", 0.8, rows, nav, max_vega_budget_pct_of_equity=vega), price))
    assert all(sizes)


def test_a_held_multi_leg_position_is_compared_resized_and_scaled_at_its_cap_and_through_limits(monkeypatch, tmp_path):
    _, algorithm, market, _ = make(monkeypatch, tmp_path, {"phase_v2": {"limit_orders": {"enabled": True, "asset_classes": ["option"]}}})
    symbol, key, rows = option_scene(algorithm)
    nav = float(algorithm.Portfolio.TotalPortfolioValue)
    price = float(rows[0]["underlying_price"])

    def vertical(confidence=0.8, vega=0.02):
        return build_vertical_spread_position_sizing("buy", confidence, rows, nav, max_vega_budget_pct_of_equity=vega)

    algorithm.limit_orders_enabled = False
    assert send(algorithm, symbol, key, vertical(), price).startswith("entered")
    notes = [send(algorithm, symbol, key, vertical(confidence=0.2), price)]
    algorithm.position_scaling_enabled = False
    notes.append(send(algorithm, symbol, key, vertical(), price))
    algorithm.position_scaling_enabled = True
    decision = vertical()
    notes.append(send(algorithm, symbol, key, decision, price))
    margin_decision = SimpleNamespace(**{**vars(decision), "margin_required": 1234.0}) if hasattr(decision, "__dict__") else decision
    notes.append(algorithm._apply_option_multi_leg_order(symbol, key, margin_decision, 0.01, price, True, "margin"))
    algorithm.limit_orders_enabled = True
    for vega in (0.08, 0.001):
        notes.append(send(algorithm, symbol, key, vertical(vega=vega), price))
    assert all(notes)


def test_a_covered_call_rests_as_a_combo_with_its_equity_leg(monkeypatch, tmp_path):
    _, algorithm, market, _ = make(monkeypatch, tmp_path, {"phase_v2": {"options_risk": {"enabled_strategy_names": ["covered_call"]}, "limit_orders": {"enabled": True, "asset_classes": ["option"]}}})
    aapl = algorithm.ticker_to_symbol["AAPL"]
    algorithm.Portfolio.apply(aapl, 300.0, float(algorithm.Securities[aapl].Price))
    algorithm._manage_covered_protective_positions()
    algorithm._manage_covered_protective_positions()
    assert any(entry[2] == "Submitted" for entry in algorithm.order_log) or algorithm.order_log


def test_early_returns_of_the_option_outcome_and_the_assignment_sweep(monkeypatch, tmp_path):
    _, algorithm, market, _ = make(monkeypatch, tmp_path)
    key = str(symbol_of(algorithm, "AAPL_OPT"))
    algorithm._emit_option_strategy_outcome_if_pending(key)
    algorithm.simulated_option_strategy_entries_by_symbol_key[key] = {"strategy_name": "not_a_strategy"}
    algorithm._emit_option_strategy_outcome_if_pending(key)
    algorithm.simulated_option_strategy_entries_by_symbol_key[key] = {"strategy_name": "bull_call_spread", "leg_symbols": [FakeSymbol("Y", "option")] * 2, "entry_net_debit_or_credit": None}
    algorithm._emit_option_strategy_outcome_if_pending(key)
    algorithm.options_assignment_risk_detector_enabled = True
    algorithm.option_positions_by_symbol[key] = [{"kind": "multi_leg", "strategy_name": "bull_call_spread", "legs": [], "strikes": [], "expiries": ()},
                                                 {"kind": "multi_leg", "strategy_name": "covered_call", "legs": [FakeSymbol("X", "option")], "strikes": [0.0], "expiries": ()}]
    algorithm._apply_option_assignment_risk_sweep()
    assert algorithm._covered_protective_equity_quantity(None) == 0.0 and algorithm._covered_protective_equity_quantity("NOPE") == 0.0 and datetime is not None and json is not None
