"""V6.0.0 (todo lead 5): a crypto/forex symbol re-scored on the equity tick uses the cross-asset payloads of its own tick."""

from __future__ import annotations

import numpy as np
import pandas as pd

from evaluation.live_parity import (
    LATE_BAR_SAME_ROW_FEATURE_PREFIXES,
    late_bar_offline_row,
    late_bar_same_row_prefixes,
)
from features.cross_asset_timing import CrossAssetTimeline, LateBarCrossAssetCache, is_late_bar_asset


def _frames(days: int = 40, seed: int = 5):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-02", periods=days)
    frames = {}
    for ticker in ("AAA", "BBB", "BTCUSD", "ETHUSD"):
        closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, days)))
        frames[ticker] = pd.DataFrame({"date": dates, "close": closes})
    return frames, dates


def test_late_bar_asset_classes():
    assert is_late_bar_asset("crypto") and is_late_bar_asset("forex")
    assert not is_late_bar_asset("equity") and not is_late_bar_asset(None)


def test_the_cache_hands_back_what_the_symbol_had_at_its_own_tick_and_nothing_before_it():
    cache = LateBarCrossAssetCache()
    assert cache.lookup("BTCUSD") is None
    node, momentum = {"symbol": "BTCUSD", "correlation_strength": 0.4}, {"BTCUSD": 0.1}
    cache.record("BTCUSD", None, momentum)  # a symbol without a topology node records nothing
    assert cache.lookup("BTCUSD") is None
    cache.record("BTCUSD", node, momentum)
    assert cache.lookup("BTCUSD") == (node, momentum)
    cache.record("BTCUSD", {"symbol": "BTCUSD", "correlation_strength": 0.9}, {"BTCUSD": 0.3})
    assert cache.lookup("BTCUSD")[0]["correlation_strength"] == 0.9  # each own tick replaces the entry


def test_the_equity_tick_payload_differs_from_the_own_tick_one_that_the_dataset_row_holds():
    frames, dates = _frames()
    timeline = CrossAssetTimeline.from_frames(frames, {"AAA": "equity", "BBB": "equity", "BTCUSD": "crypto", "ETHUSD": "crypto"})
    day = dates[30]
    row_key = timeline.row_availability("BTCUSD", day)  # the dataset row of the crypto bar of `day`
    own_tick_returns, own_tick_momentum = timeline.inputs_before(row_key)
    equity_tick_key = timeline.row_availability("AAA", dates[31])  # the next equity tick, one crypto bar later
    fresh_returns, fresh_momentum = timeline.inputs_before(equity_tick_key)
    # one crypto bar later: the 24-return window has slid by a bar
    assert fresh_returns["BTCUSD"][:-1] == own_tick_returns["BTCUSD"][1:] and fresh_returns["BTCUSD"] != own_tick_returns["BTCUSD"]
    assert fresh_momentum["BTCUSD"] != own_tick_momentum["BTCUSD"]
    cache = LateBarCrossAssetCache()
    cache.record("BTCUSD", {"top_peer_returns": own_tick_returns["ETHUSD"][-3:]}, own_tick_momentum)
    _node, cached_momentum = cache.lookup("BTCUSD")
    assert cached_momentum == own_tick_momentum  # what the equity tick feeds the model instead of `fresh_momentum`


def test_the_reconciler_reads_the_payload_features_from_the_previous_row_in_own_tick_mode():
    assert late_bar_same_row_prefixes({}) == LATE_BAR_SAME_ROW_FEATURE_PREFIXES
    own_tick = late_bar_same_row_prefixes({"phase1": {"features": {"late_bar_cross_asset": "own_tick"}}})
    assert "topology_" not in own_tick and "peer_" not in own_tick and "cs_momentum_rank" not in own_tick
    assert "alt_" in own_tick and "bond_yield_curve" in own_tick
    previous = {"topology_correlation_strength": 0.1, "alt_vix": 1.0, "close_to_close_return_1d": 0.01}
    same = {"topology_correlation_strength": 0.9, "alt_vix": 2.0, "close_to_close_return_1d": 0.5}
    assert late_bar_offline_row(previous, same)["topology_correlation_strength"] == 0.9
    merged = late_bar_offline_row(previous, same, own_tick)
    assert merged["topology_correlation_strength"] == 0.1 and merged["alt_vix"] == 2.0 and merged["close_to_close_return_1d"] == 0.01


def test_forex_monday_compares_only_the_payload_block_and_carry_reads_the_ticks_row():
    from evaluation.live_parity import forex_monday_payload_only

    prefixes = late_bar_same_row_prefixes({"phase1": {"features": {"late_bar_cross_asset": "own_tick"}}})
    assert "fx_carry" in prefixes
    previous = {"fx_carry_3m": -1.18, "macd_histogram_norm": 0.1, "alt_vix": 1.0}
    same = {"fx_carry_3m": -1.29, "macd_histogram_norm": 0.9, "alt_vix": 2.0}
    merged = late_bar_offline_row(previous, same, prefixes)
    assert merged["fx_carry_3m"] == -1.29 and merged["macd_histogram_norm"] == 0.1
    assert forex_monday_payload_only(merged, prefixes) == {"fx_carry_3m": -1.29, "alt_vix": 2.0}  # no own-price block on a Monday
    assert forex_monday_payload_only(None, prefixes) is None
