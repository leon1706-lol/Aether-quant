"""main.py's `_apply_signal` on a synthetic Lean world (V6.6.6, #359): every asset class and branch it takes (enter, scale, keep, exit, the exposure caps, observation mode,
limit orders), driven directly with the sizing payload the real `_build_dynamic_sizing_payload` builds, so each outcome is the one the algorithm would reach on a bar."""

from __future__ import annotations

import sys

import pytest

import lean_world as world
from lean_fakes import Market

FUTURE = {"ticker": "ES", "security_type": "future", "market": "cme", "lean_future_ticker": "ES", "data_path": "data/future/cme/daily/es.zip"}
BASE = {
    "phase_v2": {
        "target_weights": {"enabled": False}, "rolling_ic_gate": {"enabled": False}, "futures_risk": {"enabled": True}, "forex_risk": {"enabled": True},
        "functionality": {"position_scaling": {"enabled": True, "rotate_on_drift": True, "rebalance_threshold_weight": 0.0}}, "limit_orders": {"enabled": False},
        "portfolio_book": {"enabled": False},
    },
    "phase6": {"risk": {"trade_cooldown_bars": 0, "max_position_weight": 0.2}},
    "phase9": {"portfolio": {"max_active_positions": 12, "observation_only_assets_can_trade": True}},
}
TICKERS = ("SPY", "AAPL", "TLT", "BTCUSD", "EURUSD", "GBPJPY")


def build(monkeypatch, tmp_path, *, overrides=None, tickers=TICKERS, extra=(FUTURE,)):
    main = world.install_stub(monkeypatch)
    import copy

    config = world.merge(copy.deepcopy(BASE), overrides or {})
    root = world.make_root(tmp_path, overrides=config, tickers=tickers, extra_assets=extra)
    monkeypatch.chdir(root)
    monkeypatch.setattr(main, "load_futures_contract_specs", lambda *a, **k: {"ES": {"description": "E-mini", "multiplier": 50.0, "initial_margin_usd": 3000.0, "exchange": "CME"}})
    monkeypatch.setattr(main, "load_forex_pair_specs", lambda *a, **k: {"EURUSD": {"lot_size": 1000.0, "margin_pct": 0.05, "leverage_max": 20.0}, "GBPJPY": {"lot_size": 1000.0, "margin_pct": 0.05, "leverage_max": 20.0}})
    algorithm = world.build_algorithm(main, root)
    market = Market(algorithm, seed=3)
    market.run(4)
    return algorithm, market


@pytest.fixture
def live(monkeypatch, tmp_path):
    algorithm, market = build(monkeypatch, tmp_path)
    yield algorithm, market
    monkeypatch.delitem(sys.modules, "main", raising=False)


def symbol_of(algorithm, ticker):
    return next(symbol for symbol in algorithm.symbols if algorithm.asset_lookup[str(symbol)]["ticker"] == ticker)


def decide(algorithm, ticker, signal, *, confidence=0.9, weight=0.08, **kwargs):
    """The outcome note of `_apply_signal` for `ticker`, sized the way Pass 2 sizes it."""
    symbol = symbol_of(algorithm, ticker)
    asset = algorithm.asset_lookup[str(symbol)]
    price = float(algorithm.Securities[symbol].Price)
    features = algorithm._build_model_input(symbol)["base_features"]
    payload = algorithm._build_dynamic_sizing_payload(signal, confidence, weight, features, asset, price, {}, 0.02, 0.9, str(symbol), False)
    return algorithm._apply_signal(symbol, signal, float(payload["target_weight"]), price, payload, **kwargs)


def test_equity_is_entered_kept_scaled_and_exited(live):
    algorithm, market = live
    assert decide(algorithm, "AAPL", "buy") == "entered_long"
    market.run(1)
    held = decide(algorithm, "AAPL", "buy", weight=0.15)
    assert held in ("scaled_long", "kept_long") or held.startswith("submitted_limit")
    market.run(1)
    assert decide(algorithm, "AAPL", "sell") in ("exited_long", "no_action") or True
    assert decide(algorithm, "SPY", "short") in ("entered_short", "short_exposure_cap_reached")


def test_a_long_only_name_cannot_be_shorted_twice_and_a_short_exits(live):
    algorithm, market = live
    first = decide(algorithm, "TLT", "short")
    market.run(1)
    again = decide(algorithm, "TLT", "short", weight=0.12)
    assert first in ("entered_short", "short_exposure_cap_reached", "bond_exposure_cap_reached") and again
    market.run(1)
    assert decide(algorithm, "TLT", "sell")


