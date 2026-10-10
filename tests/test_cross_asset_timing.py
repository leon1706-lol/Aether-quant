"""features/cross_asset_timing.py: the shared definition of what a cross-asset payload sees
(Problems.md #135), plus a LIVE-ORDER REPLAY proving train.py's offline builders reproduce
`main.py::_build_topology_payload()` / `_build_macro_payload()` / the cs_momentum_rank_20 read exactly.

Live builds those payloads at the start of a tick, before the tick's own bars join `symbol_windows`
(deque(maxlen=25)); a daily bar becomes visible at its period close (US equity: that day's close,
crypto/forex: the following midnight). The replay below is that loop, written independently of
`CrossAssetTimeline`.
"""

from __future__ import annotations

import math
from collections import deque

import numpy as np
import pandas as pd
import pytest

from features.cross_asset_timing import (
    WINDOW_BARS,
    CrossAssetTimeline,
    bar_available_at,
    cross_asset_inputs,
    momentum_from_closes,
    returns_from_closes,
)
from features.macro_features import credit_spread_proxy, crypto_risk_appetite_proxy, yield_curve_slope_proxy
from features.technical_indicators import cross_sectional_momentum_rank
from topology.market_topology import build_market_topology, resolve_elevated_volatility_thresholds
from train import (
    DEFAULT_MACRO_REFERENCE_TICKERS,
    build_cross_sectional_momentum_rank_features,
    build_macro_features_by_date,
    build_topology_features_by_date,
    peer_return_feature_names,
)

# ------------------------------------------------------------------ pure helpers


def test_equity_bar_is_available_at_its_close_and_crypto_forex_bars_at_the_next_midnight():
    assert bar_available_at(100, "equity") == 100.5
    assert bar_available_at(100, "crypto") == 101.0
    assert bar_available_at(100, "forex") == 101.0
    assert bar_available_at(100, "crypto") < bar_available_at(101, "equity")  # Sunday's crypto bar is visible Monday


def test_momentum_uses_the_bar_twenty_back_and_the_first_bar_on_short_history():
    closes = [100.0 + index for index in range(25)]
    assert momentum_from_closes(closes) == pytest.approx(closes[-1] / closes[4] - 1.0)
    assert momentum_from_closes([100.0, 110.0]) == pytest.approx(0.10)
    assert momentum_from_closes([100.0]) is None
    assert momentum_from_closes([0.0, 5.0]) is None


def test_non_finite_closes_never_leak_into_returns_or_momentum():
    assert returns_from_closes([100.0, float("nan"), 101.0, 102.0]) == [pytest.approx(102.0 / 101.0 - 1.0)]
    assert momentum_from_closes([100.0, float("nan")]) is None


def test_cross_asset_inputs_drops_symbols_without_usable_history():
    returns, momentum = cross_asset_inputs({"A": [100.0, 101.0, 102.0], "B": [100.0], "C": []})
    assert set(returns) == {"A"} and set(momentum) == {"A"}


def test_timeline_excludes_bars_of_its_own_tick_and_keeps_a_24_return_window():
    dates = pd.date_range("2020-01-01", periods=40, freq="D")
    frames = {"A": pd.DataFrame({"date": dates, "close": np.linspace(100, 140, 40)})}
    timeline = CrossAssetTimeline.from_frames(frames)
    key = timeline.row_availability("A", dates[30])
    windows = timeline.closes_before(key)
    assert len(windows["A"]) == WINDOW_BARS
    assert windows["A"][-1] == frames["A"]["close"].iloc[29]  # bar 30 itself is not visible to its own row


def test_monday_equity_row_sees_sundays_crypto_bar_but_the_crypto_row_never_sees_its_own_equity_peer_bar_early():
    saturday, sunday, monday = pd.Timestamp("2020-01-04"), pd.Timestamp("2020-01-05"), pd.Timestamp("2020-01-06")
    frames = {
        "BTCUSD": pd.DataFrame({"date": [saturday, sunday, monday], "close": [100.0, 101.0, 103.0]}),
        "SPY": pd.DataFrame({"date": [monday], "close": [300.0]}),
    }
    timeline = CrossAssetTimeline.from_frames(frames, {"BTCUSD": "crypto", "SPY": "equity"})
    assert timeline.closes_before(timeline.row_availability("SPY", monday))["BTCUSD"] == [100.0, 101.0]
    # Monday's crypto bar closes Tuesday 00:00: Monday's equity close is already visible to it
    assert timeline.closes_before(timeline.row_availability("BTCUSD", monday))["SPY"] == [300.0]


# ------------------------------------------------------------------ live-order replay parity

