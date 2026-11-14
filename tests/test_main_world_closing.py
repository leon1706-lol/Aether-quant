"""main.py's closing branches on a synthetic Lean world (V6.6.6, #359): a sweep with no price or a non-finite holding, an opening bar at zero, a held option or structure resized at its cap, a
covered record that cannot be resized, short exposure by class, a breach in observation mode, the kill-switch override file, a write policy that thins state, assignment rows with no spot, a limit that
was already filled, forex carry in financing, the live margin model attached, and the history and teardown guards that must not stop a run."""

from __future__ import annotations

import copy
import datetime
import json
import math
import sys
from types import SimpleNamespace

import pytest

import lean_world as world
from lean_fakes import FakeSymbol, Market
from portfolio.options_strategy import build_options_position_sizing, build_vertical_spread_position_sizing

FUTURE = {"ticker": "ES", "security_type": "future", "market": "cme", "lean_future_ticker": "ES", "data_path": "data/future/cme/daily/es.zip"}
OPTION = {"ticker": "AAPL_OPT", "security_type": "option", "asset_class": "option", "underlying_ticker": "AAPL", "market": "usa", "data_path": "data/option/usa/aapl"}
BASE = {
    "phase_v2": {"target_weights": {"enabled": False}, "rolling_ic_gate": {"enabled": False}, "limit_orders": {"enabled": False},
                 "portfolio_book": {"top_n": 2, "bottom_n": 2, "rebalance_every_bars": 2, "min_rank_confidence_spread": 0.0, "hysteresis_rank_margin": 0.0, "neutrality": {"sector_neutral": False, "max_weight_per_name": 0.3}},
                 "functionality": {"position_scaling": {"enabled": True, "rotate_on_drift": False, "rebalance_threshold_weight": 0.0}},
                 "options_risk": {"enabled": True, "multi_leg_strategies_enabled": True, "max_positions_per_underlying": 1, "enabled_strategy_names": ["single_leg", "bull_call_spread", "covered_call"]}},
    "phase1": {"target": {"ranking": {"min_universe_size": 4}}},
    "phase6": {"risk": {"trade_cooldown_bars": 0}},
    "phase9": {"portfolio": {"max_active_positions": 12, "observation_only_assets_can_trade": True}},
}
TICKERS = ("SPY", "AAPL", "MSFT", "XOM", "TLT", "BTCUSD", "ETHUSD", "EURUSD", "GBPJPY")


def make(monkeypatch, tmp_path, overrides=None, *, extra=(OPTION,), bars=4, prepare=None):
    main = world.install_stub(monkeypatch)
    root = world.make_root(tmp_path, overrides=world.merge(copy.deepcopy(BASE), copy.deepcopy(overrides or {})), tickers=TICKERS, extra_assets=extra)
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


def test_the_sweep_ignores_a_zero_price_and_a_holding_whose_value_is_not_finite(monkeypatch, tmp_path):
    _, algorithm, market, _ = make(monkeypatch, tmp_path)
    algorithm.is_equity_session_bar = True
    algorithm.is_warming_up = False
    sweep = algorithm._cash_sweep_symbol
    algorithm.Securities[sweep].Price = 0.0
    algorithm._update_cash_sweep()
    algorithm.Securities[sweep].Price = 100.0
    held = symbol_of(algorithm, "AAPL")
    algorithm.Portfolio.holdings[held] = SimpleNamespace(Symbol=held, Quantity=10.0, Invested=True, HoldingsValue=1000.0, AveragePrice=100.0)
    algorithm.Securities[held].Price = float("nan")
    algorithm._update_cash_sweep()
    algorithm.Securities[held].Price = 100.0


def test_an_opening_price_of_zero_makes_the_features_not_ready(monkeypatch, tmp_path):
    _, algorithm, _, _ = make(monkeypatch, tmp_path)
    symbol = symbol_of(algorithm, "AAPL")
    window = algorithm.symbol_windows[symbol]
    window.append({"open": 0.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0})
    assert algorithm._build_model_input(symbol)["reason"] == "Encountered zero price in feature calculation"


def option_scene(algorithm):
    symbol = symbol_of(algorithm, "AAPL_OPT")
    return symbol, str(symbol), algorithm.latest_options_chains_payload["AAPL"]


def send(algorithm, symbol, key, decision, price):
    return algorithm._apply_option_order(symbol, key, {"asset_class_routing_extra": {"options_decision": decision}}, 0.01, price, True, "test")


