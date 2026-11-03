"""features/asof_beta_labels.py: the as-of beta and the beta-neutral / residual rank labels built on it (V6.4.3)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from features.asof_beta_labels import (
    asof_beta_by_row,
    asof_residual_forward_return,
    asof_rolling_beta,
    build_asof_rank_labels,
    cross_sectional_residualize,
)


def test_rolling_beta_recovers_a_constant_slope():
    rng = np.random.default_rng(1)
    market = rng.normal(0, 0.01, 400)
    asset = 1.7 * market + rng.normal(0, 1e-6, 400)
    beta = asof_rolling_beta(asset, market, window=100, min_periods=50)
    assert np.isnan(beta[:49]).all()
    assert beta[60:] == pytest.approx(1.7, abs=1e-3)


def test_beta_at_t_never_sees_a_later_return():
    rng = np.random.default_rng(2)
    market = rng.normal(0, 0.01, 300)
    asset = 0.8 * market + rng.normal(0, 0.005, 300)
    before = asof_rolling_beta(asset, market, window=120, min_periods=60)
    changed_asset, changed_market = asset.copy(), market.copy()
    changed_asset[200:] = 5.0
    changed_market[200:] = -3.0
    after = asof_rolling_beta(changed_asset, changed_market, window=120, min_periods=60)
    np.testing.assert_array_equal(before[:200], after[:200])


def test_missing_pairs_are_skipped_not_zero_filled():
    market = np.array([0.01, np.nan, -0.02, 0.03, 0.01, -0.01])
    asset = 2.0 * np.nan_to_num(market)
    beta = asof_rolling_beta(asset, market, window=10, min_periods=3)
    assert beta[-1] == pytest.approx(2.0)


def test_residual_forward_return_treats_a_missing_beta_as_zero():
    out = asof_residual_forward_return([0.05, 0.02], [0.01, 0.01], [np.nan, 2.0])
    assert out == pytest.approx([0.05, 0.0])


def test_residualize_falls_back_on_a_degenerate_fit():
    returns = np.array([0.1, 0.2])
    assert cross_sectional_residualize(returns, np.ones((2, 3))) is returns


def _universe(n_dates: int = 300, n_assets: int = 25, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n_dates, freq="D").strftime("%Y-%m-%d")
    market = rng.normal(0, 0.01, n_dates)
    rows = []
    for asset in range(n_assets):
        ticker = "SPY" if asset == 0 else f"A{asset}"
        beta = 1.0 if asset == 0 else rng.uniform(0.2, 1.8)
        daily = beta * market + rng.normal(0, 0.01, n_dates)
        closes = 100 * np.cumprod(1 + daily)
        for i, date in enumerate(dates):
            rows.append({"date": date, "ticker": ticker, "close_to_close_return_1d": daily[i],
                         "target_return_5d": closes[i + 5] / closes[i] - 1 if i + 5 < n_dates else np.nan,
                         "liquidity_log_dollar_volume": 10 + asset * 0.1})
    return pd.DataFrame(rows)


def test_labels_are_percentile_ranks_on_full_dates_only():
    frame = _universe()
    labels = build_asof_rank_labels(frame, horizons=(5,), sector_by_ticker={"SPY": "X"})
    ranks = labels["target_beta_neutral_rank_5d_asof"].dropna()
    assert ranks.between(0.0, 1.0).all()
    assert labels["target_residual_rank_5d_asof"].dropna().between(0.0, 1.0).all()
    last_dates = frame["date"].isin(sorted(frame["date"].unique())[-5:])
    assert labels.loc[last_dates, "target_beta_neutral_rank_5d_asof"].isna().all()


def test_a_label_row_does_not_change_when_later_data_changes():
    frame = _universe()
    cutoff = sorted(frame["date"].unique())[200]
    labels = build_asof_rank_labels(frame, horizons=(5,), use_sector=False, use_size=False)
    shocked = frame.copy()
    later = shocked["date"] > cutoff
    shocked.loc[later, "close_to_close_return_1d"] *= -4.0
    relabelled = build_asof_rank_labels(shocked, horizons=(5,), use_sector=False, use_size=False)
    early = frame["date"] < sorted(frame["date"].unique())[190]  # forward windows end before the cutoff
    pd.testing.assert_series_equal(labels.loc[early, "target_beta_neutral_rank_5d_asof"],
                                   relabelled.loc[early, "target_beta_neutral_rank_5d_asof"])


def test_beta_by_row_is_aligned_to_the_frame_index():
    frame = _universe(n_dates=150, n_assets=3).sample(frac=1.0, random_state=0)
    beta = asof_beta_by_row(frame, market_ticker="SPY", window=60, min_periods=30)
    assert beta.index.equals(frame.index)
    spy = beta[frame["ticker"] == "SPY"].dropna()
    assert len(spy) > 0
    assert spy.to_numpy() == pytest.approx(1.0)
