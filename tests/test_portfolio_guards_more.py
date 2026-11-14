"""Small guards across portfolio/ (V6.6.6, #359): garbage config numbers, odd calibrations, singular fits and thin or empty selections."""

from __future__ import annotations

import datetime as dt
import random

import numpy as np
import pandas as pd

from portfolio import cash_sweep, class_sleeve, direction_overlay, hrp_allocation, neutrality, options_arbitrage_detector as arbitrage, rank_signal, signal_construction, sleeve_guard, wide_signals
from test_options_strategy_selectors import _pool


def test_config_numbers_that_are_not_numbers_fall_back():
    assert cash_sweep._finite("x", 3.0) == 3.0 and cash_sweep._finite(float("inf"), 1.0) == 1.0
    assert class_sleeve.resolve_class_sleeve_config("bond", {"enabled": True, "max_weight_per_name": "abc"}).max_weight_per_name is None
    assert sleeve_guard.resolve_sleeve_guard_config({"enabled": True, "max_gross": "abc"}) is not None


def test_a_resize_on_garbage_is_not_traded():
    assert class_sleeve.resize_below_minimum("x", 10.0, 5.0) is True
    assert class_sleeve.resize_below_minimum(1.0, 10.0, 0.0) is False


def test_an_unknown_calibration_leaves_the_probability_alone():
    assert direction_overlay.calibrate_probability(0.3, {"method": "mystery"}) == 0.3


def test_hrp_falls_back_when_a_leg_has_no_return_history():
    rng = np.random.default_rng(0)
    returns = {name: list(rng.normal(0, 0.01, 50)) for name in ("A", "B", "D", "E")}
    both_short_missing = hrp_allocation.build_hrp_allocation(returns, selected_tickers_long=["A", "B"], selected_tickers_short=["C"], gross_exposure=1.0)
    assert both_short_missing["C"] == -0.5
    long_missing = hrp_allocation.build_hrp_allocation(returns, selected_tickers_long=["X"], selected_tickers_short=["D", "E"], gross_exposure=1.0)
    assert long_missing["X"] == 0.5
    assert hrp_allocation.build_hrp_allocation(returns, selected_tickers_long=[], selected_tickers_short=[]) == {}


def test_a_cluster_with_no_variance_splits_evenly(monkeypatch):
    rng = np.random.default_rng(1)
    frame = pd.DataFrame(rng.normal(size=(50, 4)), columns=list("ABCD"))
    monkeypatch.setattr(hrp_allocation, "_cluster_var", lambda returns, tickers: 0.0)
    assert abs(hrp_allocation.compute_hrp_weights(frame).sum() - 1.0) < 1e-9


def test_neutralising_nothing_or_a_singular_fit_returns_the_weights():
    weights = pd.Series({"A": 0.5, "B": -0.5})
    assert neutrality.factor_neutralize(weights, pd.DataFrame({"f": [np.nan, np.nan]}, index=["A", "B"])).equals(weights)
    duplicated = pd.DataFrame({"f": [1.0, 1.0], "g": [1.0, 1.0]}, index=["A", "B"])
    assert neutrality.factor_neutralize(weights, duplicated, ridge=0.0).equals(weights)


def test_arbitrage_signals_need_priced_legs_and_a_registered_strategy(monkeypatch):
    chain = _pool(random.Random(7))
    stripped = [{key: value for key, value in row.items() if key not in ("bid", "ask")} for row in chain]
    assert arbitrage.select_arbitrage_signal("conversion", stripped, dt.date(2026, 11, 13), 0.05, 1.0) is False
    monkeypatch.setattr(arbitrage, "select_arbitrage_signal", lambda *args, **kwargs: True)
    assert arbitrage.build_arbitrage_position_sizing("nonexistent", chain, dt.date(2026, 11, 13), 0.05, 1.0) is None
    monkeypatch.setattr(arbitrage, "select_strategy_legs", lambda *args, **kwargs: None)
    assert arbitrage.build_arbitrage_position_sizing("box_spread", chain, dt.date(2026, 11, 13), 0.05, 1.0) is None


def test_sector_relative_scoring_of_nothing_and_a_grouped_sector_split():
    assert rank_signal.sector_relative_scores({}, {"A": "x"}) == {}
    scores = {"A": 0.9, "B": 0.1, "C": 0.5, "D": 0.4}
    ranks = rank_signal.grouped_cross_sectional_rank_scores(scores, {"A": "main", "B": "main", "C": "bond", "D": "bond"}, {"A": "s", "B": "s", "C": "t", "D": "t"}, min_sector_size=1)
    assert set(ranks) == set(scores)


def test_a_single_recipe_with_two_parts_is_refused():
    import pytest

    table = pd.DataFrame({"A": [1.0]}, index=["2025-01-02"])
    with pytest.raises(ValueError, match="one part"):
        signal_construction.build_table({"op": "single", "parts": ["x", "y"]}, {"x": table, "y": table})


def test_an_empty_signal_has_no_live_names():
    assert wide_signals.live_names_per_rebalance(pd.DataFrame(columns=["A"]), 5) == {"median": 0.0, "minimum": 0.0}
