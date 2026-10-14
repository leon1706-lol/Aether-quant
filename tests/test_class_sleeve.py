"""portfolio/class_sleeve.py (V5.8.0): generic asset-class sleeves (forex, bonds)."""

from __future__ import annotations

import pytest

from portfolio.book_construction import BookAllocation
from portfolio.class_sleeve import (
    ClassSleeveConfig,
    build_class_sleeve_weights,
    resize_below_minimum,
    resolve_class_sleeve_config,
    sleeve_classes_out_of_main_pool,
)
from portfolio.forex_sleeve import build_forex_sleeve_weights


def _allocation(role: str, rank: float) -> BookAllocation:
    return BookAllocation(role=role, book_role_multiplier=1.0 if role == "long" else -1.0, predicted_rank_20d=rank, book_reason="test")


def test_resolve_defaults_to_disabled_and_reads_the_forex_style_key_names():
    assert not resolve_class_sleeve_config("bond", None).enabled
    config = resolve_class_sleeve_config("bond", {"enabled": True, "per_side": 3, "gross_budget": 0.2, "max_weight_per_pair": 0.05})
    assert config == ClassSleeveConfig(asset_class="bond", enabled=True, per_side=3, gross_budget=0.2, max_weight_per_name=0.05)


def test_weights_split_each_leg_half_the_budget_and_respect_the_cap():
    allocations = {"TLT": _allocation("long", 0.9), "IEF": _allocation("long", 0.8), "HYG": _allocation("short", 0.1)}
    weights = build_class_sleeve_weights(allocations, 0.2)
    assert weights == {"TLT": pytest.approx(0.05), "IEF": pytest.approx(0.05), "HYG": pytest.approx(-0.1)}
    capped = build_class_sleeve_weights(allocations, 0.2, 0.06)
    assert capped["HYG"] == pytest.approx(-0.06)


def test_one_sided_or_unfunded_sleeve_is_empty():
    assert build_class_sleeve_weights({"TLT": _allocation("long", 0.9)}, 0.2) == {}
    assert build_class_sleeve_weights({"TLT": _allocation("long", 0.9), "HYG": _allocation("short", 0.1)}, 0.0) == {}


def test_forex_wrapper_is_the_generic_function():
    allocations = {"EURUSD": _allocation("long", 0.9), "USDJPY": _allocation("short", 0.1)}
    assert build_forex_sleeve_weights(allocations, 0.3) == build_class_sleeve_weights(allocations, 0.3)


def test_resize_deadband_and_pool_exclusion():
    assert resize_below_minimum(10, 1.1, 2500.0) and not resize_below_minimum(10, 1.1, 0.0)
    assert resize_below_minimum(float("nan"), 1.0, 100.0)
    configs = {"forex": ClassSleeveConfig("forex", enabled=True), "bond": ClassSleeveConfig("bond", enabled=True)}
    assert sleeve_classes_out_of_main_pool(configs, {"forex": False}) == frozenset({"bond"})
