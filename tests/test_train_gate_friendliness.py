"""Tests for train.py::compute_gate_friendliness_weight_by_date() -
V5.2.8 (development/Problems.md #94)."""

import pandas as pd

from train import _GATE_FRIENDLINESS_WEIGHT_FLOOR, compute_gate_friendliness_weight_by_date


def _frame(rows):
    return pd.DataFrame(rows)


def test_no_gates_triggered_gives_weight_one():
    frame = _frame(
        {
            "date": ["2020-01-01"] * 3,
            "topology_risk_elevated": [0, 0, 0],
            "topology_risk_isolated": [0, 0, 0],
            "regime_risk_off": [0, 0, 0],
            "regime_signal_risk_score": [0.0, 0.0, 0.0],
        }
    )
    weights = compute_gate_friendliness_weight_by_date(frame, risk_off_override_min_severity=0.55)
    assert weights == {"2020-01-01": 1.0}


def test_all_rows_topology_gated_hits_the_floor():
    frame = _frame(
        {
            "date": ["2020-01-01"] * 3,
            "topology_risk_elevated": [1, 1, 1],
            "topology_risk_isolated": [0, 0, 0],
            "regime_risk_off": [0, 0, 0],
            "regime_signal_risk_score": [0.0, 0.0, 0.0],
        }
    )
    weights = compute_gate_friendliness_weight_by_date(frame, risk_off_override_min_severity=0.55)
    assert weights["2020-01-01"] == _GATE_FRIENDLINESS_WEIGHT_FLOOR


def test_partial_topology_gating_gives_a_fraction_between_floor_and_one():
    frame = _frame(
        {
            "date": ["2020-01-01"] * 4,
            "topology_risk_elevated": [1, 0, 0, 0],
            "topology_risk_isolated": [0, 0, 0, 0],
            "regime_risk_off": [0, 0, 0, 0],
            "regime_signal_risk_score": [0.0, 0.0, 0.0, 0.0],
        }
    )
    weights = compute_gate_friendliness_weight_by_date(frame, risk_off_override_min_severity=0.55)
    assert weights["2020-01-01"] == 0.75


def test_topology_isolated_also_gates():
    frame = _frame(
        {
            "date": ["2020-01-01"] * 2,
            "topology_risk_elevated": [0, 0],
            "topology_risk_isolated": [1, 1],
            "regime_risk_off": [0, 0],
            "regime_signal_risk_score": [0.0, 0.0],
        }
    )
    weights = compute_gate_friendliness_weight_by_date(frame, risk_off_override_min_severity=0.55)
    assert weights["2020-01-01"] == _GATE_FRIENDLINESS_WEIGHT_FLOOR


def test_risk_off_below_severity_threshold_does_not_gate():
    """Mild risk_off (severity below the configured floor) must NOT
    override - mirrors analyzer/market_analyzer.py's own Priority 2
    severity-gated behavior, not an unconditional risk_off veto."""
    frame = _frame(
        {
            "date": ["2020-01-01"] * 2,
            "topology_risk_elevated": [0, 0],
            "topology_risk_isolated": [0, 0],
            "regime_risk_off": [1, 1],
            "regime_signal_risk_score": [-0.30, -0.30],
        }
    )
    weights = compute_gate_friendliness_weight_by_date(frame, risk_off_override_min_severity=0.55)
    assert weights["2020-01-01"] == 1.0


def test_risk_off_at_or_above_severity_threshold_gates():
    frame = _frame(
        {
            "date": ["2020-01-01"] * 2,
            "topology_risk_elevated": [0, 0],
            "topology_risk_isolated": [0, 0],
            "regime_risk_off": [1, 1],
            "regime_signal_risk_score": [-0.55, -0.65],
        }
    )
    weights = compute_gate_friendliness_weight_by_date(frame, risk_off_override_min_severity=0.55)
    assert weights["2020-01-01"] == _GATE_FRIENDLINESS_WEIGHT_FLOOR


def test_multiple_dates_computed_independently():
    frame = _frame(
        {
            "date": ["2020-01-01", "2020-01-01", "2020-01-02", "2020-01-02"],
            "topology_risk_elevated": [0, 0, 1, 1],
            "topology_risk_isolated": [0, 0, 0, 0],
            "regime_risk_off": [0, 0, 0, 0],
            "regime_signal_risk_score": [0.0, 0.0, 0.0, 0.0],
        }
    )
    weights = compute_gate_friendliness_weight_by_date(frame, risk_off_override_min_severity=0.55)
    assert weights["2020-01-01"] == 1.0
    assert weights["2020-01-02"] == _GATE_FRIENDLINESS_WEIGHT_FLOOR


def test_missing_required_columns_degrades_to_uniform_one_not_raises():
    frame = _frame({"date": ["2020-01-01", "2020-01-02"], "some_other_column": [1, 2]})
    weights = compute_gate_friendliness_weight_by_date(frame, risk_off_override_min_severity=0.55)
    assert weights == {"2020-01-01": 1.0, "2020-01-02": 1.0}


def test_missing_date_column_entirely_returns_empty_dict_not_raises():
    frame = _frame({"some_other_column": [1, 2]})
    weights = compute_gate_friendliness_weight_by_date(frame, risk_off_override_min_severity=0.55)
    assert weights == {}


def test_default_severity_threshold_is_zero_gates_any_risk_off():
    """risk_off_override_min_severity defaults to 0.0 when omitted - a
    caller that forgets to pass the calibrated config value gets the
    strictest (most conservative) behavior, never a silent no-op."""
    frame = _frame(
        {
            "date": ["2020-01-01"] * 2,
            "topology_risk_elevated": [0, 0],
            "topology_risk_isolated": [0, 0],
            "regime_risk_off": [1, 1],
            "regime_signal_risk_score": [-0.05, -0.05],
        }
    )
    weights = compute_gate_friendliness_weight_by_date(frame)
    assert weights["2020-01-01"] == _GATE_FRIENDLINESS_WEIGHT_FLOOR
