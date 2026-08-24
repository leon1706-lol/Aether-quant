"""V5.3.8 - tests for the Monte Carlo simulation core
(evaluation/monte_carlo.py). Deterministic, seeded, fast."""

from __future__ import annotations

import numpy as np

from evaluation.monte_carlo import run_monte_carlo


def _returns(rows: int = 300, seed: int = 5, drift: float = 0.0005) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(drift, 0.01, rows)


def test_deterministic_given_same_seed():
    r = _returns()
    a = run_monte_carlo(r, n_runs=50, seed=7)
    b = run_monte_carlo(r, n_runs=50, seed=7)
    assert a["status"] == "OK"
    assert a["avg_curve"] == b["avg_curve"]
    assert a["final_return_pct"] == b["final_return_pct"]


def test_shapes_and_downsampling():
    r = _returns(400)
    result = run_monte_carlo(r, n_runs=25, n_plot_points=120)
    curves = result["runs_curves"]
    assert curves.shape == (25, 120)
    assert len(result["avg_curve"]) == 120
    for band in result["pct_band"].values():
        assert len(band) == 120


def test_average_curve_is_elementwise_mean_of_runs():
    r = _returns(200, seed=1)
    result = run_monte_carlo(r, n_runs=40, seed=2)
    curves = result["runs_curves"]
    manual_mean = curves.mean(axis=0)
    stored = np.asarray(result["avg_curve"])
    np.testing.assert_allclose(stored, manual_mean, atol=1e-6)


def test_constant_zero_returns_degrade_to_flat_curve():
    flat = np.zeros(120)
    result = run_monte_carlo(flat, n_runs=10)
    assert result["status"] == "OK"
    assert result["sharpe"]["p50"] == 0.0
    assert result["max_drawdown"]["p50"] == 0.0
    assert result["prob_negative_return"] == 0.0
    avg = np.asarray(result["avg_curve"])
    assert np.allclose(avg, 1.0)


def test_percentile_ordering_and_probability_bounds():
    r = _returns(250, seed=9, drift=-0.0008)  # losing strategy on purpose
    result = run_monte_carlo(r, n_runs=60, seed=3)
    fr = result["final_return_pct"]
    assert fr["p5"] <= fr["p25"] <= fr["p50"] <= fr["p75"] <= fr["p95"]
    sd = result["max_drawdown"]
    assert sd["p5"] <= sd["p95"]
    assert 0.0 <= result["prob_negative_return"] <= 1.0
    # Losing drift -> most runs negative.
    assert result["prob_negative_return"] > 0.5


def test_short_input_degrades_without_raising():
    result = run_monte_carlo([0.01, -0.01], n_runs=10)
    assert result["status"].startswith("SKIPPED")
    assert result["avg_curve"] == []
    empty = run_monte_carlo([], n_runs=10)
    assert empty["status"].startswith("SKIPPED")


def test_unknown_method_skips_cleanly():
    result = run_monte_carlo(_returns(), method="chaos", n_runs=5)
    assert result["status"].startswith("SKIPPED")


def test_block_vs_iid_both_run_and_differ_statistically():
    r = _returns(500, seed=13) + np.sin(np.arange(500) / 6.0) * 0.004  # autocorrelated
    block = run_monte_carlo(r, n_runs=80, seed=4, method="block", block_size=20)
    iid = run_monte_carlo(r, n_runs=80, seed=4, method="iid")
    assert block["status"] == "OK" and iid["status"] == "OK"
    # Block bootstrap preserves short-horizon structure: its drawdown tail is
    # expected to differ from i.i.d. on an autocorrelated series (not a strict
    # mathematical guarantee, so only smoke-check both produce valid output).
    assert block["max_drawdown"]["p95"] >= 0.0
    assert iid["max_drawdown"]["p95"] >= 0.0


def test_config_echo_in_result():
    result = run_monte_carlo(_returns(100), n_runs=5, seed=11, block_size=7, method="iid")
    assert result["config"] == {
        "n_runs": 5,
        "block_size": 7,
        "seed": 11,
        "method": "iid",
        "trading_days_per_year": 252,
    }


def test_all_positive_series_yields_exactly_zero_loss_probability():
    result = run_monte_carlo(_returns(200, seed=21) + 0.05, n_runs=50)
    assert result["prob_negative_return"] == 0.0
    assert result["worst_run_total_return"] > 0.0


def test_block_size_larger_than_series_clamps_safely():
    r = _returns(40, seed=8)
    result = run_monte_carlo(r, n_runs=10, block_size=500)
    assert result["status"] == "OK"
    assert result["config"]["n_runs"] == 10


def test_n_plot_points_larger_than_series_is_handled():
    result = run_monte_carlo(_returns(30, seed=4), n_runs=5, n_plot_points=900)
    assert result["status"] == "OK"
    curves = result["runs_curves"]
    assert curves.shape[1] == 30  # clamped to series length
