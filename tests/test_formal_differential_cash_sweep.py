"""portfolio/cash_sweep.py and class_sleeve.resize_below_minimum against their Lean 4 model (formal/AetherFormal/CashSweep.lean)."""

from __future__ import annotations

import math

import pytest

from aether_quant.formal import load_cases, to_float
from portfolio.cash_sweep import advance_strategy_value, cash_sweep_target_weight
from portfolio.class_sleeve import resize_below_minimum


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("cash_sweep")["cases"]):
        given, expected = case["input"], case["expected"]
        value = {key: to_float(item) if isinstance(item, dict) else item for key, item in given.items()}
        if case["kind"] == "target":
            config = {"margin_leverage": value["leverage"], "margin_buffer": value["margin_buffer"], "cash_buffer": value["cash_buffer"], "max_weight": value["max_weight"]}
            reserve = {"long": value["reserve_long"], "short": value["reserve_short"], "margin": value["reserve_margin"]}
            weight = cash_sweep_target_weight(long_weight=value["long"], short_weight=value["short"], margin_used=value["margin"], reserve=reserve, config=config)
            assert weight == pytest.approx(to_float(expected["weight"]), abs=1e-12), index
        elif case["kind"] == "advance":
            state = {"total": value["state_total"], "sweep": value["state_sweep"], "value": value["value"]}
            _, out = advance_strategy_value(state, value["total"], value["sweep"])
            assert out == pytest.approx(to_float(expected["value"]), abs=1e-9), index
        else:
            minimum = given["min_trade_usd"]
            below = resize_below_minimum(value["delta"], value["price"], math.nan if minimum is None else to_float(minimum))
            assert below is expected["below"], index
