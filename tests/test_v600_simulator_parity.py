"""V6.0.0 round file: the offline simulator learns the live execution details the Lean calibration found missing
(Problems.md #176): equity-session cadence on live's phase, next-open fills, the resize threshold, the entry cooldown,
the trailing stop, the per-order dollar floor, class slots, and a replay of live's gate decisions."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from evaluation.live_parity import NEXT_INTRADAY_RETURN_COLUMN, add_next_intraday_return, build_as_live_kwargs
from evaluation.rank_book_simulator import simulate_rank_book
from execution.cost_model import min_commission_usd_by_ticker


def _frame(num_tickers: int = 12, num_days: int = 30, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2024-01-02", periods=num_days)]
    rows = []
    for day_index, date in enumerate(dates):
        for index in range(num_tickers):
            skill = (index - num_tickers / 2) / num_tickers
            close = 100.0 * (1 + 0.01 * day_index * skill)
            rows.append({
                "date": date, "ticker": f"T{index}", "pred": skill + rng.normal(0, 0.05),
                "target_return_1d": skill * 0.002 + rng.normal(0, 0.002),
                "open": close * 0.999, "close": close,
            })
    return pd.DataFrame(rows)


def _kwargs(**overrides):
    kwargs = dict(
        prediction_column="pred", forward_return_column="target_return_1d", ticker_column="ticker", date_column="date",
        top_n=3, bottom_n=3, rebalance_every_bars=5, cost_bps_per_side=0.0, commission_bps=0.0, gross_exposure=1.0,
        dollar_neutral=True, sector_neutral=False, max_weight_per_name=0.5, min_universe_size=5,
    )
    kwargs.update(overrides)
    return kwargs


def test_new_options_default_to_the_old_result():
    frame = _frame()
    old = simulate_rank_book(frame, **_kwargs())
    new = simulate_rank_book(frame, **_kwargs(rebalance_counter_start=0, resize_threshold_weight=0.0, trade_cooldown_dates=0))
    assert old.per_date_net_return == new.per_date_net_return
    assert [entry["date"] for entry in new.rebalance_log] == new.per_date[::5]


def test_cadence_counts_only_session_dates_and_starts_on_the_live_phase():
    frame = _frame()
    dates = sorted(frame["date"].unique())
    holiday = dates[2]
    sessions = set(dates) - {holiday}
    result = simulate_rank_book(frame, **_kwargs(rebalance_session_dates=sessions, rebalance_counter_start=3))
    rebalanced = [entry["date"] for entry in result.rebalance_log]
    assert holiday not in rebalanced
    ordered_sessions = [date for date in dates if date in sessions]
    assert rebalanced[0] == ordered_sessions[2]  # counter 3 reaches the next multiple of 5 after two sessions
    assert rebalanced[1] == ordered_sessions[7]
    assert len(result.per_date) == len(dates)  # returns still accrue on the holiday


def test_next_open_fills_give_the_next_intraday_move_to_the_new_weights():
    frame = add_next_intraday_return(_frame())
    plain = simulate_rank_book(frame, **_kwargs(entry_lag_bars=1, log_weights=True))
    opened = simulate_rank_book(frame, **_kwargs(entry_lag_bars=1, intraday_next_return_column=NEXT_INTRADAY_RETURN_COLUMN))
    first = plain.per_date[0]
    intraday = frame[frame["date"] == first].set_index("ticker")[NEXT_INTRADAY_RETURN_COLUMN]
    expected = sum(weight * intraday[ticker] for ticker, weight in plain.weights_log[0].items())
    assert opened.per_date_net_return[0] - plain.per_date_net_return[0] == pytest.approx(expected)


def test_add_next_intraday_return_reads_the_same_tickers_next_session():
    frame = pd.DataFrame({"date": ["2024-01-03", "2024-01-02", "2024-01-02"], "ticker": ["A", "A", "B"],
                          "open": [10.0, 9.0, 5.0], "close": [11.0, 9.5, 5.5]})
    add_next_intraday_return(frame)
    assert frame.loc[1, NEXT_INTRADAY_RETURN_COLUMN] == pytest.approx(0.1)
    assert np.isnan(frame.loc[0, NEXT_INTRADAY_RETURN_COLUMN]) and np.isnan(frame.loc[2, NEXT_INTRADAY_RETURN_COLUMN])


def test_a_trivial_resize_is_not_traded():
    frame = _frame()
    loose = simulate_rank_book(frame, **_kwargs(live_weighting=True, normalize_to_percentile=True, rebalance_every_bars=1))
    tight = simulate_rank_book(frame, **_kwargs(live_weighting=True, normalize_to_percentile=True, rebalance_every_bars=1,
                                                resize_threshold_weight=0.5))
    assert tight.annualized_turnover < loose.annualized_turnover


def test_the_cooldown_blocks_a_flip_of_a_recently_traded_name():
    frame = _frame(num_days=12)
    # every prediction flips after day 3: the free book turns its longs short, the cooled-down book keeps them long
    late = frame["date"] >= sorted(frame["date"].unique())[3]
    frame.loc[late, "pred"] = -frame.loc[late, "pred"]
    free = simulate_rank_book(frame, **_kwargs(rebalance_every_bars=1, log_weights=True))
    blocked = simulate_rank_book(frame, **_kwargs(rebalance_every_bars=1, trade_cooldown_dates=100, log_weights=True))
    flipped = [name for name, weight in free.weights_log[0].items() if weight > 0 and free.weights_log[5].get(name, 0.0) < 0]
    assert flipped
    for name in flipped:
        assert blocked.weights_log[5].get(name, 0.0) > 0  # live: a signal change inside the cooldown is not traded


def test_the_trailing_stop_closes_a_long_after_a_drawdown_from_its_peak():
    frame = _frame(num_days=10)
    top = frame.loc[frame["date"] == frame["date"].min()].sort_values("pred").iloc[-1]["ticker"]
    dates = sorted(frame["date"].unique())
    frame.loc[(frame["ticker"] == top) & (frame["date"] >= dates[4]), "close"] = 50.0
    result = simulate_rank_book(frame, **_kwargs(rebalance_every_bars=100, trailing_stop_pct=0.15, log_weights=True))
    assert top in result.weights_log[3]
    assert top not in result.weights_log[4]


def test_replayed_decisions_set_the_rebalance_dates_and_states():
    frame = _frame()
    dates = sorted(frame["date"].unique())
    overrides = {dates[1]: "engaged", dates[4]: "vetoed", dates[9]: "locked"}
    result = simulate_rank_book(frame, **_kwargs(decision_overrides=overrides, hold_positions_on_veto=True))
    log = {entry["date"]: entry for entry in result.rebalance_log}
    assert set(log) == set(overrides)
    assert log[dates[1]]["engaged"] and not log[dates[4]]["engaged"]
    assert log[dates[9]]["engaged"] and log[dates[9]]["locked"]


def test_class_slots_and_floors_reach_the_simulator():
    kwargs = build_as_live_kwargs(
        _kwargs(), book_config={"per_asset_class_slots": {"equity": [2, 2], "bad": [1]}}, exits_config={"enabled": True,
        "trailing_stop_pct": 0.15}, max_position_weight=0.12, candidate_metadata={}, next_open_fills=True,
        resize_threshold_weight=0.03, trade_cooldown_bars=10,
    )
    assert kwargs["per_asset_class_slots"] == {"equity": (2, 2)}
    assert kwargs["intraday_next_return_column"] == NEXT_INTRADAY_RETURN_COLUMN
    assert (kwargs["resize_threshold_weight"], kwargs["trade_cooldown_dates"], kwargs["trailing_stop_pct"]) == (0.03, 10, 0.15)
    costs = {"min_commission_usd": 1.0, "fee_by_type": {"crypto": {"fee_bps": 80.0, "min_usd": 0.0},
                                                         "forex": {"fee_bps": 0.2, "min_usd": 2.0}}}
    assert min_commission_usd_by_ticker(costs, {"AAPL": "equity", "BTCUSD": "crypto", "EURUSD": "forex"}) == {"AAPL": 1.0, "EURUSD": 2.0}


def test_the_simulators_rebalance_dates_are_the_ones_live_s_cadence_function_picks():
    from portfolio.book_construction import should_rebalance_this_bar

    frame = _frame(num_days=40)
    dates = sorted(frame["date"].unique())
    sessions = {date for index, date in enumerate(dates) if index % 7 != 3}  # equity holidays in between
    result = simulate_rank_book(frame, **_kwargs(rebalance_every_bars=5, rebalance_session_dates=sessions))
    ordered_sessions = [date for date in dates if date in sessions]
    live_dates = [
        date for bar_index, date in enumerate(ordered_sessions, start=1)
        if should_rebalance_this_bar(bar_index, 5, has_previous_allocation=True, is_trading_day_bar=True)
    ]
    assert [entry["date"] for entry in result.rebalance_log] == live_dates
