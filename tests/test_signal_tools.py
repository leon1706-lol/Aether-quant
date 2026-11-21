"""evaluation/signal_tools.py (V6.6.5, #345)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from evaluation.research_harness import evaluate_signal
from evaluation.signal_tools import forward_rank_targets, forward_returns, ic_decay, quantile_returns, validate_signal_frame


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


def test_a_signal_file_is_checked_for_errors_and_warnings_before_scoring():
    assert validate_signal_frame(pd.DataFrame({"date": ["2024-01-01"], "name": ["A"]}))["errors"] == ["missing column(s): ticker, score (a signal is date, ticker, score)"]
    good = pd.DataFrame({"date": ["2024-01-01", "2024-01-01", "2024-01-02", "2024-01-02"], "ticker": ["A", "B", "A", "B"], "score": [1.0, 2.0, 2.0, 1.0]})
    assert validate_signal_frame(good) == {"errors": [], "warnings": []}
    broken = pd.DataFrame({"date": ["2024-01-01", "not a date", "2024-01-02", "2024-01-02"], "ticker": ["A", "B", "A", "A"], "score": [1.0, np.inf, 2.0, 3.0]})
    errors = validate_signal_frame(broken)["errors"]
    assert errors[0].startswith("1 unparseable date(s), e.g. ['not a date']") and "share a (date, ticker)" in errors[1] and errors[2] == "1 score(s) are missing, NaN or infinite"
    unordered = pd.DataFrame({"date": ["2024-01-02", "2024-01-01", "2024-01-01"], "ticker": ["A", "A", "B"], "score": [1.0, 3.0, 3.0]})
    warnings = validate_signal_frame(unordered)["warnings"]
    assert warnings[0].startswith("rows are not in date order") and warnings[1].startswith("1 date(s) score fewer than 2 names") and warnings[2] == "the score never varies within a date: it ranks nothing"
