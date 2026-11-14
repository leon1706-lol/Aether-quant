"""The legacy probability sleeve inside the offline rank-book simulator (V6.6.6, #359): `_legacy_step`'s exits, skips, cooldown and cost floor, and the two helpers that mark its positions on non-trading dates and
earn the next open-to-close move."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from evaluation import rank_book_simulator as sim
from portfolio.legacy_sleeve import resolve_legacy_sleeve_config

SIGNAL = {"decision_threshold": 0.5, "buy_threshold": 0.6, "sell_threshold": 0.4, "max_position_weight": 0.05, "band_enabled": False, "band_min_observations": 10, "band_percentile": 0.2, "band_window": 20}


def component(**changes):
    base = {"signal": SIGNAL, "sleeve_config": resolve_legacy_sleeve_config({"enabled": True, "max_gross_exposure": 0.5, "max_weight_per_name": 0.05}), "probability_column": "p",
            "asset_classes": ("equity",), "weight_fn": None, "max_holding_dates": None, "trailing_stop_pct": None}
    return {**base, **changes}


def step(state, rows, **overrides):
    eligible = pd.DataFrame(rows)
    meta = {ticker: {"asset_class": "equity", "trading_eligible": True} for ticker in eligible["ticker"]}
    kwargs = dict(eligible=eligible, date="2020-01-10", date_index=10, is_session=True, ticker_column="ticker", close_column="close", book_members=set(), book_held={}, book_active=True,
                  kill_switch_locked=False, candidate_metadata_by_ticker=meta, cost_bps=5.0, commission_override=lambda symbol: 1.0, min_commission_usd_by_ticker=None, pv_for_costs=100_000.0,
                  max_active_positions=None, cooldown_dates=0, resize_threshold_weight=0.0)
    comp = overrides.pop("component", component())
    kwargs.update(overrides)
    return sim._legacy_step(state, comp, **kwargs)


def test_without_a_probability_column_the_sleeve_does_nothing():
    state = sim._new_legacy_state()
    assert step(state, {"ticker": ["A"], "close": [10.0]}) == (0.0, 0.0) and state["weights"] == {}


def test_a_high_probability_opens_a_capped_position_and_pays_cost_and_a_commission_floor():
    state = sim._new_legacy_state()
    cost, turnover = step(state, {"ticker": ["A"], "close": [10.0], "p": [0.9]}, min_commission_usd_by_ticker={"A": 5.0})
    assert state["weights"] == {"A": pytest.approx(0.05)} and turnover == pytest.approx(0.05) and state["entry_index"] == {"A": 10}
    assert cost == pytest.approx(0.05 * 6.0 / 1e4 + max(0.0, 5.0 - 0.05 * 100_000.0 * 5.0 / 1e4) / 100_000.0)


def test_a_low_probability_closes_a_held_position_and_forgets_it_and_a_sell_with_nothing_held_does_nothing():
    state = sim._new_legacy_state()
    state.update(weights={"A": 0.04}, entry_index={"A": 3}, peak={"A": 12.0})
    cost, turnover = step(state, {"ticker": ["A", "B"], "close": [10.0, 10.0], "p": [0.1, 0.1]})
    assert state["weights"] == {} and turnover == pytest.approx(0.04) and "A" not in state["entry_index"] and "A" not in state["peak"] and cost > 0.0


def test_an_age_exit_removes_a_position_and_a_missing_price_or_probability_skips_the_name():
    state = sim._new_legacy_state()
    state.update(weights={"A": 0.04, "B": 0.04, "C": 0.04}, entry_index={"A": 0, "B": 0, "C": 9}, peak={"C": 10.0})
    rows = {"ticker": ["A", "B", "C"], "close": [10.0, float("nan"), 10.0], "p": [float("nan"), 0.5, 0.5]}
    step(state, rows, component=component(max_holding_dates=3))
    assert set(state["weights"]) == {"B", "C"}


def test_a_name_outside_the_sleeve_classes_or_already_held_by_the_book_is_not_traded():
    state = sim._new_legacy_state()
    meta = {"A": {"asset_class": "crypto", "trading_eligible": True}, "B": {"asset_class": "equity", "trading_eligible": False}, "C": {"asset_class": "equity", "trading_eligible": True}}
    step(state, {"ticker": ["A", "B", "C"], "close": [10.0] * 3, "p": [0.9] * 3}, candidate_metadata_by_ticker=meta, book_held={"C": 0.05})
    assert state["weights"] == {}


def test_a_resize_to_the_weight_already_held_a_cooldown_and_the_position_cap_each_leave_the_book_alone():
    held = sim._new_legacy_state()
    held["weights"] = {"A": 0.05}
    step(held, {"ticker": ["A"], "close": [10.0], "p": [0.9]}, component=component(weight_fn=lambda **kwargs: kwargs["held_weight"]))
    assert held["weights"] == {"A": 0.05}
    cooling = sim._new_legacy_state()
    cooling["last_trade"] = {"A": 9}
    step(cooling, {"ticker": ["A"], "close": [10.0], "p": [0.9]}, cooldown_dates=5)
    assert cooling["weights"] == {}
    capped = sim._new_legacy_state()
    step(capped, {"ticker": ["A"], "close": [10.0], "p": [0.9]}, max_active_positions=1, book_held={"X": 0.1})
    assert capped["weights"] == {}


def test_the_lock_blocks_new_entries_and_a_non_session_date_only_records_the_signal():
    locked = sim._new_legacy_state()
    step(locked, {"ticker": ["A"], "close": [10.0], "p": [0.9]}, kill_switch_locked=True)
    assert locked["weights"] == {}
    weekend = sim._new_legacy_state()
    step(weekend, {"ticker": ["A"], "close": [10.0], "p": [0.9]}, is_session=False)
    assert weekend["weights"] == {} and weekend["band"]["A"] == [0.9]


def test_legacy_positions_are_marked_on_a_date_that_is_not_traded_and_earn_the_next_open_to_close_move():
    state = sim._new_legacy_state()
    assert sim._legacy_mark(state, {"A": 0.1}) == 0.0
    state["history"].append({"A": 0.5, "B": 0.5})
    assert sim._legacy_mark(state, {"A": 0.02}) == pytest.approx(0.01)
    state.update(weights={"A": 0.5, "B": 0.2, "C": 0.1}, previous={"A": 0.5, "B": 0.0, "D": 0.3})
    eligible = pd.DataFrame({"ticker": ["A", "B", "C", "D"], "intraday": [0.05, 0.01, float("nan"), -0.02]})
    assert sim._legacy_intraday(state, eligible, "ticker", "intraday") == pytest.approx(0.2 * 0.01 + 0.3 * 0.02)
    assert sim._annualized_sharpe(np.array([0.01]), 252) == 0.0


def test_a_trailing_stop_closes_only_a_position_that_fell_far_enough_from_its_peak():
    state = sim._new_legacy_state()
    state.update(weights={"A": 0.04, "B": 0.04}, entry_index={"A": 9, "B": 9}, peak={"A": 20.0, "B": 10.5})
    step(state, {"ticker": ["A", "B"], "close": [10.0, 10.0], "p": [0.5, 0.5]}, component=component(trailing_stop_pct=0.10))
    assert set(state["weights"]) == {"B"} and state["peak"]["B"] == 10.5


def test_no_exit_rule_means_no_exit_whatever_the_drawdown():
    state = sim._new_legacy_state()
    state.update(weights={"A": 0.04}, entry_index={"A": 0}, peak={"A": 20.0})
    step(state, {"ticker": ["A"], "close": [10.0], "p": [0.5]})
    assert state["weights"] == {"A": 0.04}


# ---- inside the full simulation ---------------------------------------------------------------------------------------


from test_rank_book_simulator import _base_kwargs, _synthetic_frame  # noqa: E402


def test_a_date_too_thin_to_rank_still_earns_the_held_book_and_the_kill_switch_equity_follows():
    frame = _synthetic_frame(num_tickers=20, num_days=60)
    thin_dates = sorted(frame["date"].unique())[20:24]
    frame = frame[~(frame["date"].isin(thin_dates) & (frame["ticker"] != "T0"))].reset_index(drop=True)
    kill_switch = {"enabled": True, "evaluation_bars": 2, "min_rolling_sharpe": 1e9, "min_return_std_for_sharpe": 0.0}
    plain = sim.simulate_rank_book(frame, **_base_kwargs(entry_lag_bars=1, accrue_skipped_dates=True))
    locked = sim.simulate_rank_book(frame, **_base_kwargs(entry_lag_bars=1, accrue_skipped_dates=True, kill_switch_config=kill_switch, kill_switch_sticky=True))
    ignoring = sim.simulate_rank_book(frame, **_base_kwargs(entry_lag_bars=1))
    assert plain.per_date_net_return != ignoring.per_date_net_return and locked.num_kill_switch_locked_dates > 0


def test_a_trailing_stop_skips_a_held_name_with_no_close_that_day():
    frame = _synthetic_frame(num_tickers=20, num_days=40)
    frame["close"] = 100.0
    frame.loc[frame["date"] == sorted(frame["date"].unique())[8], "close"] = float("nan")
    result = sim.simulate_rank_book(frame, **_base_kwargs(close_column="close", trailing_stop_pct=0.5, rebalance_every_bars=3))
    assert result.num_dates_used > 0


def test_the_legacy_sleeve_earns_the_next_open_to_close_move_of_what_it_traded_when_orders_fill_at_the_next_open():
    frame = _synthetic_frame(num_tickers=20, num_days=60)
    frame["p"] = np.where(frame["pred"] > 0.0, 0.9, 0.1)
    frame["close"] = 100.0
    frame["intraday"] = 0.001
    meta = {ticker: {"asset_class": "equity", "trading_eligible": True} for ticker in frame["ticker"].unique()}
    comp = component(weight_fn=None)
    plain = sim.simulate_rank_book(frame, **_base_kwargs(entry_lag_bars=1, legacy_component=comp, candidate_metadata_by_ticker=meta, close_column="close"))
    with_intraday = sim.simulate_rank_book(frame, **_base_kwargs(entry_lag_bars=1, legacy_component=comp, candidate_metadata_by_ticker=meta, close_column="close", intraday_next_return_column="intraday"))
    assert plain.per_date_net_return != with_intraday.per_date_net_return


def test_capacity_is_estimated_from_a_run_the_sweep_did_not_include_and_is_zero_when_nothing_is_held():
    frame = _synthetic_frame()
    estimate = sim.capacity_curve(frame, participation_cap=0.01, base_kwargs=_base_kwargs(), top_n_sweep=[2])
    assert estimate["capacity_usd"] > 0.0 and estimate["binding_ticker"] is not None
    nothing = sim.capacity_curve(frame, participation_cap=0.01, base_kwargs=_base_kwargs(min_universe_size=10_000), top_n_sweep=[4])
    assert nothing == {"capacity_usd": 0.0, "binding_ticker": None, "per_top_n": nothing["per_top_n"]}