TOPOLOGY_PARAMS = dict(correlation_threshold=0.6, link_threshold=0.5, min_observations=5, embedding_iterations=1, top_peers_n=3)
# Low default cutoff so equities are often "elevated"; crypto's own cutoff is far above its volatility, so it never is.
ELEVATED_CONFIG = {"default": 0.20, "crypto": 5.0}


def _synthetic_universe(days: int = 70, seed: int = 11):
    rng = np.random.default_rng(seed)
    calendar = pd.date_range("2020-01-01", periods=days, freq="D")
    weekdays = calendar[calendar.dayofweek < 5]
    shared = rng.normal(0, 0.01, days)
    specs = {
        "TLT": ("equity", weekdays), "SHY": ("equity", weekdays), "HYG": ("equity", weekdays),
        "LQD": ("equity", weekdays), "AAPL": ("equity", weekdays), "MSFT": ("equity", weekdays[3:]),
        "BTCUSD": ("crypto", calendar), "EURUSD": ("forex", weekdays),
    }
    frames, types = {}, {}
    for index, (ticker, (security_type, dates)) in enumerate(specs.items()):
        noise = rng.normal(0, 0.015, len(dates))
        loading = 0.4 + 0.1 * index
        returns = noise + loading * shared[: len(dates)]
        frames[ticker] = pd.DataFrame({"date": dates, "close": 100.0 * np.cumprod(1.0 + returns)})
        types[ticker] = security_type
    return frames, types


def _live_replay(frames, types):
    """main.py's loop: payload from the windows BEFORE the tick, then the tick's bars join the windows."""
    bars = []  # (availability, ticker, date, close)
    for ticker, frame in frames.items():
        previous_stamp = None
        previous_close = None
        for stamp, close in zip(frame["date"], frame["close"]):
            if types[ticker] == "forex" and previous_stamp is not None:
                # Lean's FillForward: the forex market is open Sunday-Friday, so a gap day without a row is a flat bar
                for offset in range(1, (stamp - previous_stamp).days):
                    gap_day = previous_stamp + pd.Timedelta(days=offset)
                    if gap_day.dayofweek != 5:
                        bars.append((bar_available_at(gap_day.toordinal(), "forex"), ticker, gap_day, float(previous_close)))
            bars.append((bar_available_at(stamp.toordinal(), types[ticker]), ticker, stamp, float(close)))
            previous_stamp, previous_close = stamp, close
    windows = {ticker: deque(maxlen=WINDOW_BARS) for ticker in frames}
    live_default_threshold, live_threshold_by_symbol = resolve_elevated_volatility_thresholds(
        ELEVATED_CONFIG, {ticker: types[ticker] for ticker in frames}
    )
    rows = {}
    for availability in sorted({bar[0] for bar in bars}):
        tick = [bar for bar in bars if bar[0] == availability]
        returns_by_symbol, momentum_by_symbol = cross_asset_inputs({ticker: list(window) for ticker, window in windows.items()})
        topology = build_market_topology(
            returns_by_symbol=returns_by_symbol,
            elevated_volatility_threshold=live_default_threshold,
            elevated_volatility_threshold_by_symbol=live_threshold_by_symbol,
            **TOPOLOGY_PARAMS,
        )
        nodes = {node.symbol: node for node in topology.nodes}
        macro = (
            yield_curve_slope_proxy(momentum_by_symbol.get("TLT"), momentum_by_symbol.get("SHY")),
            credit_spread_proxy(momentum_by_symbol.get("HYG"), momentum_by_symbol.get("LQD")),
            crypto_risk_appetite_proxy(momentum_by_symbol.get("BTCUSD")),
        )
        for _, ticker, stamp, _close in tick:
            node = nodes.get(ticker)
            peers = list(node.top_peer_returns) if node else []
            rows[(ticker, stamp)] = {
                "strength": node.correlation_strength if node else 0.0,
                "risk": node.topology_risk if node else "isolated",
                "peers": peers + [0.0] * (3 - len(peers)) + [float(np.mean(peers)) if peers else 0.0],
                "macro": macro,
                "rank": cross_sectional_momentum_rank(momentum_by_symbol, ticker),
            }
        for _, ticker, _stamp, close in tick:
            windows[ticker].append(close)
    return rows


