"""V5.4.3 - tests for factor-neutralization check, HRP allocation, and
benchmark comparison baselines."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from evaluation.factor_neutralization_check import compute_factor_exposure


class TestFactorExposure:
    def _make_data(self, n=200, seed=7):
        rng = np.random.default_rng(seed)
        market = rng.normal(0.0003, 0.01, n)
        momentum = rng.normal(0, 0.008, n)
        book = 0.6 * market + 0.3 * momentum + rng.normal(0, 0.005, n)
        idx = pd.bdate_range("2019-01-01", periods=n)
        return (
            pd.Series(book, index=idx),
            pd.Series(market, index=idx),
            pd.Series(momentum, index=idx),
            idx,
        )

    def test_pure_market_exposure_gives_high_r_squared(self):
        rng = np.random.default_rng(3)
        market = rng.normal(0, 0.01, 200)
        book = 0.8 * market + rng.normal(0, 0.001, 200)
        result = compute_factor_exposure(
            pd.Series(book), pd.Series(market)
        )
        assert result["r_squared"] > 0.95
        assert abs(result["loadings"]["market"] - 0.8) < 0.1

    def test_pure_alpha_gives_low_r_squared(self):
        rng = np.random.default_rng(5)
        alpha = rng.normal(0.0002, 0.005, 200)
        market = rng.normal(0, 0.01, 200)
        result = compute_factor_exposure(
            pd.Series(alpha), pd.Series(market)
        )
        assert result["r_squared"] < 0.15
        assert abs(result["alpha_sharpe"]) < 3.0

    def test_returns_all_required_keys(self):
        book, market, mom, idx = self._make_data()
        result = compute_factor_exposure(
            book, market, momentum_factor=mom
        )
        for key in ("alpha_sharpe", "total_sharpe", "r_squared",
                    "loadings", "alpha_annualized_return_pct",
                    "factor_contribution_pct", "n_obs"):
            assert key in result

    def test_handles_short_series(self):
        result = compute_factor_exposure(
            pd.Series([0.01, -0.01]),
            pd.Series([0.005, -0.005]),
        )
        assert isinstance(result, dict)


class TestHRP:
    def test_hrp_weights_sum_to_one(self):
        from portfolio.hrp_allocation import compute_hrp_weights

        rng = np.random.default_rng(11)
        returns = pd.DataFrame(
            rng.normal(0, 0.01, (100, 6)),
            columns=[f"T{i}" for i in range(6)],
        )
        weights = compute_hrp_weights(returns)
        assert weights.sum() == pytest.approx(1.0, abs=1e-6)
        assert all(w >= 0 for w in weights)

    def test_hrp_single_ticker_gets_full_weight(self):
        from portfolio.hrp_allocation import compute_hrp_weights

        returns = pd.DataFrame({"A": [0.01, -0.01, 0.02]})
        weights = compute_hrp_weights(returns)
        assert weights["A"] == pytest.approx(1.0)

    def test_build_hrp_allocation_longs_and_shorts(self):
        from portfolio.hrp_allocation import build_hrp_allocation

        rng = np.random.default_rng(13)
        returns_by_ticker = {
            f"T{i}": list(rng.normal(0, 0.01, 50)) for i in range(6)
        }
        longs = ["T0", "T1", "T2"]
        shorts = ["T3", "T4", "T5"]
        alloc = build_hrp_allocation(
            returns_by_ticker, selected_tickers_long=longs, selected_tickers_short=shorts
        )
        assert set(alloc) == set(longs + shorts)
        long_sum = sum(v for t, v in alloc.items() if t in longs)
        short_sum = sum(abs(v) for t, v in alloc.items() if t in shorts)
        assert long_sum == pytest.approx(short_sum, abs=0.01)


class TestBenchmarkBaselines:
    def test_momentum_baseline_returns_valid_sharpe(self):
        from evaluation.benchmark_comparison import momentum_baseline

        rng = np.random.default_rng(17)
        log_returns = np.cumsum(rng.normal(0, 0.01, (200, 10)), axis=0)
        close = pd.DataFrame(
            100 * np.exp(log_returns),
            columns=[f"A{i}" for i in range(10)],
            index=pd.bdate_range("2019-01-01", periods=200),
        )
        result = momentum_baseline(close)
        assert isinstance(result["net_sharpe"], float)
        assert "total_return_pct" in result

    def test_random_entry_baseline_near_zero_sharpe(self):
        from evaluation.benchmark_comparison import random_entry_baseline

        result = random_entry_baseline([f"T{i}" for i in range(12)], n_days=300)
        assert abs(result["net_sharpe"]) < 1.5  # should be near zero

    def test_mean_reversion_no_longer_placeholder_zero(self):
        # V5.4.4: this baseline previously accrued a hardcoded
        # `weight_sum * 0.001` placeholder -> structurally 0.0 Sharpe AND
        # 0.0% return regardless of the data. A strongly trending universe
        # (half the names rising, half falling) must now produce a
        # nonzero result - MR shorts the trend winners, so it should lean
        # negative here.
        from evaluation.benchmark_comparison import mean_reversion_baseline

        rng = np.random.default_rng(42)
        n = 60
        drifts = np.linspace(-0.004, 0.004, 12)
        log_rets = np.cumsum(rng.normal(0, 0.005, (n, 12)) + drifts[None, :], axis=0)
        close = pd.DataFrame(
            100 * np.exp(log_rets),
            columns=[f"T{i}" for i in range(12)],
            index=pd.bdate_range("2019-01-01", periods=n),
        )
        result = mean_reversion_baseline(close)
        assert not (result["net_sharpe"] == 0.0 and result["total_return_pct"] == 0.0)
        assert result["total_return_pct"] < 0.0

    def test_mean_reversion_known_value_deterministic(self):
        # T_A rises +1%/day, T_B falls -0.5%/day. With top_n=bottom_n=1
        # and a single rebalance (rebalance_every huge), the book is long
        # the FALLER and short the RISER from day `lookback` on: each
        # accrued day earns exactly r_B - r_A = -1.5%.
        from evaluation.benchmark_comparison import mean_reversion_baseline

        n = 25
        dates = pd.bdate_range("2019-01-01", periods=n)
        close = pd.DataFrame(
            {
                "T_A": 100 * np.power(1.01, np.arange(n)),
                "T_B": 100 * np.power(0.995, np.arange(n)),
            },
            index=dates,
        )
        lookback = 5
        result = mean_reversion_baseline(close, lookback=lookback, top_n=1, bottom_n=1, rebalance_every=1000)
        # Accrual starts at di=lookback (the single rebalance) and earns
        # (1 - 0.015) per day through di=n-2 (last next-day pair).
        accrued_days = n - 1 - lookback
        expected_total = (0.985**accrued_days - 1.0) * 100.0
        assert result["total_return_pct"] == pytest.approx(round(expected_total, 2), abs=1e-6)
        assert result["net_sharpe"] < 0