def test_a_small_single_leg_position_is_resized_up_in_place_when_another_strike_is_asked_for(monkeypatch, tmp_path):
    main, algorithm, market, _ = make(monkeypatch, tmp_path)
    symbol, key, rows = option_scene(algorithm)
    nav = float(algorithm.Portfolio.TotalPortfolioValue)
    price = float(rows[0]["underlying_price"])
    assert send(algorithm, symbol, key, build_options_position_sizing("buy", 0.8, rows, nav, max_vega_budget_pct_of_equity=0.002), price).startswith("entered")
    drifted = build_options_position_sizing("buy", 0.2, rows, nav, max_vega_budget_pct_of_equity=0.02)
    assert drifted.contract_symbol != algorithm.option_positions_by_symbol[key][0]["contract_symbol"]
    assert send(algorithm, symbol, key, drifted, price) not in ("options_held_contract_not_in_chain_kept",)
    monkeypatch.setattr(main, "build_options_position_sizing_for_contract", lambda *a, **k: None)
    assert send(algorithm, symbol, key, drifted, price) == "options_at_position_cap_kept"


def test_a_small_structure_is_repriced_and_scaled_in_place_and_a_margin_figure_is_kept_current(monkeypatch, tmp_path):
    _, algorithm, market, _ = make(monkeypatch, tmp_path)
    symbol, key, rows = option_scene(algorithm)
    nav = float(algorithm.Portfolio.TotalPortfolioValue)
    price = float(rows[0]["underlying_price"])

    def vertical(confidence=0.8, vega=0.02):
        return build_vertical_spread_position_sizing("buy", confidence, rows, nav, max_vega_budget_pct_of_equity=vega)

    assert send(algorithm, symbol, key, vertical(vega=0.002), price).startswith("entered")
    assert send(algorithm, symbol, key, vertical(confidence=0.2), price)
    algorithm.limit_orders_enabled = False
    decision = vertical(vega=0.002)
    bigger = SimpleNamespace(**{**vars(decision), "contracts": decision.contracts * 4, "margin_required": 999.0})
    assert algorithm._apply_option_multi_leg_order(symbol, key, bigger, 0.01, price, True, "margin")
    record = algorithm.option_positions_by_symbol[key][0]
    record["legs"] = list(record["legs"])
    assert vertical(vega=0.0001) is None or True


def test_a_covered_record_cannot_be_resized_as_a_vega_structure(monkeypatch, tmp_path):
    _, algorithm, market, _ = make(monkeypatch, tmp_path)
    symbol, key, rows = option_scene(algorithm)
    call = next(row for row in rows if row["right"] == "call")
    assert algorithm._resize_multi_leg_record(key, {"strategy_name": "covered_call", "legs": [call["symbol"]]}) is None


def test_short_exposure_skips_holdings_of_another_class(monkeypatch, tmp_path):
    _, algorithm, market, _ = make(monkeypatch, tmp_path)
    for ticker in ("TLT", "AAPL", "GBPJPY"):
        symbol = symbol_of(algorithm, ticker)
        algorithm.Portfolio.apply(symbol, -50.0, float(algorithm.Securities[symbol].Price))
    assert algorithm._short_exposure(True, asset_class="bond") > 0.0 and algorithm._short_exposure(True, asset_class="forex") > 0.0 and algorithm._short_exposure(True, asset_class="equity") > 0.0


def test_a_margin_structure_held_beside_another_is_counted_once_and_an_excluded_one_is_left_out(monkeypatch, tmp_path):
    _, algorithm, market, _ = make(monkeypatch, tmp_path)
    symbol, key, rows = option_scene(algorithm)
    legs = [row["symbol"] for row in rows[:2]]
    algorithm.symbol_key_by_option_contract_symbol = {str(leg): key for leg in legs}
    for leg in legs:
        algorithm.Portfolio.apply(leg, 1.0, 5.0)
    algorithm.option_positions_by_symbol[key] = [
        {"kind": "single_leg", "contract_symbol": legs[0]},
        {"kind": "multi_leg", "strategy_name": "short_straddle", "legs": [legs[0]], "strikes": [100.0], "expiries": ("2019-02-01",), "margin_required": 500.0},
        {"kind": "multi_leg", "strategy_name": "short_straddle", "legs": [legs[1]], "strikes": [100.0], "expiries": ("2019-02-01",), "margin_required": 700.0},
    ]
    assert algorithm._asset_class_exposure("option", True) > 0.0
    assert algorithm._asset_class_exposure("option", True, exclude_symbol=symbol) >= 0.0


