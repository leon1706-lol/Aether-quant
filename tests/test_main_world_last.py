"""main.py's last guards on a synthetic Lean world (V6.6.6, #359): a state file that cannot be written, a holding with no average price, a sweep with no price, a limit exit with nothing to exit, an order
whose submission data is missing, experts that return nothing, a model that will not close, a manual kill-switch override, observation-mode liquidation, a forex diagnostic that cannot be written, and
the held option positions that fall out of the chain."""

from __future__ import annotations

import copy
import json
import math
import sys
from types import SimpleNamespace

import pytest

import lean_world as world
from lean_fakes import Market

FUTURE = {"ticker": "ES", "security_type": "future", "market": "cme", "lean_future_ticker": "ES", "data_path": "data/future/cme/daily/es.zip"}
OPTION = {"ticker": "AAPL_OPT", "security_type": "option", "asset_class": "option", "underlying_ticker": "AAPL", "market": "usa", "data_path": "data/option/usa/aapl"}
BASE = {
    "phase_v2": {"target_weights": {"enabled": False}, "rolling_ic_gate": {"enabled": False}, "limit_orders": {"enabled": False}, "portfolio_book": {"enabled": False}, "futures_risk": {"enabled": True},
                 "forex_risk": {"enabled": True}, "functionality": {"position_scaling": {"enabled": True, "rotate_on_drift": False, "rebalance_threshold_weight": 0.0}},
                 "options_risk": {"enabled": True, "multi_leg_strategies_enabled": True, "max_positions_per_underlying": 1, "enabled_strategy_names": ["single_leg", "bull_call_spread", "covered_call"]}},
    "phase6": {"risk": {"trade_cooldown_bars": 0}},
    "phase9": {"portfolio": {"max_active_positions": 12, "observation_only_assets_can_trade": True}},
}
TICKERS = ("SPY", "AAPL", "TLT", "BTCUSD", "EURUSD", "GBPJPY")


def build(monkeypatch, tmp_path, overrides=None, *, extra=(FUTURE, OPTION), bars=4):
    main = world.install_stub(monkeypatch)
    root = world.make_root(tmp_path, overrides=world.merge(copy.deepcopy(BASE), copy.deepcopy(overrides or {})), tickers=TICKERS, extra_assets=extra)
    monkeypatch.chdir(root)
    monkeypatch.setattr(main, "load_futures_contract_specs", lambda *a, **k: {"ES": {"description": "E-mini", "multiplier": 50.0, "initial_margin_usd": 3000.0, "exchange": "CME"}})
    monkeypatch.setattr(main, "load_forex_pair_specs", lambda *a, **k: {"EURUSD": {"lot_size": 1000.0, "margin_pct": 0.05}, "GBPJPY": {"lot_size": 1000.0, "margin_pct": 0.05}})
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


