"""evaluation/lean_benchmarks.py: every series on one calendar and one formula; a missing benchmark is left out, not faked."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from evaluation.lean_benchmarks import benchmark_rows, series_row


def test_series_row_computes_return_volatility_sharpe_and_drawdown():
    returns = pd.Series([0.10, -0.20, 0.05, 0.05])
    row = series_row("x", returns, periods_per_year=4)
    assert row["total_return"] == pytest.approx(1.10 * 0.80 * 1.05 * 1.05 - 1.0)
    assert row["annual_return"] == pytest.approx(row["total_return"])
    assert row["max_drawdown"] == pytest.approx(0.20)
    assert row["volatility"] == pytest.approx(returns.std(ddof=1) * 2.0)
    assert row["sharpe"] == pytest.approx(returns.mean() / returns.std(ddof=1) * 2.0)


def test_a_first_day_loss_counts_as_drawdown_from_the_start():
    assert series_row("x", pd.Series([-0.10, 0.01]))["max_drawdown"] == pytest.approx(0.10)


def test_a_flat_or_empty_series_never_raises_or_divides_by_zero():
    assert series_row("x", pd.Series([], dtype=float))["sharpe"] is None
    flat = series_row("x", pd.Series([0.0, 0.0, 0.0]))
    assert flat["sharpe"] is None and flat["max_drawdown"] == 0.0 and math.isfinite(flat["total_return"])


def _benchmarks() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    index = [f"2024-01-{day:02d}" for day in range(1, 21)]
    return pd.DataFrame(rng.normal(0, 0.01, size=(20, 5)), index=index, columns=["SPY", "AGG", "BTCUSD", "ETHUSD", "XRPUSD"])


def test_rows_cover_the_run_the_benchmarks_and_the_coins_it_traded_on_shared_sessions():
    table = _benchmarks()
    portfolio = pd.Series(0.001, index=table.index[:15])
    rows = benchmark_rows(portfolio, portfolio * 0.5, table, ["BTCUSD", "ETHUSD", "NOTHERE"])
    assert [row["series"] for row in rows] == [
        "**Portfolio** (with the T-bill sweep)", "**Strategy** (without the sweep)", "SPY", "60/40 SPY/AGG, rebalanced daily",
        "Bitcoin, buy and hold", "The book's 2 coins, equal weight",
    ]
    expected = (1.0 + table["SPY"].iloc[:15]).prod() - 1.0  # only the sessions the run covers
    assert rows[2]["total_return"] == pytest.approx(expected)


def test_a_benchmark_outside_the_universe_is_left_out():
    table = _benchmarks().drop(columns=["AGG", "BTCUSD"])
    rows = benchmark_rows(pd.Series(0.001, index=table.index), pd.Series(dtype=float), table, ["ETHUSD"])
    assert [row["series"] for row in rows] == ["**Portfolio** (with the T-bill sweep)", "SPY"]


def test_no_shared_sessions_gives_no_rows():
    assert benchmark_rows(pd.Series(0.001, index=["1999-01-01"]), pd.Series(dtype=float), _benchmarks(), []) == []