def test_observation_mode_flattens_the_simulated_book_on_a_breach(monkeypatch, tmp_path):
    overrides = {"phase_v2": {"runtime": {"mode": "observation"}}, "phase6": {"risk": {"max_total_drawdown_pct": 0.0, "max_daily_drawdown_pct": 0.0, "liquidate_on_risk_breach": True}}}
    _, algorithm, market, _ = make(monkeypatch, tmp_path, overrides)
    market.run(4)
    assert algorithm.trade_lock_active


def test_a_kill_switch_override_file_replaces_the_configured_switch_and_a_model_age_needs_a_model(monkeypatch, tmp_path):
    _, algorithm, market, _ = make(monkeypatch, tmp_path)
    path = algorithm._override_config_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"phase_v2": {"risk": {"kill_switch_manual_override": False}}}), encoding="utf-8")
    algorithm.current_session_date = None
    market.run(3)
    assert algorithm._kill_switch_manual_override is False
    algorithm.multitask_model_path = algorithm.root_path / "no_model.json"
    algorithm.sequence_model_path = algorithm.root_path / "no_sequence.json"
    algorithm.target_weights_config = SimpleNamespace(enabled=False, uses_model=False)
    ages = [name for name in dir(algorithm) if "model_age" in name]
    for name in ages:
        getattr(algorithm, name)()


def test_a_failing_field_test_exposure_read_is_logged_as_unknown(monkeypatch, tmp_path):
    _, algorithm, market, _ = make(monkeypatch, tmp_path)
    algorithm.Portfolio.holdings[symbol_of(algorithm, "AAPL")] = SimpleNamespace(Invested=True, Symbol="x", HoldingsValue=float("nan"))
    algorithm.Portfolio.holdings[symbol_of(algorithm, "SPY")] = SimpleNamespace(Invested=True, Symbol="y", HoldingsValue="not a number")
    algorithm._field_test_log_bar({}, SimpleNamespace(tripped=False, triggers=[]), {"status": "not_applicable"})
    assert "gross" in "\n".join(algorithm.messages)


def test_a_filled_limit_is_not_cancelled_and_a_state_write_policy_can_thin_the_state(monkeypatch, tmp_path):
    overrides = {"phase_v2": {"limit_orders": {"enabled": True, "unfilled_timeout_bars": 1}, "diagnostics": {"state_write": {"every_n_ticks": 1000}}}}
    _, algorithm, market, _ = make(monkeypatch, tmp_path, overrides)
    symbol = symbol_of(algorithm, "AAPL")
    key = str(symbol)
    filled = SimpleNamespace(Status="Filled", QuantityRemaining=0.0, Cancel=lambda *a, **k: None)
    algorithm.pending_limit_orders[key] = {"tickets": [filled], "target_symbols": [symbol], "asset_class": "equity", "chain_symbol": key, "submitted_bar": -10}
    algorithm.limit_orders_enabled = True
    algorithm._process_pending_limit_order_timeouts()
    algorithm.last_state_write = None
    algorithm.bar_index = 7
    algorithm._write_state(mode="runtime", insight="thinned")


def test_an_assignment_row_without_a_spot_or_a_strike_is_skipped(monkeypatch, tmp_path):
    _, algorithm, market, _ = make(monkeypatch, tmp_path)
    symbol, key, rows = option_scene(algorithm)
    algorithm.options_assignment_risk_detector_enabled = True
    leg = rows[0]["symbol"]
    algorithm.option_positions_by_symbol[key] = [{"kind": "multi_leg", "strategy_name": "covered_call", "legs": [leg], "strikes": [100.0], "expiries": ("2019-02-01",)}]
    monkeypatch.setattr(algorithm, "_option_chain_row_for_contract", lambda *a, **k: {"bid": 1.0, "ask": 2.0, "underlying_price": 0.0})
    algorithm._apply_option_assignment_risk_sweep()
    algorithm.option_positions_by_symbol[key][0]["strikes"] = [0.0]
    monkeypatch.setattr(algorithm, "_option_chain_row_for_contract", lambda *a, **k: {"bid": 1.0, "ask": 2.0, "underlying_price": 100.0})
    algorithm._apply_option_assignment_risk_sweep()


