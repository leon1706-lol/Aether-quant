"""evaluation/pbo.py (V6.4.3)."""

from __future__ import annotations

import numpy as np

from evaluation.pbo import probability_of_backtest_overfitting


def test_picking_the_best_of_pure_noise_overfits_about_half_the_time():
    returns = np.random.default_rng(0).normal(0.0, 0.01, size=(800, 20))
    report = probability_of_backtest_overfitting(returns, blocks=10)
    assert 0.3 < report["pbo"] < 0.7
    assert report["num_combinations"] == 252


def test_one_genuinely_skilled_trial_gives_a_low_pbo():
    rng = np.random.default_rng(1)
    returns = rng.normal(0.0, 0.01, size=(800, 10))
    returns[:, 3] += 0.004
    report = probability_of_backtest_overfitting(returns, blocks=10)
    assert report["pbo"] < 0.1
    assert report["prob_oos_loss"] < 0.1


def test_degenerate_inputs_report_no_pbo():
    assert probability_of_backtest_overfitting(np.zeros((100, 1)))["pbo"] is None
    assert probability_of_backtest_overfitting(np.zeros((5, 4)), blocks=16)["pbo"] is None
    assert probability_of_backtest_overfitting(np.zeros((100, 4)), blocks=7)["pbo"] is None


def test_nan_returns_count_as_flat_days():
    returns = np.random.default_rng(2).normal(0.0, 0.01, size=(320, 6))
    returns[::7, 2] = np.nan
    assert probability_of_backtest_overfitting(returns, blocks=8)["pbo"] is not None
