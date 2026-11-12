"""evaluation/backtest_api.py (V6.6.5, #345): the general backtest, held to the target-weights simulator's returns."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from evaluation.backtest_api import BacktestResult, backtest, summary_statistics
from evaluation.target_weights_engine import MarketPanel, simulate_target_weights
from execution.cost_models import LinearCostModel, SquareRootImpactModel
from portfolio.target_weights import TargetWeightsConfig


def _market(seed: int = 1, rows: int = 400, names: int = 4):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2022-01-03", periods=rows).strftime("%Y-%m-%d").tolist()
    tickers = [chr(65 + i) for i in range(names)]
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (rows, names)), axis=0))
    opens = closes * np.exp(rng.normal(0, 0.003, (rows, names)))
    decisions = {}
    for i, day in enumerate(dates):
        if i % 5 == 0 and i > 0:
            decisions[day] = dict(zip(tickers, rng.uniform(-0.3, 0.4, names)))
    return dates, tickers, closes, opens, decisions


def test_matches_the_target_weights_simulator_for_equities():
    dates, tickers, closes, opens, decisions = _market()
    panel = MarketPanel(dates, tickers, opens, closes, {t: "equity" for t in tickers}, set(dates))
    config = TargetWeightsConfig(min_weight_change=0.0, min_trade_usd=0.0, equity_fee_bps=10.0, equity_min_fee_usd=0.0,
                                 slippage_bps_by_class={"equity": 0.0}, financing_enabled=False)
    reference = pd.Series(simulate_target_weights(decisions, panel, config, start=dates[0], end=dates[-1], nav=1e9)["strategy"])
    weights = pd.DataFrame.from_dict(decisions, orient="index").reindex(dates)
    result = backtest(weights, pd.DataFrame(closes, index=dates, columns=tickers), opens=pd.DataFrame(opens, index=dates, columns=tickers),
                      cost_model=LinearCostModel(commission_bps=10.0), initial_nav=1e9)
    ours = result.returns.iloc[1:]
    theirs = reference.reindex(ours.index)
    assert not theirs.isna().any()
    assert abs((1 + ours).prod() - (1 + theirs).prod()) < 1e-4  # within 1 bp of total return (whole-share rounding)
    assert float(np.corrcoef(ours, theirs)[0, 1]) > 0.999
    assert float((ours - theirs).abs().max()) < 1e-6


def test_costs_reduce_returns_by_exactly_the_fees():
    dates, tickers, closes, opens, decisions = _market(seed=3)
    weights = pd.DataFrame.from_dict(decisions, orient="index").reindex(dates)
    prices = pd.DataFrame(closes, index=dates, columns=tickers)
    free = backtest(weights, prices, fill="close")
    paid = backtest(weights, prices, fill="close", cost_model=LinearCostModel(commission_bps=25.0))
    assert paid.nav.iloc[-1] < free.nav.iloc[-1]
    assert np.allclose(paid.gross_returns - paid.returns, paid.costs, atol=1e-12)
    assert paid.costs.sum() > 0 and (paid.turnover >= 0).all()


def test_close_fill_holds_target_weights_on_decision_days():
    dates, tickers, closes, _opens, decisions = _market(seed=4)
    weights = pd.DataFrame.from_dict(decisions, orient="index").reindex(dates)
    result = backtest(weights, pd.DataFrame(closes, index=dates, columns=tickers), fill="close")
    day = next(iter(decisions))
    assert np.allclose(result.weights.loc[day].to_numpy(), np.array([decisions[day][t] for t in tickers]), atol=1e-12)


def test_rebalance_every_skips_decisions_and_a_missing_price_is_never_sized():
    dates, tickers, closes, opens, decisions = _market(seed=5)
    closes = closes.copy()
    closes[:50, 0] = np.nan
    weights = pd.DataFrame.from_dict(decisions, orient="index").reindex(dates)
    prices = pd.DataFrame(closes, index=dates, columns=tickers)
    every = backtest(weights, prices, fill="close")
    sparse = backtest(weights, prices, fill="close", rebalance_every=3)
    assert (sparse.turnover > 0).sum() < (every.turnover > 0).sum()
    assert (every.weights.iloc[:50, 0] == 0).all()
    assert np.isfinite(every.nav).all()


def test_impact_model_uses_adv_and_vol():
    dates, tickers, closes, opens, decisions = _market(seed=6)
    weights = pd.DataFrame.from_dict(decisions, orient="index").reindex(dates)
    prices = pd.DataFrame(closes, index=dates, columns=tickers)
    with_impact = backtest(weights, prices, fill="close", cost_model=SquareRootImpactModel(eta=1.0), initial_nav=1e8,
                           adv_usd={t: 1e7 for t in tickers}, daily_vol={t: 0.02 for t in tickers})
    without_inputs = backtest(weights, prices, fill="close", cost_model=SquareRootImpactModel(eta=1.0), initial_nav=1e8)
    assert with_impact.costs.sum() > 0 and without_inputs.costs.sum() == 0


def test_bad_arguments_raise():
    prices = pd.DataFrame({"A": [1.0, 2.0]}, index=["2024-01-01", "2024-01-02"])
    with pytest.raises(ValueError):
        backtest(prices, prices, fill="next_open")
    with pytest.raises(ValueError):
        backtest(prices, prices, fill="vwap")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        backtest(prices, prices, fill="close", initial_nav=0.0)


def test_stats_report_and_frame_are_finite():
    dates, tickers, closes, opens, decisions = _market(seed=7)
    weights = pd.DataFrame.from_dict(decisions, orient="index").reindex(dates)
    result = backtest(weights, pd.DataFrame(closes, index=dates, columns=tickers), opens=pd.DataFrame(opens, index=dates, columns=tickers),
                      cost_model=LinearCostModel(commission_bps=5.0))
    assert isinstance(result, BacktestResult)
    stats = result.stats()
    assert all(math.isfinite(value) for value in stats.values())
    assert 0.0 <= stats["max_drawdown"] <= 1.0
    assert "Sharpe" in result.report() and set(result.to_frame().columns) >= {"nav", "return", "cost"}


def test_summary_statistics_of_a_constant_series_and_of_nothing():
    flat = pd.Series([0.001] * 252, index=pd.bdate_range("2024-01-01", periods=252).strftime("%Y-%m-%d"))
    stats = summary_statistics(flat)
    assert stats["max_drawdown"] == 0.0 and stats["cagr"] > 0
    empty = summary_statistics(pd.Series([], dtype=float))
    assert empty["observations"] == 0.0 and empty["sharpe_ratio"] == 0.0
    noisy = summary_statistics(pd.Series([0.01, float("nan"), float("inf"), -0.01], index=["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]))
    assert noisy["observations"] == 2.0