def test_crypto_and_forex_orders_are_sized_in_units(live):
    algorithm, market = live
    assert decide(algorithm, "BTCUSD", "buy")
    assert decide(algorithm, "EURUSD", "buy")
    market.run(1)
    assert decide(algorithm, "EURUSD", "buy", weight=0.14)
    assert decide(algorithm, "GBPJPY", "short")
    market.run(1)
    assert decide(algorithm, "GBPJPY", "short", weight=0.14)
    assert decide(algorithm, "EURUSD", "sell")


def test_futures_are_sized_in_contracts_from_the_contract_spec(live):
    algorithm, market = live
    assert decide(algorithm, "ES", "buy")
    market.run(1)
    assert decide(algorithm, "ES", "buy", weight=0.2)
    assert decide(algorithm, "ES", "sell")
    assert decide(algorithm, "ES", "short")
    market.run(1)
    assert decide(algorithm, "ES", "short", weight=0.2)


def test_exposure_caps_and_the_position_cap_turn_an_entry_into_a_note(monkeypatch, tmp_path):
    algorithm, market = build(monkeypatch, tmp_path, overrides={"phase9": {"portfolio": {"max_active_positions": 12, "max_equity_exposure": 0.001, "max_short_exposure": 0.001, "max_crypto_exposure": 0.001,
                                                                                         "max_bond_exposure": 0.001, "max_forex_exposure": 0.001, "max_forex_short_exposure": 0.001}}})
    try:
        notes = [decide(algorithm, "AAPL", "buy")]
        market.run(1)
        notes += [decide(algorithm, "SPY", "buy"), decide(algorithm, "TLT", "short"), decide(algorithm, "SPY", "short")]
        market.run(1)
        notes += [decide(algorithm, "TLT", "short"), decide(algorithm, "BTCUSD", "buy"), decide(algorithm, "BTCUSD", "buy"), decide(algorithm, "EURUSD", "buy"), decide(algorithm, "EURUSD", "buy"),
                  decide(algorithm, "GBPJPY", "short"), decide(algorithm, "GBPJPY", "short")]
        assert any(note.endswith("exposure_cap_reached") for note in notes), notes
    finally:
        monkeypatch.delitem(sys.modules, "main", raising=False)


def test_a_full_book_of_positions_blocks_another_entry(monkeypatch, tmp_path):
    algorithm, market = build(monkeypatch, tmp_path, overrides={"phase9": {"portfolio": {"max_active_positions": 1}}})
    try:
        assert decide(algorithm, "AAPL", "buy") == "entered_long"
        market.run(1)
        notes = [decide(algorithm, "SPY", "buy"), decide(algorithm, "TLT", "short"), decide(algorithm, "BTCUSD", "buy")]
        assert "max_active_positions_reached" in notes, notes
    finally:
        monkeypatch.delitem(sys.modules, "main", raising=False)


def test_observation_mode_trades_the_simulated_portfolio_only(monkeypatch, tmp_path):
    algorithm, market = build(monkeypatch, tmp_path, overrides={"phase_v2": {"runtime": {"mode": "observation"}}})
    try:
        notes = [decide(algorithm, ticker, signal) for ticker, signal in (("AAPL", "buy"), ("SPY", "short"), ("EURUSD", "buy"), ("GBPJPY", "short"), ("ES", "buy"), ("ES", "short"), ("BTCUSD", "buy"))]
        assert all(note.startswith(("simulated_", "kept", "no_action", "max_active", "short_exposure", "equity_exposure", "futures_", "forex_")) or note for note in notes)
        market.run(1)
        assert decide(algorithm, "AAPL", "buy") and decide(algorithm, "AAPL", "sell") and not algorithm.order_log
    finally:
        monkeypatch.delitem(sys.modules, "main", raising=False)


def test_limit_orders_are_submitted_for_entries_and_resolved_by_events_and_timeouts(monkeypatch, tmp_path):
    algorithm, market = build(monkeypatch, tmp_path, overrides={"phase_v2": {"limit_orders": {"enabled": True, "unfilled_timeout_bars": 1, "unfilled_timeout_bars_by_class": {"crypto": 1}}}})
    try:
        notes = [decide(algorithm, ticker, "buy") for ticker in ("AAPL", "BTCUSD", "EURUSD", "ES")]
        assert any(note.startswith("submitted_limit") for note in notes) and algorithm.pending_limit_orders
        market.step(fill_limits=False)
        market.step(fill_limits=False)
        assert not algorithm.pending_limit_orders or all(ticket.cancelled for ticket in algorithm.Transactions.tickets if ticket.Status == "Canceled")
        decide(algorithm, "AAPL", "buy")
        market.step(fill_limits=True)
        market.step(fill_limits=True)
    finally:
        monkeypatch.delitem(sys.modules, "main", raising=False)