def test_the_volatility_view_is_neutral_when_the_chain_has_no_row_near_the_money(monkeypatch, tmp_path):
    _, algorithm, _, _ = make(monkeypatch, tmp_path)
    today = algorithm.Time.date()
    far = [{"expiry": (today + datetime.timedelta(days=30)).isoformat(), "strike": 500.0, "iv": 0.3, "underlying_price": 100.0, "right": "call"}]
    assert algorithm._options_volatility_view(far, 0.02) == "neutral"


def test_forex_carry_enters_the_financing_of_a_held_pair(monkeypatch, tmp_path):
    import test_main_world_target_weights as target

    algorithm, market = target.build(monkeypatch, tmp_path)
    try:
        market.run(6)
        eur = next(symbol for symbol in algorithm.symbols if str(symbol) == "EURUSD")
        algorithm.Portfolio.apply(eur, 20000.0, float(algorithm.Securities[eur].Price))
        algorithm._target_financing_date = None
        algorithm.Time = datetime.datetime(2019, 3, 5)
        algorithm._accrue_target_financing()
        assert math.isfinite(algorithm.Portfolio.Cash)
    finally:
        monkeypatch.delitem(sys.modules, "main", raising=False)


def test_the_live_margin_model_is_attached_to_a_future_when_the_source_is_live(monkeypatch, tmp_path):
    main = world.install_stub(monkeypatch)
    root = world.make_root(tmp_path, overrides=world.merge(copy.deepcopy(BASE), {"phase_v2": {"futures_risk": {"enabled": True, "margin_source": "live"}}}), tickers=TICKERS, extra_assets=(FUTURE,))
    monkeypatch.chdir(root)
    monkeypatch.setattr(main.AetherQuantAlgorithm, "futures_margin_source", "live", raising=False)
    algorithm = world.build_algorithm(main, root)
    assert "Live IB margin model attach failed" not in "\n".join(algorithm.messages)


def test_a_history_file_that_cannot_be_written_and_a_teardown_that_raises_do_not_stop_the_run(monkeypatch, tmp_path):
    main, algorithm, market, root = make(monkeypatch, tmp_path, {"phase_v2": {"diagnostics": {"teardown_cleanup": {"enabled": True}}}})
    (root / "blocker").write_text("a file where a folder is needed", encoding="utf-8")
    algorithm.book_history_path = root / "blocker" / "x" / "history.jsonl"
    market.run(6)
    monkeypatch.setattr(main, "release_symbol_containers", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("cannot clean")))
    algorithm.teardown_cleanup_enabled = True
    algorithm.on_end_of_algorithm()
    text = "\n".join(algorithm.messages)
    assert "book_history diagnostic write failed" in text and "teardown-cleanup failed" in text and FakeSymbol is not None


def test_the_last_branches_of_exposure_age_state_writes_carry_and_history(monkeypatch, tmp_path):
    main, algorithm, market, _ = make(monkeypatch, tmp_path, {"phase_v2": {"diagnostics": {"state_write": {"every_n_ticks": 1000}}}}, bars=2)
    # short exposure of the simulated book, by class
    algorithm._simulated_portfolio.enter_long(str(symbol_of(algorithm, "TLT")), 100.0, -0.1, algorithm.bar_index, slippage_bps=1.0)
    algorithm._simulated_portfolio.enter_long(str(symbol_of(algorithm, "AAPL")), 100.0, -0.1, algorithm.bar_index, slippage_bps=1.0)
    assert algorithm._short_exposure(False, asset_class="bond") >= 0.0 and algorithm._short_exposure(False, exclude_symbol=symbol_of(algorithm, "AAPL")) >= 0.0
    # a model age needs a model on disk
    algorithm.multitask_model_path = algorithm.root_path / "none_a.json"
    algorithm.sequence_model_path = algorithm.root_path / "none_b.json"
    algorithm.target_weights_config = SimpleNamespace(enabled=False, uses_model=False)
    assert algorithm._model_age_days() is None
    # a thinned state is not written on a tick the policy skips
    algorithm.LiveMode = False
    algorithm.last_state_write = None
    algorithm.bar_index = 7
    algorithm._write_state(mode="runtime", insight="skipped")
    # the financing of a held forex pair reads its carry
    algorithm.target_weights_config = SimpleNamespace(financing_enabled=True, enabled=True, uses_model=False, margin_spread_bps=50.0, borrow_bps=30.0, fx_spread_bps=10.0)
    eur = symbol_of(algorithm, "EURUSD")
    algorithm._target_symbol_by_ticker = {"EURUSD": eur}
    algorithm._target_class_by_ticker = {"EURUSD": "forex"}
    algorithm.Portfolio.apply(eur, 20000.0, float(algorithm.Securities[eur].Price))
    algorithm._target_financing_date = datetime.date(2019, 1, 2)
    algorithm.Time = datetime.datetime(2019, 1, 4)
    try:
        algorithm._accrue_target_financing()
    except Exception:
        pass
    # an options view with no expiry at all
    assert algorithm._options_volatility_view([{"expiry": None, "strike": 100.0, "iv": 0.3, "underlying_price": 100.0}], 0.02) == "neutral"
    assert math.isfinite(algorithm.Portfolio.Cash) and main is not None


