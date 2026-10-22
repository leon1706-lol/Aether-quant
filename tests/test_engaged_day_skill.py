"""V6.4.0 (lead L1): rank skill on the days the rolling-IC gate lets the book trade."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from evaluation.engaged_day_skill import (
    engaged_vs_all, engaged_window_returns, gate_labels, l1_verdict, sharpe, subset_skill,
)

DATES = [str(day.date()) for day in pd.bdate_range("2023-01-02", periods=60)]


def _frame(skill_on_even_days=True, seed=0):
    """30 names a day; the score carries information about the forward rank only on even-indexed days."""
    rng = np.random.default_rng(seed)
    rows = []
    for index, date in enumerate(DATES):
        informative = skill_on_even_days and index % 2 == 0
        for name in range(30):
            noise = rng.normal()
            score = noise
            target = noise * (1.0 if informative else 0.0) + rng.normal(0, 0.5 if informative else 1.0)
            rows.append({"date": date, "ticker": f"T{name:02d}", "live_rank_score": score, "forward": target})
    frame = pd.DataFrame(rows)
    frame["target_rank_20d"] = frame.groupby("date")["forward"].rank(pct=True)
    frame["target_return_20d"] = frame["forward"] * 0.01
    return frame


def _labels():
    return {date: index % 2 == 0 for index, date in enumerate(DATES)}


def test_gate_labels_read_the_engaged_flag():
    labels = gate_labels(lambda day: {"engaged": day.endswith("2")}, ["2023-01-02", "2023-01-03"])
    assert labels == {"2023-01-02": True, "2023-01-03": False}
    assert gate_labels(lambda day: None, ["2023-01-02"]) == {"2023-01-02": False}


def test_engaged_days_show_more_skill_when_the_gate_selects_them():
    result = engaged_vs_all(_frame(), _labels(), horizon=2, top_n=5, bottom_n=5)
    assert result["engaged_dates"] == 30 and result["vetoed_dates"] == 30
    assert result["engaged"]["daily_mean_ic"] > result["all"]["daily_mean_ic"] > result["vetoed"]["daily_mean_ic"]
    assert result["ic_margin"] > 0.2
    assert result["engaged"]["long_short_spread"] > result["vetoed"]["long_short_spread"]


def test_a_gate_that_selects_nothing_in_particular_has_no_margin():
    labels = {date: index % 3 == 0 for index, date in enumerate(DATES)}
    result = engaged_vs_all(_frame(skill_on_even_days=False, seed=4), labels, horizon=2, top_n=5, bottom_n=5)
    assert abs(result["ic_margin"]) < 0.1


def test_unlabelled_dates_count_as_vetoed():
    result = engaged_vs_all(_frame(), {}, horizon=2)
    assert result["engaged"] is None and result["vetoed_dates"] == len(DATES) and result["ic_margin"] is None


def test_non_overlapping_sample_keeps_dates_a_horizon_apart():
    frame = _frame()
    sampled = subset_skill(frame, None, DATES, score_column="live_rank_score", target_column="target_rank_20d",
                           forward_column="target_return_20d", top_n=5, bottom_n=5, horizon=20, min_names=10)
    assert sampled["non_overlapping_n"] == 3 and sampled["n_dates"] == 60


def test_window_returns_follow_the_latest_rebalance():
    returns = {"2023-01-02": 0.01, "2023-01-03": 0.02, "2023-01-04": -0.01, "2023-01-05": 0.03}
    log = [{"date": "2023-01-02", "engaged": True}, {"date": "2023-01-04", "engaged": False}]
    engaged, everything = engaged_window_returns(returns, log)
    assert engaged == [0.01, 0.02] and everything == list(returns.values())


def test_sharpe_needs_variation():
    assert sharpe([0.01] * 10) is None and sharpe([0.01, 0.02]) is None
    assert sharpe([0.01, -0.01, 0.02, 0.0]) == pytest.approx(np.mean([0.01, -0.01, 0.02, 0.0]) / np.std([0.01, -0.01, 0.02, 0.0], ddof=1) * np.sqrt(252))


def test_l1_needs_both_margins_on_both_splits():
    good = {"validation": {"ic_margin": 0.03, "sharpe_margin": 0.2}, "backtest": {"ic_margin": 0.025, "sharpe_margin": 0.16}}
    assert l1_verdict(good)["gate_protects_capital"] is True
    weak_sharpe = {**good, "backtest": {"ic_margin": 0.05, "sharpe_margin": 0.1}}
    verdict = l1_verdict(weak_sharpe)
    assert verdict["gate_protects_capital"] is False and "hides weakness" in verdict["reading"]
    assert l1_verdict({"validation": {"ic_margin": None, "sharpe_margin": 1.0}})["gate_protects_capital"] is False
    assert l1_verdict({})["gate_protects_capital"] is False
