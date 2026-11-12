"""evaluation/signal_tools.py (V6.6.5, #345)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from evaluation.research_harness import evaluate_signal
from evaluation.signal_tools import forward_rank_targets, forward_returns, ic_decay, quantile_returns


def _prices(rows: int = 200, names: int = 12, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2024-01-01", periods=rows).strftime("%Y-%m-%d")
    return pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.01, (rows, names)), axis=0)), index=index, columns=[f"T{i}" for i in range(names)])


def test_forward_returns_look_ahead_exactly_h_rows():
    prices = _prices()
    future = forward_returns(prices, 5)
    assert math.isclose(future.iloc[0, 0], prices.iloc[5, 0] / prices.iloc[0, 0] - 1)
    assert future.iloc[-5:].isna().all().all()


def test_targets_feed_evaluate_signal_and_a_perfect_signal_scores_one():
    prices = _prices()
    targets = forward_rank_targets(prices, horizons=(5, 20))
    assert {"date", "ticker", "split", "target_return_1d", "target_rank_5d", "target_rank_20d"} <= set(targets.columns)
    targets["score"] = targets["target_rank_20d"]
    report = evaluate_signal(targets.dropna(subset=["target_rank_20d"]), score_column="score", splits=("validation",), min_names_per_date=5, bootstrap_draws=50)
    assert report["splits"]["validation"]["h20"]["mean_ic"] > 0.99


def test_quantile_returns_order_a_perfect_signal():
    prices = _prices()
    future = forward_returns(prices, 5)
    table = quantile_returns(future, future, n_quantiles=4).dropna()
    means = table.mean()
    assert list(means.index) == [1, 2, 3, 4] and means.is_monotonic_increasing


def test_ic_decay_is_one_at_its_own_horizon_and_nan_without_names():
    prices = _prices()
    decay = ic_decay(forward_returns(prices, 5), prices, horizons=(1, 5))
    assert math.isclose(decay[5], 1.0)
    assert math.isnan(ic_decay(prices.iloc[:, :2], prices.iloc[:, :2], horizons=(1,), min_names=3)[1])
