"""evaluation/sim_lean_calibration.py (V6.4.3)."""

from __future__ import annotations

import numpy as np
import pytest

from evaluation.sim_lean_calibration import daily_gap_breakdown, gap_report, rung_attribution


def test_rung_attribution_reports_each_rungs_gain():
    variants = {"v580": {"daily_correlation": 0.5, "annual_return_gap": 0.04},
                "phase": {"daily_correlation": 0.6, "annual_return_gap": -0.03},
                "calibrated": {"daily_correlation": 0.7, "annual_return_gap": 0.01}}
    rows = rung_attribution(variants)
    assert [row["rung"] for row in rows] == ["v580", "phase", "calibrated"]
    assert rows[1]["delta_correlation"] == pytest.approx(0.1)
    assert rows[1]["delta_gap"] == pytest.approx(-0.01)
    assert "delta_correlation" not in rows[0]


def test_gap_breakdown_on_identical_series_is_zero():
    series = {f"d{i:03d}": float(v) for i, v in enumerate(np.random.default_rng(0).normal(0, 0.01, 100))}
    out = daily_gap_breakdown(series, dict(series))
    assert out["daily_correlation"] == pytest.approx(1.0)
    assert out["tracking_error_annual"] == pytest.approx(0.0)


def test_gap_breakdown_separates_rebalance_days():
    lean = {f"d{i:03d}": 0.0 for i in range(60)}
    offline = {date: (0.01 if int(date[1:]) % 20 == 0 else 0.0) for date in lean}
    out = daily_gap_breakdown(lean, offline, rebalance_dates=[d for d in lean if int(d[1:]) % 20 == 0])
    assert out["mean_abs_gap_rebalance_days"] == pytest.approx(0.01)
    assert out["mean_abs_gap_other_days"] == 0.0
    assert out["worst_days_share_of_squared_gap"] == pytest.approx(1.0)


def test_gap_breakdown_needs_three_days():
    assert daily_gap_breakdown({"a": 0.1}, {"a": 0.2}) == {"days": 1}


def test_gap_report_names_the_best_rung():
    report = gap_report({"windows": {"bt5": {"variants": {"v580": {"daily_correlation": 0.4, "annual_return_gap": 0.0},
                                                           "calibrated": {"daily_correlation": 0.7, "annual_return_gap": 0.0}}}}})
    assert report["bt5"]["best_rung"] == "calibrated"
    assert report["bt5"]["judged"]["daily_correlation"] == 0.7
