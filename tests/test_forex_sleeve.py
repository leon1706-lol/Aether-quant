"""portfolio/forex_sleeve.py (V5.7.0): the shared sleeve weights and the dollar deadband."""

import pytest

from portfolio.book_construction import BookAllocation
from portfolio.forex_sleeve import build_forex_sleeve_weights, forex_resize_below_minimum


def _allocation(role):
    return BookAllocation(role=role, book_role_multiplier=1.0, predicted_rank_20d=0.9 if role == "long" else 0.1, book_reason="test")


def test_each_leg_gets_half_the_gross_budget_split_evenly_and_the_sleeve_is_dollar_neutral():
    allocations = {"EURUSD": _allocation("long"), "GBPUSD": _allocation("long"), "USDJPY": _allocation("short"), "AUDUSD": _allocation("short")}
    weights = build_forex_sleeve_weights(allocations, 0.4)
    assert weights == {"EURUSD": 0.1, "GBPUSD": 0.1, "USDJPY": -0.1, "AUDUSD": -0.1}
    assert sum(weights.values()) == pytest.approx(0.0)
    assert sum(abs(w) for w in weights.values()) == pytest.approx(0.4)


def test_per_pair_cap_binds_and_uneven_legs_still_spend_their_own_half_budget():
    allocations = {"EURUSD": _allocation("long"), "USDJPY": _allocation("short"), "AUDUSD": _allocation("short")}
    weights = build_forex_sleeve_weights(allocations, 0.4)
    assert weights["EURUSD"] == pytest.approx(0.2) and weights["USDJPY"] == pytest.approx(-0.1)
    capped = build_forex_sleeve_weights(allocations, 0.4, max_weight_per_pair=0.12)
    assert capped["EURUSD"] == pytest.approx(0.12) and capped["USDJPY"] == pytest.approx(-0.1)


def test_one_sided_empty_or_unfunded_sleeves_are_empty():
    only_longs = {"EURUSD": _allocation("long"), "GBPUSD": _allocation("long")}
    assert build_forex_sleeve_weights(only_longs, 0.4) == {}
    assert build_forex_sleeve_weights({}, 0.4) == {}
    both = {"EURUSD": _allocation("long"), "USDJPY": _allocation("short")}
    for budget in (0.0, -0.1, float("nan"), float("inf")):
        assert build_forex_sleeve_weights(both, budget) == {}


def test_resize_deadband_is_in_dollars_not_a_fraction_of_the_position():
    assert forex_resize_below_minimum(1_000, 1.10, 2_500.0) is True  # $1,100 < $2,500
    assert forex_resize_below_minimum(3_000, 1.10, 2_500.0) is False  # $3,300
    assert forex_resize_below_minimum(-1_000, 1.10, 2_500.0) is True  # sign does not matter
    assert forex_resize_below_minimum(1, 1.10, 0.0) is False  # disabled
    assert forex_resize_below_minimum(float("nan"), 1.10, 2_500.0) is True