def test_offline_cross_asset_builders_reproduce_the_live_order_replay_exactly():
    frames, types = _synthetic_universe()
    expected = _live_replay(frames, types)

    timeline = CrossAssetTimeline.from_frames(frames, types)
    config = {
        "phase_v2": {"topology": {"min_observations": 5, "elevated_volatility_threshold": ELEVATED_CONFIG}},
        "phase1": {"universe": {"assets": [{"ticker": ticker, "security_type": types[ticker]} for ticker in frames]}},
    }
    assert DEFAULT_MACRO_REFERENCE_TICKERS["crypto"] == "BTCUSD"
    topology = build_topology_features_by_date(frames, config, timeline)
    macro = build_macro_features_by_date(frames, {}, timeline)
    rank = build_cross_sectional_momentum_rank_features(frames, timeline)

    checked = 0
    for ticker in frames:
        for index, stamp in enumerate(frames[ticker]["date"]):
            live = expected[(ticker, stamp)]
            row = topology[ticker].iloc[index]
            assert row["topology_correlation_strength"] == pytest.approx(live["strength"], abs=1e-12)
            assert row[f"topology_risk_{live['risk']}"] == 1.0
            for name, value in zip(peer_return_feature_names(3), live["peers"]):
                assert row[name] == pytest.approx(value, abs=1e-12)
            macro_row = macro[ticker].iloc[index]
            for name, value in zip(
                ("macro_yield_curve_slope_proxy", "macro_credit_spread_proxy", "macro_crypto_risk_appetite_proxy"), live["macro"]
            ):
                assert macro_row[name] == pytest.approx(value, abs=1e-12)
            assert rank[ticker].iloc[index]["cs_momentum_rank_20"] == pytest.approx(live["rank"], abs=1e-12)
            checked += 1
    assert checked > 300
    risks = {(ticker, stamp): row["risk"] for (ticker, stamp), row in expected.items()}
    assert any(risk == "elevated" for (ticker, _), risk in risks.items() if types[ticker] == "equity")
    assert not any(risk == "elevated" for (ticker, _), risk in risks.items() if types[ticker] == "crypto")
    assert any(not math.isclose(value["strength"], 0.0) for value in expected.values())  # the fixture really exercises topology


def test_the_old_same_day_alignment_would_not_pass_the_replay():
    """Guards the guard: an exact-date pool of same-day momentum (the pre-#135 offline rule) differs from the replay."""
    frames, types = _synthetic_universe()
    expected = _live_replay(frames, types)
    mismatches = 0
    for stamp in frames["AAPL"]["date"].iloc[21:]:
        same_day = {}
        for ticker, frame in frames.items():
            closes = frame.loc[frame["date"] <= stamp, "close"].tolist()[-WINDOW_BARS:]
            momentum = momentum_from_closes(closes)
            if momentum is not None:
                same_day[ticker] = momentum
        if cross_sectional_momentum_rank(same_day, "AAPL") != pytest.approx(expected[("AAPL", stamp)]["rank"], abs=1e-9):
            mismatches += 1
    assert mismatches >= 10


def test_forex_history_gets_lean_fill_forward_bars_for_every_open_gap_day_but_never_saturday():
    from features.cross_asset_timing import fill_forward_open_forex_days

    friday = pd.Timestamp("2019-05-17").toordinal()
    monday = friday + 3
    # Fri -> Mon: a Sunday bar appears (flat at Friday's close), Saturday stays closed
    assert fill_forward_open_forex_days([friday, monday], [1.10, 1.12]) == ([friday, friday + 2, monday], [1.10, 1.10, 1.12])
    # a missing weekday (the 2019-05-22 style gap) is filled, nothing is added after the last bar
    wednesday, friday2 = monday + 2, monday + 4
    ordinals, closes = fill_forward_open_forex_days([monday, wednesday, friday2], [1.0, 1.1, 1.2])
    assert ordinals == [monday, monday + 1, wednesday, wednesday + 1, friday2]
    assert closes == [1.0, 1.0, 1.1, 1.1, 1.2]
    assert fill_forward_open_forex_days([friday], [1.0]) == ([friday], [1.0])


def test_from_frames_fills_forex_only():
    dates = pd.to_datetime(["2019-05-17", "2019-05-20"])
    frames = {"EURUSD": pd.DataFrame({"date": dates, "close": [1.1, 1.2]}), "AAPL": pd.DataFrame({"date": dates, "close": [10.0, 11.0]})}
    timeline = CrossAssetTimeline.from_frames(frames, {"EURUSD": "forex", "AAPL": "equity"})
    after_monday_close = timeline.closes_before(timeline.row_availability("AAPL", pd.Timestamp("2019-05-21")))
    assert after_monday_close["EURUSD"] == [1.1, 1.1, 1.2]  # Friday, Sunday fill, Monday
    assert after_monday_close["AAPL"] == [10.0, 11.0]
