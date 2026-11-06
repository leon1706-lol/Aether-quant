"""execution/order_gate.py against its Lean 4 model (formal/AetherFormal/OrderGate.lean)."""

from __future__ import annotations

import pytest

from aether_quant.formal import load_cases, to_float
from execution.order_gate import (
    resolve_cash_sweep_order_permission,
    resolve_order_permission,
    resolve_risk_exit_permission,
    resolve_runtime_mode,
    resolve_slippage_bps,
    slippage_amount,
)


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("order_gate")["cases"]):
        given, expected = case["input"], case["expected"]
        if case["kind"] == "permission":
            mode = given["mode"]
            flags = (given["allow_live_orders"], given["broker_config_present"])
            assert resolve_order_permission(mode, *flags, given["risk_locks_healthy"]) == (
                expected["permitted"], expected["reason"]), index
            assert resolve_cash_sweep_order_permission(mode, *flags) == (
                expected["cash_sweep_permitted"], expected["cash_sweep_reason"]), index
            assert resolve_risk_exit_permission(mode, *flags) == (
                expected["risk_exit_permitted"], expected["risk_exit_reason"]), index
        elif case["kind"] == "runtime_mode":
            assert resolve_runtime_mode(given["raw"]) == expected["mode"], index
        else:
            raw = to_float(given["raw_bps"])
            by_symbol = {} if raw is None else {"X": raw}
            bps = resolve_slippage_bps("X", by_symbol, to_float(given["max_bps"]))
            assert bps == pytest.approx(to_float(expected["bps"]), abs=1e-12), index
            amount = slippage_amount(to_float(given["price"]), bps)
            assert amount == pytest.approx(to_float(expected["amount"]), abs=1e-12, rel=1e-9), index
