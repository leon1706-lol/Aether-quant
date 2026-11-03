"""execution/cost_model.py against its Lean 4 model (formal/AetherFormal/CostModel.lean)."""

from __future__ import annotations

import pytest

from aether_quant.formal import load_cases, to_float
from execution.cost_model import estimate_round_trip_cost_bps, expected_edge_bps, expected_fill_fee_bps


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("cost_model")["cases"]):
        given, expected = case["input"], case["expected"]
        if case["kind"] == "fill_fee":
            actual = expected_fill_fee_bps(given["is_limit_route"], to_float(given["fill_rate"]), to_float(given["maker_bps"]),
                                           to_float(given["taker_bps"]))
            want = expected["fee_bps"]
        elif case["kind"] == "round_trip":
            actual = estimate_round_trip_cost_bps(
                {"estimated_round_trip_cost": to_float(given["liquidity_fraction"])},
                commission_bps_per_side=to_float(given["commission_bps_per_side"]),
                min_commission_usd=to_float(given["min_commission_usd"]), order_value=to_float(given["order_value"]),
                extra_slippage_bps=to_float(given["extra_slippage_bps"]),
            )
            want = expected["cost_bps"]
        else:
            actual = expected_edge_bps(to_float(given["rank"]), edge_bps_per_rank_unit=to_float(given["edge_bps_per_rank_unit"]),
                                       holding_bars=given["holding_bars"], horizon_days=given["horizon_days"],
                                       trade_direction=given["trade_direction"])
            want = expected["edge_bps"]
        assert actual == pytest.approx(to_float(want), abs=1e-9, rel=1e-9), index
