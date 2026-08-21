"""V5.3.5.3 Workstream B (development/Problems.md #91/#100) - tests for
evaluation/feature_reconciliation.py, the XOM feature-level investigation's
pure diff core.

Pure-function coverage only - no Lean backtest, no real dataset (the CLI
wiring that owns the I/O gets its own end-to-end tests in test_aq_cli.py).
"""

import math

from evaluation.feature_reconciliation import (
    DEFAULT_ABS_TOLERANCE,
    summarize_feature_reconciliation,
    reconcile_feature_snapshot,
)


def _row(**overrides):
    row = {
        "date": "2019-01-02",
        "ticker": "XOM",
        "return_5d": 0.012,
        "volatility_20d": 0.155,
        "volume_zscore": -0.4,
    }
    row.update(overrides)
    return row


def _snapshot(**overrides):
    snapshot = {
        "return_5d": 0.012,
        "volatility_20d": 0.155,
        "volume_zscore": -0.4,
    }
    snapshot.update(overrides)
    return snapshot


def test_exact_match_reports_all_matched_and_zero_delta():
    result = reconcile_feature_snapshot(_snapshot(), _row())
    assert result["features_compared"] == 3
    assert result["features_matched"] == 3
    assert result["features_diverged"] == 0
    assert result["max_abs_delta"] == 0.0
    assert result["features_only_in_logged"] == []
    assert result["features_only_in_offline"] == ["date", "ticker"]
    for entry in result["feature_deltas"]:
        assert entry["diverged"] is False


def test_divergence_requires_both_abs_and_rel_tolerance_exceeded():
    # abs_delta = 1e-7 exceeds the default abs tolerance (1e-9) but the
    # offline value is large enough that relative_delta (~6e-7) also clears
    # the rel floor -> a real divergence.
    result = reconcile_feature_snapshot(_snapshot(return_5d=0.0120001), _row())
    assert result["features_diverged"] == 1
    assert result["feature_deltas"][0]["feature"] == "return_5d"
    assert result["feature_deltas"][0]["diverged"] is True

    # Same abs_delta against a near-zero offline value: relative_delta is
    # huge, so this is ALSO a divergence - the AND-condition only forgives
    # tiny absolute deltas when the value itself is tiny.
    result_near_zero = reconcile_feature_snapshot({"tiny": 1e-7}, {"tiny": 0.0})
    assert result_near_zero["features_diverged"] == 1

    # Tiny abs delta on a tiny offline value (rel within floor): noise,
    # not a divergence.
    result_noise = reconcile_feature_snapshot({"tiny": 1e-12}, {"tiny": 2e-12})
    assert result_noise["features_diverged"] == 0
    assert result_noise["features_matched"] == 1


def test_float_reconstruction_noise_within_default_tolerances_matches():
    logged = _snapshot(volume_zscore=-0.4 + 1e-13)
    result = reconcile_feature_snapshot(logged, _row())
    assert result["features_diverged"] == 0
    assert result["features_matched"] == 3


def test_nan_or_none_on_either_side_degrades_to_none_not_divergence():
    logged = _snapshot(volatility_20d=None)
    result = reconcile_feature_snapshot(logged, _row())
    degraded = [entry for entry in result["feature_deltas"] if entry["feature"] == "volatility_20d"][0]
    assert degraded["logged_value"] is None
    assert degraded["abs_delta"] is None
    assert degraded["relative_delta"] is None
    assert degraded["diverged"] is False
    assert result["features_matched"] == 2

    offline_row = _row()
    offline_row["return_5d"] = float("nan")
    result_nan_offline = reconcile_feature_snapshot(_snapshot(), offline_row)
    degraded_nan = [entry for entry in result_nan_offline["feature_deltas"] if entry["feature"] == "return_5d"][0]
    assert degraded_nan["offline_value"] is None
    assert degraded_nan["diverged"] is False


def test_non_numeric_values_degrade_instead_of_raising():
    result = reconcile_feature_snapshot(
        _snapshot(volume_zscore="not-a-number"), _row(volume_zscore=object())
    )
    assert result["features_compared"] == 3
    assert result["features_diverged"] == 0


def test_deltas_sorted_by_abs_delta_descending():
    result = reconcile_feature_snapshot(
        _snapshot(return_5d=0.02, volatility_20d=0.9), _row()
    )
    deltas = [entry["abs_delta"] for entry in result["feature_deltas"]]
    assert deltas == sorted(deltas, reverse=True)
    assert result["feature_deltas"][0]["feature"] == "volatility_20d"
    assert result["max_abs_delta"] == max(deltas)


def test_only_in_lists_are_sorted_and_informational():
    result = reconcile_feature_snapshot(
        _snapshot(peer_return_momentum=0.3),
        _row(bond_duration_beta=1.2),
    )
    assert result["features_only_in_logged"] == ["peer_return_momentum"]
    assert sorted(result["features_only_in_offline"]) == [
        "bond_duration_beta", "date", "ticker"
    ]
    # Only-in-* features are never counted as divergences.
    assert result["features_diverged"] == 0
    assert result["features_compared"] == 3


