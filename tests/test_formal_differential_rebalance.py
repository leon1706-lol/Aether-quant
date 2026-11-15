"""portfolio/target_weights.py's rebalance_deltas against its Lean 4 model (formal/AetherFormal/Rebalance.lean).

Ticker "A" is a fixed purchase that is never a reduction; the case's ticker "B" sorts before it exactly when the model
calls B's order a reduction."""

from __future__ import annotations

import pytest

from aether_quant.formal import load_cases, to_float
from portfolio.target_weights import TargetWeightsConfig, rebalance_deltas


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("rebalance")["cases"]):
        given, expected = case["input"], case["expected"]
        config = TargetWeightsConfig(min_weight_change=to_float(given["min_weight_change"]), min_trade_usd=to_float(given["min_trade_usd"]))
        held = {"B": to_float(given["held"])}
        prices = {"A": 1.0, "B": to_float(given["unit"])}
        nav = to_float(given["nav"])
        target = {"A": 0.5}
        wanted = to_float(given["wanted"])
        if wanted != 0.0:
            target["B"] = wanted
        orders = rebalance_deltas(held, prices, nav, target, config, lot_size={"B": to_float(given["lot"])})
        by_ticker = dict(orders)
        assert by_ticker["A"] == nav * 0.5, index
        delta = to_float(expected["delta"])
        if delta is None:
            assert "B" not in by_ticker, (index, orders)
            continue
        assert by_ticker["B"] == pytest.approx(delta, abs=1e-9), index
        assert (orders[0][0] == "B") is expected["reduces"], (index, orders)
