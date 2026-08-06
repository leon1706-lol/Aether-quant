"""Tests for execution/reconciliation.py - V5.1 Phase 6 (production safety)."""

import pytest

from execution.reconciliation import reconcile_positions


def _reconcile(expected, actual, **overrides):
    kwargs = dict(weight_tolerance=0.01, value_tolerance_usd=50.0, portfolio_value=100_000.0)
    kwargs.update(overrides)
    return reconcile_positions(expected, actual, **kwargs)


# ---------------------------------------------------------------------------
# Four classifications
# ---------------------------------------------------------------------------


def test_matched_when_within_both_tolerances():
    # delta_weight=0.001 -> delta_usd=$100 on a $100k portfolio; the default
    # value_tolerance_usd=50.0 would reject that on dollar terms alone, so
    # this test uses a wider value tolerance specifically to isolate the
    # weight-tolerance-alone "matched" case.
    report = _reconcile({"AAPL": 0.10}, {"AAPL": 0.101}, value_tolerance_usd=1_000_000.0)

    assert report.matched == ["AAPL"]
    assert report.drifted == []


def test_drifted_when_weight_delta_exceeds_tolerance():
    report = _reconcile({"AAPL": 0.10}, {"AAPL": 0.20}, weight_tolerance=0.01, value_tolerance_usd=1_000_000.0)

    assert report.drifted[0]["symbol"] == "AAPL"
    assert report.drifted[0]["delta_weight"] == pytest.approx(0.10)
    assert report.matched == []


def test_drifted_when_only_value_tolerance_exceeded_despite_small_weight_delta():
    # A tiny weight delta on a large portfolio can still be a real dollar
    # drift - value_tolerance_usd must independently gate this even when
    # weight_tolerance alone would have passed.
    report = _reconcile(
        {"AAPL": 0.10}, {"AAPL": 0.105},
        weight_tolerance=0.10, value_tolerance_usd=10.0, portfolio_value=100_000.0,
    )

    assert report.drifted[0]["symbol"] == "AAPL"


def test_orphan_broker_when_held_but_not_expected():
    report = _reconcile({}, {"TSLA": 0.05})

    assert len(report.orphan_broker) == 1
    assert report.orphan_broker[0]["symbol"] == "TSLA"
    assert report.orphan_broker[0]["expected_weight"] == 0.0
    assert report.orphan_broker[0]["actual_weight"] == 0.05


def test_missing_broker_when_expected_but_not_held():
    report = _reconcile({"MSFT": 0.08}, {})

    assert len(report.missing_broker) == 1
    assert report.missing_broker[0]["symbol"] == "MSFT"
    assert report.missing_broker[0]["actual_weight"] == 0.0


# ---------------------------------------------------------------------------
# Tolerance boundaries
# ---------------------------------------------------------------------------


def test_exactly_at_weight_tolerance_boundary_is_matched():
    report = _reconcile({"AAPL": 0.10}, {"AAPL": 0.11}, weight_tolerance=0.01, value_tolerance_usd=1_000_000.0)
    assert report.matched == ["AAPL"]


def test_just_over_weight_tolerance_boundary_is_drifted():
    report = _reconcile({"AAPL": 0.10}, {"AAPL": 0.1101}, weight_tolerance=0.01, value_tolerance_usd=1_000_000.0)
    assert report.matched == []
    assert len(report.drifted) == 1


# ---------------------------------------------------------------------------
# Empty portfolios
# ---------------------------------------------------------------------------


def test_both_empty_never_raises_and_reports_all_empty():
    report = _reconcile({}, {})

    assert report.matched == []
    assert report.drifted == []
    assert report.orphan_broker == []
    assert report.missing_broker == []
    assert report.max_abs_weight_drift == 0.0
    assert report.breach is False


# ---------------------------------------------------------------------------
# Order-independence
# ---------------------------------------------------------------------------


