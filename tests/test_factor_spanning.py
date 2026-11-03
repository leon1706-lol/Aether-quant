"""evaluation/factor_spanning.py (V6.4.3)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from evaluation.factor_spanning import build_factor_returns, build_factor_scores, factor_spanning


def _frame(n_dates: int = 400, n_names: int = 25, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2021-01-04", periods=n_dates, freq="B").strftime("%Y-%m-%d")
    rows = []
    for i in range(n_names):
        daily = rng.normal(0, 0.01, n_dates)
        for t, date in enumerate(dates):
            rows.append({"date": date, "ticker": f"T{i}", "close_to_close_return_1d": daily[t],
                         "close_to_close_return_5d": daily[max(0, t - 4): t + 1].sum(), "momentum_20d": daily[max(0, t - 19): t + 1].sum(),
                         "rolling_volatility_20d": 0.01 + i * 1e-4, "dist_52w_high": -0.1 * i / n_names,
                         "target_return_1d": daily[t + 1] if t + 1 < n_dates else np.nan})
    return pd.DataFrame(rows)


def test_momentum_12_1_uses_only_past_returns():
    frame = _frame(n_dates=300, n_names=2)
    scores = build_factor_scores(frame)
    one = frame[frame["ticker"] == "T0"].reset_index(drop=True)
    t = 280
    expected = one["close_to_close_return_1d"].iloc[t - 252 + 1: t - 21 + 1].sum()
    got = scores.loc[frame.index[(frame["ticker"] == "T0")][t], "f_mom_12_1"]
    assert got == pytest.approx(expected)
    assert scores.loc[frame.index[(frame["ticker"] == "T0")][100], "f_mom_12_1"] != scores.loc[frame.index[(frame["ticker"] == "T0")][100], "f_mom_12_1"]


def test_factor_return_is_top_minus_bottom_quantile():
    frame = pd.DataFrame({"date": ["d"] * 10, "s": list(range(10)), "target_return_1d": [0.0] * 8 + [0.1, 0.2]})
    out = build_factor_returns(frame, ["s"], quantile=0.2, min_names=5)
    assert out.loc["d", "s"] == pytest.approx(0.15)


def test_spanning_recovers_alpha_and_beta():
    rng = np.random.default_rng(3)
    index = pd.Index([f"d{i}" for i in range(1500)])
    factors = pd.DataFrame({"f1": rng.normal(0, 0.01, 1500), "f2": rng.normal(0, 0.01, 1500)}, index=index)
    signal = 0.0008 + 0.5 * factors["f1"] + rng.normal(0, 0.002, 1500)
    report = factor_spanning(signal, factors, hac_lags=5)
    assert report["alpha_daily"] == pytest.approx(0.0008, abs=2e-4)
    assert report["betas"]["f1"] == pytest.approx(0.5, abs=0.05)
    assert report["alpha_t"] > 5
    assert abs(report["betas_t"]["f2"]) < 4


def test_spanning_with_too_few_dates_reports_nothing():
    report = factor_spanning(pd.Series([0.1, 0.2]), pd.DataFrame({"f": [0.1, 0.2]}))
    assert report["alpha_t"] is None


def test_composite_is_a_mean_of_ranks():
    scores = build_factor_scores(_frame(n_dates=300))
    composite = scores["f_composite"].dropna()
    assert composite.between(0.0, 1.0).all()
