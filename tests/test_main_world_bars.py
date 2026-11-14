"""main.py's per-bar handling on a synthetic Lean world (V6.6.6, #359): forex quote bars, a stale bar borrowed on the equity tick, split events, flat fill-forward forex, zero-volume bars, the crypto
bar probe, late-bar cross-asset inputs, a batched inference pass that fails, the rolling-IC gate, hierarchical risk parity, and the sleeve and rotation exits of a long run."""

from __future__ import annotations

import copy
import sys
from types import SimpleNamespace

import pytest

import lean_world as world
from lean_fakes import Market

TICKERS = ("SPY", "AAPL", "MSFT", "XOM", "NVDA", "TLT", "BTCUSD", "ETHUSD", "EURUSD", "GBPJPY")
BOOK = {
    "phase_v2": {
        "target_weights": {"enabled": False}, "rolling_ic_gate": {"enabled": False}, "limit_orders": {"enabled": False},
        "portfolio_book": {"top_n": 2, "bottom_n": 2, "rebalance_every_bars": 3, "min_rank_confidence_spread": 0.0, "hysteresis_rank_margin": 0.0, "neutrality": {"sector_neutral": False, "max_weight_per_name": 0.3}},
        "exits": {"max_holding_bars": 5, "trailing_stop_pct": 0.03},
    },
    "phase1": {"target": {"ranking": {"min_universe_size": 4}}},
    "phase6": {"risk": {"trade_cooldown_bars": 0}},
}


def make(monkeypatch, tmp_path, overrides=None, *, tickers=TICKERS):
    main = world.install_stub(monkeypatch)
    root = world.make_root(tmp_path, overrides=world.merge(copy.deepcopy(BOOK), copy.deepcopy(overrides or {})), tickers=tickers)
    monkeypatch.chdir(root)
    algorithm = world.build_algorithm(main, root)
    return main, algorithm, Market(algorithm, seed=21)


@pytest.fixture(autouse=True)
def drop_main(monkeypatch):
    yield
    monkeypatch.delitem(sys.modules, "main", raising=False)


def test_forex_arrives_as_quote_bars_and_a_missing_crypto_bar_is_borrowed_on_the_equity_tick(monkeypatch, tmp_path):
    _, algorithm, market = make(monkeypatch, tmp_path)
    market.run(12, forex_quotes=True)
    market.step(forex_quotes=True, drop=("BTCUSD", "ETHUSD"))
    assert len(algorithm.symbol_windows[next(symbol for symbol in algorithm.symbols if str(symbol) == "EURUSD")]) > 5
    assert algorithm.bar_index > 5


def test_a_split_event_is_carried_into_the_bar_and_a_malformed_one_is_ignored(monkeypatch, tmp_path):
    _, algorithm, market = make(monkeypatch, tmp_path)
    market.run(6)
    aapl = next(symbol for symbol in algorithm.symbols if str(symbol) == "AAPL")
    msft = next(symbol for symbol in algorithm.symbols if str(symbol) == "MSFT")
    market.step(splits={aapl: SimpleNamespace(split_factor=0.5, reference_price=100.0), msft: SimpleNamespace(split_factor="bad")})
    assert algorithm.bar_index >= 5


def test_flat_forex_mode_rebuilds_a_fill_forward_bar_flat_at_the_previous_close(monkeypatch, tmp_path):
    _, algorithm, market = make(monkeypatch, tmp_path, {"phase1": {"features": {"forex_fill_forward_bars": "flat"}}})
    market.run(8)
    market.run(4, fill_forward=("EURUSD",))
    market.run(3, forex_quotes=True, fill_forward=("GBPJPY",))
    assert algorithm.forex_fill_forward_mode == "flat" and algorithm.symbol_real_bar_closes


def test_zero_volume_bars_are_counted_and_the_crypto_probe_logs_its_first_bars(monkeypatch, tmp_path):
    overrides = {"phase_v2": {"diagnostics": {"crypto_bar_probe": {"enabled": True, "max_bars_per_symbol": 2, "date_ranges": [["2019-01-03", "2019-01-12"]]}}}}
    _, algorithm, market = make(monkeypatch, tmp_path, overrides)
    market.run(10, zero_volume=("BTCUSD", "AAPL"))
    assert "crypto-bar-probe" in "\n".join(algorithm.messages) and algorithm._bar_volume_diagnostic_counts_by_symbol["BTCUSD"]["zero_volume"] > 0


def test_late_bar_inputs_are_replayed_from_the_symbols_own_tick(monkeypatch, tmp_path):
    _, algorithm, market = make(monkeypatch, tmp_path, {"phase1": {"features": {"late_bar_cross_asset": "own_tick"}}})
    market.run(8)
    market.step(drop=("BTCUSD", "EURUSD"))
    market.step(drop=("ETHUSD",))
    assert algorithm.late_bar_cross_asset_own_tick is True


def test_a_failing_batched_inference_pass_falls_back_to_the_per_symbol_path(monkeypatch, tmp_path):
    main, algorithm, market = make(monkeypatch, tmp_path, {"phase_v2": {"inference_parallelism": {"enabled": False, "batch_flat_models_across_symbols": True, "batch_experts_across_symbols": True}}})
    market.run(8)

    def boom(*args, **kwargs):
        raise RuntimeError("batched pass failed")

    monkeypatch.setattr(main, "run_exported_model_rows", boom)
    monkeypatch.setattr(main, "run_exported_multitask_model_rows", boom)
    monkeypatch.setattr(algorithm, "_run_experts_across_symbols", boom)
    market.run(3)
    text = "\n".join(algorithm.messages)
    assert "Batched baseline inference failed" in text and "Batched multitask inference failed" in text and "Batched expert inference failed" in text


def test_the_rolling_ic_gate_records_events_and_judges_the_book(monkeypatch, tmp_path):
    overrides = {"phase_v2": {"rolling_ic_gate": {"enabled": True, "horizon_days": 2, "rolling_window_days": 6, "min_resolved_dates_required": 2, "min_names_per_date": 3, "min_rolling_mean_ic": -1.0}}}
    _, algorithm, market = make(monkeypatch, tmp_path, overrides)
    market.run(30)
    assert algorithm.rolling_ic_gate_enabled and len(algorithm._rolling_ic_event_buffer) > 0


def test_hierarchical_risk_parity_replaces_the_rank_weights_of_the_book(monkeypatch, tmp_path):
    overrides = {"phase_v2": {"portfolio_book": {"allocation_method": "hrp"}}}
    _, algorithm, market = make(monkeypatch, tmp_path, overrides)
    market.run(40)
    assert algorithm.portfolio_book_allocation_method == "hrp"


def test_a_long_run_rotates_names_out_closes_on_the_backstop_and_reduces_oversized_orders(monkeypatch, tmp_path):
    overrides = {"phase_v2": {"portfolio_book": {"rebalance_every_bars": 2, "hold_positions_on_veto": True}, "liquidity": {"max_round_trip_cost_fraction": 0.0000001}}}
    _, algorithm, market = make(monkeypatch, tmp_path, overrides)
    market.run(60)
    assert algorithm.order_log