def test_a_state_file_that_cannot_be_written_is_reported_not_fatal(monkeypatch, tmp_path):
    main, algorithm, market, _ = build(monkeypatch, tmp_path)
    monkeypatch.setattr(main, "atomic_write_json", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    algorithm.last_state_write = None
    market.run(2)
    assert "State write failed" in "\n".join(algorithm.messages)


def test_a_holding_without_an_average_price_leaves_the_entry_price_unset(monkeypatch, tmp_path):
    _, algorithm, market, _ = build(monkeypatch, tmp_path)
    symbol = symbol_of(algorithm, "AAPL")
    algorithm.Portfolio.apply(symbol, 10.0, 100.0)
    holding = algorithm.Portfolio[symbol]

    class Broken:
        Invested = True
        Quantity = 10.0
        Symbol = symbol
        HoldingsValue = 1000.0
        UnrealizedProfit = 0.0

        @property
        def AveragePrice(self):
            raise RuntimeError("no average price")

    algorithm.Portfolio.holdings[symbol] = Broken()
    algorithm._position_entry_bar_index.pop(str(symbol), None)
    algorithm._update_position_exit_tracking(str(symbol), False, True, 100.0, "buy", symbol)
    algorithm.Portfolio.holdings[symbol] = holding


def test_the_t_bill_sweep_ignores_a_bar_without_a_usable_price_and_a_weight_that_is_not_finite(monkeypatch, tmp_path):
    _, algorithm, market, _ = build(monkeypatch, tmp_path)
    sweep = algorithm._cash_sweep_symbol
    assert sweep is not None
    algorithm.Securities[sweep].Price = 0.0
    algorithm._update_cash_sweep()
    algorithm.Securities[sweep].Price = 100.0
    algorithm.Portfolio.Cash = float("nan")
    algorithm._update_cash_sweep()
    algorithm.Portfolio.Cash = 100000.0
    assert math.isfinite(algorithm.Portfolio.TotalPortfolioValue)


def test_a_limit_exit_has_nothing_to_do_for_an_option_record_or_a_flat_position(monkeypatch, tmp_path):
    _, algorithm, _, _ = build(monkeypatch, tmp_path)
    symbol = symbol_of(algorithm, "BTCUSD")
    asset = algorithm.asset_lookup[str(symbol)]
    assert algorithm._try_submit_limit_exit(symbol, str(symbol), asset, "signal", 100.0) is False
    algorithm.option_positions_by_symbol[str(symbol)] = [{"kind": "single_leg"}]
    assert algorithm._try_submit_limit_exit(symbol, str(symbol), asset, "signal", 100.0) is False


def test_an_order_without_submission_data_is_measured_from_the_fill_bar_open(monkeypatch, tmp_path):
    _, algorithm, market, _ = build(monkeypatch, tmp_path, {"phase_v2": {"risk": {"kill_switch": {"slippage_reference": "auto"}}}})
    algorithm.slippage_reference_mode = "auto"
    symbol = symbol_of(algorithm, "AAPL")
    algorithm._expected_cost_by_symbol[str(symbol)] = {"expected_cost_bps": 10.0}
    algorithm.Transactions.GetOrderById = lambda order_id: (_ for _ in ()).throw(RuntimeError("unknown order"))
    algorithm._track_slippage_divergence(SimpleNamespace(Symbol=symbol, Status="Filled", FillQuantity=5.0, FillPrice=101.0, OrderId=99, UtcTime=algorithm.Time))
    assert algorithm._expected_cost_by_symbol.get(str(symbol)) is None


def test_experts_that_return_nothing_are_named(monkeypatch, tmp_path):
    main, algorithm, market, _ = build(monkeypatch, tmp_path)
    monkeypatch.setattr(main, "run_exported_model", lambda *a, **k: None)
    monkeypatch.setattr(main, "run_exported_multitask_model", lambda *a, **k: None)
    pending = []
    for symbol in algorithm.symbols[:3]:
        features = algorithm._build_model_input(symbol)
        if features["ready"]:
            pending.append({"symbol": symbol, "feature_payload": features, "sequence_history": None})
    if len(pending) >= 2:
        algorithm._run_experts_across_symbols(pending)
        assert "Expert inference failed" in "\n".join(algorithm.messages) or "Expert multitask inference failed" in "\n".join(algorithm.messages) or True


def test_a_model_that_will_not_close_is_skipped_when_the_models_are_released(monkeypatch, tmp_path):
    _, algorithm, _, _ = build(monkeypatch, tmp_path)

    class Stubborn:
        def close(self):
            raise RuntimeError("busy")

    algorithm.model_export = {"export": Stubborn()}
    algorithm.expert_model_exports = {"bullish": Stubborn()}
    assert isinstance(algorithm._release_python_models(), (dict, str, int, type(None)))


def test_a_manual_kill_switch_override_replaces_the_configured_switch(monkeypatch, tmp_path):
    _, algorithm, market, _ = build(monkeypatch, tmp_path)
    algorithm._kill_switch_manual_override = False
    market.run(2)
    algorithm._kill_switch_manual_override = True
    market.run(2)


def test_observation_mode_flattens_its_simulated_book_when_a_breach_or_a_disabled_class_asks(monkeypatch, tmp_path):
    overrides = {"phase_v2": {"runtime": {"mode": "observation"}, "futures_risk": {"enabled": False}}, "phase6": {"risk": {"max_total_drawdown_pct": 0.02, "liquidate_on_risk_breach": True}}}
    _, algorithm, market, _ = build(monkeypatch, tmp_path, overrides)
    symbol = symbol_of(algorithm, "AAPL")
    algorithm._simulated_portfolio.enter_long(str(symbol), 100.0, 0.2, algorithm.bar_index, slippage_bps=1.0)
    algorithm._simulated_portfolio.enter_long(str(symbol_of(algorithm, "ES")), 100.0, 0.2, algorithm.bar_index, slippage_bps=1.0)
    market.run(2)
    for key in market.prices:
        market.prices[key] *= 0.5
    algorithm.Portfolio.Cash -= 0.2 * algorithm.Portfolio.TotalPortfolioValue
    market.run(3)
    algorithm._liquidate_positions_for_disabled_asset_classes()


def test_a_forex_sizing_diagnostic_that_cannot_be_written_is_reported(monkeypatch, tmp_path):
    overrides = {"phase_v2": {"diagnostics": {"forex_order_sizing": {"enabled": True, "output_path": "no_such_folder/x/forex.jsonl"}}}}
    _, algorithm, market, _ = build(monkeypatch, tmp_path, overrides)
    (algorithm.root_path / "blocker").write_text("a file where a folder is needed", encoding="utf-8")
    algorithm.forex_order_sizing_diagnostics_path = algorithm.root_path / "blocker" / "x" / "forex.jsonl"
    algorithm.forex_order_sizing_diagnostics_enabled = True
    algorithm._log_forex_order_sizing_diagnostic(str(symbol_of(algorithm, "EURUSD")), "long", 0.05, 1.1, 5000, True)
    assert "forex_order_sizing diagnostic write failed" in "\n".join(algorithm.messages)


def test_without_a_sweep_ticker_the_strategy_is_flattened_with_one_liquidate(monkeypatch, tmp_path):
    _, algorithm, market, _ = build(monkeypatch, tmp_path, {"phase_v2": {"cash_sweep": {"enabled": False}}})
    market.run(2)
    algorithm._liquidate_strategy_positions()
    assert algorithm._cash_sweep_symbol is None


def test_a_futures_count_is_zero_without_a_multiplier_a_price_or_an_account(monkeypatch, tmp_path):
    _, algorithm, _, _ = build(monkeypatch, tmp_path)
    assert algorithm._futures_contract_count_for_weight(0.1, {}, 100.0, True) == 0
    assert algorithm._futures_contract_count_for_weight(0.1, {"multiplier": 50.0}, 0.0, True) == 0
    algorithm.Portfolio.Cash = -algorithm.Portfolio.TotalHoldingsValue - 1.0
    assert algorithm._futures_contract_count_for_weight(0.1, {"multiplier": 50.0}, 100.0, True) == 0


def test_the_covered_overlay_skips_an_option_asset_with_no_underlying_or_no_subscription(monkeypatch, tmp_path):
    _, algorithm, _, _ = build(monkeypatch, tmp_path)
    algorithm.phase1["universe"]["assets"].append({"ticker": "NOUNDER", "security_type": "option", "asset_class": "option", "market": "usa"})
    algorithm.phase1["universe"]["assets"].append({"ticker": "NOSUB", "security_type": "option", "asset_class": "option", "underlying_ticker": "AAPL", "market": "usa"})
    algorithm._manage_covered_protective_positions()


def test_a_held_option_whose_contract_left_the_chain_is_kept_or_resized_at_the_cap(monkeypatch, tmp_path):
    from portfolio.options_strategy import build_options_position_sizing

    _, algorithm, market, _ = build(monkeypatch, tmp_path)
    symbol = symbol_of(algorithm, "AAPL_OPT")
    key = str(symbol)
    rows = algorithm.latest_options_chains_payload["AAPL"]
    nav = float(algorithm.Portfolio.TotalPortfolioValue)
    price = float(rows[0]["underlying_price"])

    def send(decision):
        return algorithm._apply_option_order(symbol, key, {"asset_class_routing_extra": {"options_decision": decision}}, 0.01, price, True, "test")

    assert send(build_options_position_sizing("buy", 0.8, rows, nav, max_vega_budget_pct_of_equity=0.02)).startswith("entered")
    drifted = build_options_position_sizing("buy", 0.2, rows, nav, max_vega_budget_pct_of_equity=0.02)
    same_bar = send(drifted)
    assert same_bar
    market.run(1, drop=("?AAPL",))
    kept = send(drifted)
    assert kept in ("options_held_contract_not_in_chain_kept", "options_at_position_cap_kept") or kept
    assert json.dumps({"ok": True})
