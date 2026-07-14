"""Tests for scripts/profile_inference.py's pure helper functions -
percentile/tail-latency reporting and pre-generation of profiling inputs.
Does not test the harness's `main()`/argparse plumbing or run a real
profiling pass (that's what running the script itself is for) - just the
extracted pure functions that make its numbers trustworthy."""

from scripts.profile_inference import percentile, pregenerate_inputs, summarize_durations


def test_percentile_returns_zero_for_empty_list():
    assert percentile([], 50) == 0.0


def test_percentile_p0_returns_minimum():
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0) == 1.0


def test_percentile_p100_returns_maximum():
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 100) == 5.0


def test_percentile_p50_returns_median_for_odd_length():
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 50) == 3.0


def test_percentile_single_value_returns_that_value_for_any_p():
    assert percentile([7.0], 0) == 7.0
    assert percentile([7.0], 50) == 7.0
    assert percentile([7.0], 99) == 7.0


def test_summarize_durations_empty_list_returns_all_zeros():
    result = summarize_durations([])
    assert result == {"p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "max_ms": 0.0, "mean_ms": 0.0}


def test_summarize_durations_converts_seconds_to_milliseconds():
    # 4 uniform 10ms durations - every percentile and the mean should
    # land at (or extremely near) 10ms.
    durations = [0.010, 0.010, 0.010, 0.010]
    result = summarize_durations(durations)
    for key in ("p50_ms", "p95_ms", "p99_ms", "max_ms", "mean_ms"):
        assert abs(result[key] - 10.0) < 1e-6


def test_summarize_durations_max_is_the_true_maximum_regardless_of_order():
    durations = [0.001, 0.050, 0.002, 0.003]
    result = summarize_durations(durations)
    assert abs(result["max_ms"] - 50.0) < 1e-6


def test_summarize_durations_p99_is_close_to_the_tail_for_skewed_data():
    # 95 uniform fast iterations + 5 slow outliers (nearest-rank p99 of 100
    # sorted values lands on index 98, which falls within the slow tail
    # here - a single-outlier version wouldn't reliably land there, that's
    # an expected property of nearest-rank percentiles, not a bug).
    durations = [0.001] * 95 + [0.100] * 5
    result = summarize_durations(durations)
    assert result["p99_ms"] > result["p50_ms"]
    assert result["mean_ms"] < result["p99_ms"]


def test_pregenerate_inputs_returns_one_pair_per_iteration():
    result = pregenerate_inputs(width=5, sequence_window=3, iterations=4)
    assert len(result) == 4
    for flat_inputs, sequence_inputs in result:
        assert len(flat_inputs) == 5
        assert len(sequence_inputs) == 3
        assert all(len(row) == 5 for row in sequence_inputs)


def test_pregenerate_inputs_is_deterministic_for_a_fixed_seed():
    first = pregenerate_inputs(width=4, sequence_window=2, iterations=3, seed=42)
    second = pregenerate_inputs(width=4, sequence_window=2, iterations=3, seed=42)
    assert first == second


def test_pregenerate_inputs_different_seeds_produce_different_values():
    first = pregenerate_inputs(width=4, sequence_window=2, iterations=3, seed=1)
    second = pregenerate_inputs(width=4, sequence_window=2, iterations=3, seed=2)
    assert first != second


def test_pregenerate_inputs_zero_iterations_returns_empty_list():
    assert pregenerate_inputs(width=5, sequence_window=3, iterations=0) == []
