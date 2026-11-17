"""portfolio/hrp_allocation.py (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from portfolio.hrp_allocation import aligned_returns, build_hrp_allocation, compute_hrp_weights


def _series(seed: int, length: int, scale: float = 0.01) -> list[float]:
    return np.random.default_rng(seed).normal(0.0, scale, length).tolist()


def test_hrp_weights_are_positive_and_sum_to_one():
    returns = pd.DataFrame(np.random.default_rng(5).normal(0, 0.01, (200, 4)), columns=list("ABCD"))
    weights = compute_hrp_weights(returns)
    assert abs(float(weights.sum()) - 1.0) < 1e-9 and (weights > 0).all()


def test_single_linkage_also_sums_to_one_and_an_unknown_method_is_refused():
    returns = pd.DataFrame(np.random.default_rng(6).normal(0, 0.01, (120, 5)), columns=list("ABCDE"))
    weights = compute_hrp_weights(returns, "single")
    assert abs(float(weights.sum()) - 1.0) < 1e-9 and (weights > 0).all()
    with pytest.raises(ValueError, match="unknown linkage"):
        compute_hrp_weights(returns, "centroid-ish")


def test_a_flat_column_is_left_out_instead_of_turning_every_weight_into_nan():
    """#383: 1 / variance of a constant series is infinite, which made the whole result NaN."""
    frame = pd.DataFrame({"A": _series(1, 60), "B": _series(2, 60), "FLAT": [0.0] * 60})
    weights = compute_hrp_weights(frame)
    assert list(weights.index) != [] and "FLAT" not in weights.index
    assert all(math.isfinite(value) for value in weights) and abs(float(weights.sum()) - 1.0) < 1e-9
    only_flat = compute_hrp_weights(pd.DataFrame({"A": _series(3, 30), "FLAT": [0.0] * 30}))
    assert only_flat.to_dict() == {"A": 1.0}
    assert compute_hrp_weights(pd.DataFrame({"FLAT": [0.0] * 30})).empty


def test_histories_of_different_length_are_aligned_at_their_end():
    """#383: crypto has seven bars a week and an equity five, so position i of two windows was a different date."""
    long_history = _series(4, 40)
    mirror = [-value for value in long_history[-20:]]
    frame = aligned_returns({"A": long_history, "B": mirror}, ["A", "B"])
    assert len(frame) == 20
    assert float(frame.corr().loc["A", "B"]) == pytest.approx(-1.0)
    # aligned from the start, as before, the same two series look unrelated
    assert abs(float(pd.DataFrame({"A": long_history[:20], "B": mirror}).corr().loc["A", "B"])) < 0.9


def test_a_history_under_half_the_longest_is_left_out_not_used_to_cut_the_others():
    frame = aligned_returns({"A": _series(1, 40), "B": _series(2, 38), "NEW": _series(3, 5)}, ["A", "B", "NEW", "ABSENT"])
    assert list(frame.columns) == ["A", "B"] and len(frame) == 38
    assert aligned_returns({}, ["A"]).empty
    assert aligned_returns({"A": [0.1]}, ["A"]).empty


def test_a_name_hrp_could_not_estimate_gets_its_legs_mean_weight():
    """#383: it used to get a silent zero while the docstring promised the selected set is covered."""
    returns = {"A": _series(1, 60), "B": _series(2, 60, 0.03), "NEW": _series(3, 4), "FLAT": [0.0] * 60, "S1": _series(5, 60), "S2": _series(6, 60)}
    weights = build_hrp_allocation(returns, selected_tickers_long=["A", "B", "NEW", "FLAT"], selected_tickers_short=["S1", "S2"], gross_exposure=1.0)
    assert set(weights) == {"A", "B", "NEW", "FLAT", "S1", "S2"}
    assert sum(weights[name] for name in ("A", "B", "NEW", "FLAT")) == pytest.approx(0.5)
    assert sum(weights[name] for name in ("S1", "S2")) == pytest.approx(-0.5)
    assert weights["NEW"] == pytest.approx(weights["FLAT"]) == pytest.approx((weights["A"] + weights["B"]) / 2.0)
    assert weights["A"] > weights["B"] > 0.0  # the calmer name still gets more


def test_a_leg_hrp_estimated_nothing_for_is_equal_weighted():
    returns = {"A": _series(1, 60), "B": _series(2, 60), "S1": [0.0] * 60, "S2": _series(4, 3)}
    weights = build_hrp_allocation(returns, selected_tickers_long=["A", "B"], selected_tickers_short=["S1", "S2"], gross_exposure=2.0)
    assert weights["S1"] == pytest.approx(-0.5) and weights["S2"] == pytest.approx(-0.5)
    assert weights["A"] + weights["B"] == pytest.approx(1.0)


def test_the_linkage_method_reaches_the_estimate():
    returns = {name: _series(index, 80, 0.01 * (1 + index % 3)) for index, name in enumerate("ABCDEF")}
    ward = build_hrp_allocation(returns, selected_tickers_long=list("ABCDEF"), selected_tickers_short=[])
    single = build_hrp_allocation(returns, selected_tickers_long=list("ABCDEF"), selected_tickers_short=[], linkage_method="single")
    assert sum(ward.values()) == pytest.approx(1.0) and sum(single.values()) == pytest.approx(1.0)
    # an unknown method raises inside the estimate, and the book falls back to equal weight rather than failing mid-bar
    fallback = build_hrp_allocation(returns, selected_tickers_long=list("ABCDEF"), selected_tickers_short=[], linkage_method="nope")
    assert all(value == pytest.approx(1.0 / 6.0) for value in fallback.values())


@settings(max_examples=60, deadline=None, derandomize=True)
@given(
    lengths=st.lists(st.integers(min_value=0, max_value=45), min_size=1, max_size=8),
    shorts=st.integers(min_value=0, max_value=4),
    flat=st.booleans(),
    gross=st.floats(min_value=0.1, max_value=3.0),
)
def test_every_selected_name_gets_a_finite_weight_and_each_leg_sums_to_its_total(lengths, shorts, flat, gross):
    names = [f"N{index}" for index in range(len(lengths))]
    returns = {name: _series(index + 11, length) for index, (name, length) in enumerate(zip(names, lengths, strict=True))}
    if flat:
        returns[names[0]] = [0.0] * max(lengths[0], 3)
    short_names = names[:min(shorts, len(names) - 1)]
    long_names = [name for name in names if name not in short_names]
    weights = build_hrp_allocation(returns, selected_tickers_long=long_names, selected_tickers_short=short_names, gross_exposure=gross)
    assert set(weights) == set(names)
    assert all(math.isfinite(value) for value in weights.values())
    long_total = gross / 2.0 if short_names else gross
    assert sum(weights[name] for name in long_names) == pytest.approx(long_total)
    assert all(weights[name] > 0.0 for name in long_names)
    if short_names:
        assert sum(weights[name] for name in short_names) == pytest.approx(-gross / 2.0)
        assert all(weights[name] < 0.0 for name in short_names)
