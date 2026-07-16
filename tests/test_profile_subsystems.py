"""Tests for scripts/profile_subsystems.py's pure build_*_workload()/
run_*_workload() helpers - shape/length/non-negativity only, using a tiny
iteration count (not a real 200+-iteration profiling run, which is what
running the script itself is for). Does not test main()/argparse
plumbing or a real profiling pass, matching tests/test_profile_inference.py's
own scope."""

from scripts.profile_subsystems import (
    build_analyzer_workload,
    build_gating_workload,
    build_indicators_workload,
    build_learned_topology_workload,
    build_liquidity_workload,
    build_regime_workload,
    build_topology_cache_workload,
    build_topology_workload,
    run_analyzer_workload,
    run_gating_workload,
    run_indicators_workload,
    run_learned_topology_workload,
    run_liquidity_workload,
    run_regime_workload,
    run_topology_cache_workload,
    run_topology_workload,
)

_N = 3  # keep the test suite fast - shape/non-negativity only, not real percentile stats


def _assert_non_negative_durations(durations: list[float], expected_length: int) -> None:
    assert len(durations) == expected_length
    assert all(d >= 0.0 for d in durations)


def test_regime_workload_shape_and_durations():
    workload = build_regime_workload(_N)
    assert len(workload) == _N
    assert all(set(item.keys()) == {"momentum_5d", "momentum_20d", "rolling_volatility_20d", "drawdown_20d", "average_correlation"} for item in workload)
    _assert_non_negative_durations(run_regime_workload(workload), _N)


def test_topology_workload_shape_and_durations():
    workload = build_topology_workload(_N, n_symbols=5)
    assert len(workload) == _N
    assert len(workload[0]["returns_by_symbol"]) == 5
    _assert_non_negative_durations(run_topology_workload(workload), _N)


def test_topology_cache_workload_shape_and_durations():
    workload = build_topology_cache_workload(_N, n_symbols=5)
    assert len(workload) == _N
    assert len(workload[0]["returns_by_symbol"]) == 5
    _assert_non_negative_durations(run_topology_cache_workload(workload), _N)


def test_topology_cache_workload_returns_drift_instead_of_resampling_independently():
    """The whole point of this workload (vs. build_topology_workload()) is
    that consecutive iterations' returns are related, not independently
    redrawn - lock that in directly, not just via the shape test above."""
    workload = build_topology_cache_workload(5, n_symbols=3, seed=7)
    first_symbol = next(iter(workload[0]["returns_by_symbol"]))
    # Each iteration's series is the previous one's window slid by one -
    # only the newest value is new, everything else shifts by one
    # position - so iteration N's series[1:] always equals iteration
    # (N+1)'s series[:-1], regardless of how the new value itself was
    # generated (factor-model here, vs. build_topology_workload()'s fresh
    # independent draw every iteration).
    series_a = workload[0]["returns_by_symbol"][first_symbol]
    series_b = workload[1]["returns_by_symbol"][first_symbol]
    assert series_a[1:] == series_b[:-1]


def test_learned_topology_workload_shape_and_durations():
    workload = build_learned_topology_workload(_N, n_symbols=5)
    assert len(workload) == _N
    assert "deterministic_topology" in workload[0]
    assert len(workload[0]["symbol_features"]) == 5
    _assert_non_negative_durations(run_learned_topology_workload(workload), _N)


def test_liquidity_workload_shape_and_durations():
    workload = build_liquidity_workload(_N)
    assert len(workload) == _N
    _assert_non_negative_durations(run_liquidity_workload(workload), _N)


def test_gating_workload_shape_and_durations():
    workload = build_gating_workload(_N)
    assert len(workload) == _N
    assert set(workload[0]["expert_probabilities"].keys()) == {"bullish", "bearish", "sideways", "volatility"}
    _assert_non_negative_durations(run_gating_workload(workload), _N)


def test_analyzer_workload_shape_and_durations():
    workload = build_analyzer_workload(_N)
    assert len(workload) == _N
    _assert_non_negative_durations(run_analyzer_workload(workload), _N)


def test_indicators_workload_shape_and_durations():
    workload = build_indicators_workload(_N)
    assert len(workload) == _N
    result = run_indicators_workload(workload)
    assert set(result.keys()) == {
        "relative_strength_index", "average_true_range_pct", "bollinger_pctb", "volume_zscore",
        "cross_sectional_momentum_rank", "macd_histogram_normalized", "distance_from_52w_high",
    }
    for durations in result.values():
        _assert_non_negative_durations(durations, _N)