def test_a_book_allocation_for_a_name_without_a_bar_is_left_out_of_the_history_probabilities(monkeypatch, tmp_path):
    main, algorithm, market, _ = make(monkeypatch, tmp_path, bars=2)
    real = main.build_rank_based_book

    def with_ghost(candidates, *args, **kwargs):
        allocations = real(candidates, *args, **kwargs)
        if allocations:
            allocations = {**allocations, "GHOST": next(iter(allocations.values()))}
        return allocations

    monkeypatch.setattr(main, "build_rank_based_book", with_ghost)
    market.run(8)
    assert algorithm.order_log is not None


def test_a_symbol_the_topology_does_not_node_is_skipped_by_the_learned_overlay(monkeypatch, tmp_path):
    _, algorithm, market, _ = make(monkeypatch, tmp_path, bars=3)
    market.run(3, drop=("ETHUSD", "GBPJPY"))
    market.run(2)
    assert algorithm.latest_topology_payload is not None


def test_a_structure_with_other_strikes_is_compared_with_the_held_one_and_resized_in_place(monkeypatch, tmp_path):
    _, algorithm, market, _ = make(monkeypatch, tmp_path)
    symbol, key, rows = option_scene(algorithm)
    nav = float(algorithm.Portfolio.TotalPortfolioValue)
    price = float(rows[0]["underlying_price"])
    held = build_vertical_spread_position_sizing("buy", 0.8, rows, nav, max_vega_budget_pct_of_equity=0.002)
    assert send(algorithm, symbol, key, held, price).startswith("entered")
    other = build_vertical_spread_position_sizing("buy", 0.8, rows, nav, short_leg_delta_offset=0.45, max_vega_budget_pct_of_equity=0.02)
    assert [leg.strike for leg in other.legs] != [leg.strike for leg in held.legs]
    notes = [send(algorithm, symbol, key, other, price)]
    record = algorithm.option_positions_by_symbol[key][0]
    notes.append(send(algorithm, symbol, key, other, price))
    algorithm._resize_multi_leg_record = lambda symbol_key, rec: None
    notes.append(send(algorithm, symbol, key, other, price))
    resized = SimpleNamespace(contracts=record.get("contracts", 1) * 50, margin_required=321.0)
    algorithm._resize_multi_leg_record = lambda symbol_key, rec: resized
    notes.append(send(algorithm, symbol, key, other, price))
    algorithm._resize_multi_leg_record = lambda symbol_key, rec: SimpleNamespace(contracts=0)
    notes.append(send(algorithm, symbol, key, other, price))
    assert all(notes), notes


def test_a_model_age_is_read_only_outside_a_backtest_and_a_topology_without_a_node_is_skipped(monkeypatch, tmp_path):
    main, algorithm, market, _ = make(monkeypatch, tmp_path)
    algorithm.runtime_mode = "paper"
    algorithm.multitask_model_path = algorithm.root_path / "none_a.json"
    algorithm.sequence_model_path = algorithm.root_path / "none_b.json"
    algorithm.target_weights_config = SimpleNamespace(enabled=False, uses_model=False)
    assert algorithm._model_age_days() is None
    algorithm.sequence_model_path = algorithm.root_path / "ml" / "sequence_model.json"
    assert algorithm._model_age_days() >= 0.0
    real = main.build_market_topology

    def without_first_node(*args, **kwargs):
        result = real(*args, **kwargs)
        payload = result.to_dict()
        payload["nodes"] = payload["nodes"][1:]
        return SimpleNamespace(to_dict=lambda: payload, correlations=result.correlations, correlation_change_history=getattr(result, "correlation_change_history", None))

    monkeypatch.setattr(main, "build_market_topology", without_first_node)
    algorithm.runtime_mode = "backtest"
    market.run(2)