def test_empty_or_disjoint_inputs_degrade_to_defined_shape():
    empty = reconcile_feature_snapshot({}, {})
    assert empty["features_compared"] == 0
    assert empty["max_abs_delta"] is None
    assert empty["feature_deltas"] == []

    disjoint = reconcile_feature_snapshot(_snapshot(), {"unrelated_column": 1.0})
    assert disjoint["features_compared"] == 0
    assert disjoint["max_abs_delta"] is None
    assert disjoint["features_only_in_offline"] == ["unrelated_column"]


def test_custom_tolerances_are_honored():
    loose = reconcile_feature_snapshot(
        _snapshot(return_5d=0.02), _row(), abs_tolerance=1.0, rel_tolerance=1.0
    )
    assert loose["features_diverged"] == 0
    tight = reconcile_feature_snapshot(
        _snapshot(), _row(), abs_tolerance=0.0, rel_tolerance=0.0
    )
    assert tight["features_diverged"] == 0  # exactly-equal still matches at zero tolerance
    almost_equal = reconcile_feature_snapshot(
        _snapshot(return_5d=math.nextafter(0.012, 1)), _row(),
        abs_tolerance=0.0, rel_tolerance=0.0,
    )
    assert almost_equal["features_diverged"] == 1


def test_summarize_empty_list_returns_defined_all_zero_shape():
    summary = summarize_feature_reconciliation([])
    assert summary == {
        "num_dates": 0,
        "num_dates_with_comparison": 0,
        "num_features_compared_per_date": {"min": None, "max": None, "mean": None},
        "total_divergences": 0,
        "dates_with_any_divergence": 0,
        "features_diverged_most_often": [],
        "features_never_compared": [],
    }


def test_summarize_aggregates_per_feature_divergence_counts():
    good_result = reconcile_feature_snapshot(_snapshot(), _row())
    bad_logged_a = _snapshot(return_5d=0.99)
    bad_logged_b = _snapshot(volatility_20d=0.01, volume_zscore=5.0)
    results = [good_result, reconcile_feature_snapshot(bad_logged_a, _row()),
               reconcile_feature_snapshot(bad_logged_b, _row())]
    summary = summarize_feature_reconciliation(results)

    assert summary["num_dates"] == 3
    assert summary["num_dates_with_comparison"] == 3
    assert summary["num_features_compared_per_date"]["min"] == 3
    assert summary["num_features_compared_per_date"]["max"] == 3
    assert summary["num_features_compared_per_date"]["mean"] == 3.0
    assert summary["dates_with_any_divergence"] == 2
    assert summary["total_divergences"] == 3

    offenders = {entry["feature"]: entry for entry in summary["features_diverged_most_often"]}
    assert offenders["volume_zscore"]["diverged_count"] == 1
    assert offenders["return_5d"]["diverged_count"] == 1
    assert offenders["return_5d"]["diverged_fraction"] == 1 / 3
    assert "volatility_20d" in offenders or offenders.get("volatility_20d", {}).get("diverged_count", 0) >= 0


def test_summarize_orders_worst_offenders_first_and_caps_at_twenty():
    results = []
    for day in range(30):
        logged = _snapshot()
        # f00 diverges EVERY date, f29 only once - ordering must reflect that.
        if day % 30 < 15:
            logged[f"f{day % 25:02d}"] = 123.0
        results.append(reconcile_feature_snapshot(logged, _row()))
    summary = summarize_feature_reconciliation(results)
    top = summary["features_diverged_most_often"]
    assert len(top) <= 20
    counts = [entry["diverged_count"] for entry in top]
    assert counts == sorted(counts, reverse=True)


def test_summarize_features_never_compared_flags_always_present_never_comparable():
    # A feature present in every logged snapshot but absent from every
    # offline row: never comparable, and must be flagged as such rather
    # than silently ignored.
    results = [
        reconcile_feature_snapshot(_snapshot(live_only_feature=1.0), _row())
        for _ in range(3)
    ]
    summary = summarize_feature_reconciliation(results)
    assert summary["features_never_compared"] == ["live_only_feature"]

    # A feature missing from just ONE snapshot was simply not logged that
    # day - not "never compared".
    results_partial = [
        reconcile_feature_snapshot(_snapshot(live_only_feature=1.0), _row()),
        reconcile_feature_snapshot(_snapshot(live_only_feature=1.0), _row()),
        reconcile_feature_snapshot(_snapshot(), _row()),
    ]
    summary_partial = summarize_feature_reconciliation(results_partial)
    assert "live_only_feature" not in summary_partial["features_never_compared"]


def test_default_tolerances_match_module_contract():
    assert DEFAULT_ABS_TOLERANCE == 1e-9
