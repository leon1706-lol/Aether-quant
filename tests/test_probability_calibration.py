"""V6.4.0 (lead L2): reliability, temperature scaling, isotonic regression and thresholds."""

from __future__ import annotations

import numpy as np
import pytest

from evaluation.probability_calibration import (
    apply_isotonic, apply_temperature, best_threshold_by_class, brier_score, calibration_report, cross_fitted_log_loss,
    expected_calibration_error, fit_isotonic, fit_temperature, log_loss, reliability_curve,
)


def _overconfident(n=4000, temperature=2.5, seed=1):
    """True probabilities p; the model reports sigmoid(logit(p) * temperature): over-confident by exactly `temperature`."""
    rng = np.random.default_rng(seed)
    true = np.clip(rng.beta(4, 4, n), 0.05, 0.95)
    outcome = (rng.random(n) < true).astype(float)
    reported = apply_temperature(true, 1.0 / temperature)
    return reported, outcome, true


def test_log_loss_and_brier_of_known_values():
    assert log_loss([0.5, 0.5], [1, 0]) == pytest.approx(np.log(2.0))
    assert brier_score([1.0, 0.0], [1, 0]) == pytest.approx(0.0, abs=1e-12)
    assert log_loss([], []) is None


def test_ece_of_a_calibrated_sample_is_near_zero_and_of_a_biased_one_is_not():
    rng = np.random.default_rng(0)
    p = rng.random(20000)
    y = (rng.random(20000) < p).astype(float)
    assert expected_calibration_error(p, y) < 0.02
    assert expected_calibration_error(np.full(2000, 0.9), (rng.random(2000) < 0.5).astype(float)) == pytest.approx(0.4, abs=0.05)


def test_reliability_curve_bins_and_counts():
    rows = reliability_curve([0.05, 0.05, 0.95], [0, 1, 1], bins=10)
    assert [row["n"] for row in rows] == [2, 1]
    assert rows[0]["observed_rate"] == pytest.approx(0.5) and rows[1]["mean_probability"] == pytest.approx(0.95)


def test_temperature_fit_recovers_the_over_confidence_and_lowers_the_loss():
    reported, outcome, _true = _overconfident()
    temperature = fit_temperature(reported, outcome)
    assert temperature == pytest.approx(2.5, rel=0.2)
    assert log_loss(apply_temperature(reported, temperature), outcome) < log_loss(reported, outcome)


def test_temperature_needs_both_classes_and_enough_rows():
    assert fit_temperature([0.6] * 5, [1, 0, 1, 0, 1]) is None
    assert fit_temperature([0.6] * 20, [1] * 20) is None


def test_isotonic_is_monotone_and_pools_violators():
    fit = fit_isotonic(np.linspace(0.05, 0.95, 40), np.array([0, 1] * 20, dtype=float))
    assert all(a <= b + 1e-12 for a, b in zip(fit["y"], fit["y"][1:]))
    assert len(fit["x"]) < 40
    calibrated = apply_isotonic([0.0, 0.5, 1.0], fit)
    assert calibrated[0] <= calibrated[1] <= calibrated[2]


def test_isotonic_improves_a_monotone_miscalibration():
    reported, outcome, _true = _overconfident()
    fit = fit_isotonic(reported, outcome)
    assert log_loss(np.clip(apply_isotonic(reported, fit), 1e-6, 1 - 1e-6), outcome) < log_loss(reported, outcome)


def test_cross_fitted_loss_prefers_a_calibration_for_an_overconfident_head():
    reported, outcome, _true = _overconfident()
    raw = cross_fitted_log_loss(reported, outcome, "raw")
    assert cross_fitted_log_loss(reported, outcome, "temperature") < raw
    with pytest.raises(ValueError):
        cross_fitted_log_loss(reported, outcome, "nope")


def test_thresholds_by_class_pick_the_balanced_accuracy_maximiser():
    rng = np.random.default_rng(2)
    n = 400
    p = rng.random(n)
    y = (rng.random(n) < np.clip(p - 0.2, 0.02, 0.98)).astype(float)  # the positives need a higher bar than 0.5
    result = best_threshold_by_class(p, y, ["eq"] * n)
    assert 0.3 <= result["eq"]["threshold"] <= 0.7 and result["eq"]["balanced_accuracy"] > 0.5
    small = best_threshold_by_class([0.6] * 5, [1, 0, 1, 0, 1], ["x"] * 5)
    assert small["x"] == {"threshold": 0.5, "balanced_accuracy": None, "n": 5}


def test_the_report_carries_every_decision_input():
    reported, outcome, _ = _overconfident(n=600)
    report = calibration_report(reported, outcome, classes=["eq", "crypto"] * 300)
    assert {"log_loss", "brier", "ece", "reliability", "cross_fitted_log_loss", "temperature", "isotonic", "thresholds_by_class"} <= set(report)
    assert report["cross_fitted_log_loss"]["temperature"] < report["cross_fitted_log_loss"]["raw"]