def test_result_is_independent_of_dict_insertion_order():
    expected_a = {"AAPL": 0.10, "MSFT": 0.05, "TSLA": -0.03}
    actual_a = {"TSLA": -0.20, "GOOG": 0.02, "AAPL": 0.101}
    result_a = _reconcile(expected_a, actual_a, weight_tolerance=0.01, value_tolerance_usd=1_000_000.0)

    expected_b = {"TSLA": -0.03, "AAPL": 0.10, "MSFT": 0.05}
    actual_b = {"AAPL": 0.101, "TSLA": -0.20, "GOOG": 0.02}
    result_b = _reconcile(expected_b, actual_b, weight_tolerance=0.01, value_tolerance_usd=1_000_000.0)

    assert result_a.to_dict() == result_b.to_dict()


# ---------------------------------------------------------------------------
# max_abs_weight_drift / breach
# ---------------------------------------------------------------------------


def test_max_abs_weight_drift_is_the_largest_across_every_classification():
    report = _reconcile(
        {"AAPL": 0.10, "MSFT": 0.05}, {"AAPL": 0.101, "TSLA": 0.30},
        weight_tolerance=0.01, value_tolerance_usd=1_000_000.0,
    )
    # AAPL delta ~0.001, MSFT (missing_broker) delta 0.05, TSLA (orphan_broker) delta 0.30
    assert report.max_abs_weight_drift == pytest.approx(0.30)


def test_breach_false_when_max_tolerated_drift_not_provided():
    report = _reconcile({"AAPL": 0.10}, {"AAPL": 0.50}, weight_tolerance=0.01, value_tolerance_usd=1_000_000.0)
    assert report.breach is False


def test_breach_true_when_drift_exceeds_max_tolerated_drift():
    report = _reconcile(
        {"AAPL": 0.10}, {"AAPL": 0.50},
        weight_tolerance=0.01, value_tolerance_usd=1_000_000.0, max_tolerated_drift=0.05,
    )
    assert report.breach is True


def test_breach_false_when_drift_within_max_tolerated_drift():
    report = _reconcile(
        {"AAPL": 0.10}, {"AAPL": 0.101},
        weight_tolerance=0.0001, value_tolerance_usd=1_000_000.0, max_tolerated_drift=0.05,
    )
    assert report.breach is False


# ---------------------------------------------------------------------------
# Dust positions - tolerance is checked BEFORE presence, so a negligible
# one-sided amount is "matched", never a permanent orphan/missing entry
# (bug fix: previously ANY presence-only mismatch was unconditionally
# orphan_broker/missing_broker regardless of size).
# ---------------------------------------------------------------------------


def test_dust_position_held_but_not_expected_is_matched_not_orphan():
    report = _reconcile({}, {"AAPL": 0.0001}, weight_tolerance=0.01, value_tolerance_usd=1_000_000.0)
    assert report.matched == ["AAPL"]
    assert report.orphan_broker == []


def test_dust_position_expected_but_not_held_is_matched_not_missing():
    report = _reconcile({"AAPL": 0.0001}, {}, weight_tolerance=0.01, value_tolerance_usd=1_000_000.0)
    assert report.matched == ["AAPL"]
    assert report.missing_broker == []


def test_large_one_sided_position_still_classifies_as_orphan_or_missing():
    # Sanity check the dust fix didn't swallow genuine one-sided drift.
    report = _reconcile({}, {"TSLA": 0.20}, weight_tolerance=0.01, value_tolerance_usd=1_000_000.0)
    assert report.matched == []
    assert len(report.orphan_broker) == 1


def test_matched_symbols_excluded_from_max_abs_weight_drift():
    # A matched symbol's own tiny delta must never be what max_abs_weight_drift
    # reports - only drifted/orphan_broker/missing_broker entries count,
    # matching the field's own docstring.
    report = _reconcile(
        {"AAPL": 0.10, "MSFT": 0.05}, {"AAPL": 0.1005},
        weight_tolerance=0.01, value_tolerance_usd=1_000_000.0,
    )
    assert report.matched == ["AAPL"]
    assert report.missing_broker[0]["symbol"] == "MSFT"
    assert report.max_abs_weight_drift == pytest.approx(0.05)
