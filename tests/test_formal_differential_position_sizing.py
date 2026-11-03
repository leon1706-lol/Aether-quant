"""risk/position_sizing.py against its Lean 4 model (formal/AetherFormal/PositionSizing.lean). The rolling volatility
equals the target volatility, so the volatility multiplier is 1 and the product is confidence x rank."""

from __future__ import annotations

import pytest

from aether_quant.formal import load_cases, to_float
from risk.position_sizing import build_dynamic_position_sizing, rank_sizing_multiplier


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("position_sizing")["cases"]):
        given, expected = case["input"], case["expected"]
        rank, lo, hi = (to_float(given[key]) for key in ("predicted_rank_20d", "min_rank_multiplier", "max_rank_multiplier"))
        assert rank_sizing_multiplier(rank, True, lo, hi)[0] == pytest.approx(to_float(expected["rank_multiplier"])), index
        decision = build_dynamic_position_sizing(
            to_float(given["base_target_weight"]), to_float(given["confidence"]), 0.015, to_float(given["max_position_weight"]),
            target_daily_volatility=0.015, min_position_weight=to_float(given["min_position_weight"]),
            predicted_rank_20d=rank, rank_sizing_enabled=True, min_rank_multiplier=lo, max_rank_multiplier=hi,
        )
        assert decision.target_weight == pytest.approx(to_float(expected["target_weight"]), abs=1e-12, rel=1e-9), index
