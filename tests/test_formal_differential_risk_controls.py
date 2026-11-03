"""risk_controls.py against its Lean 4 model (formal/AetherFormal/RiskControls.lean)."""

from __future__ import annotations

import pytest

from aether_quant.formal import load_cases, to_float
from risk_controls import assess_drawdown_lock, cap_target_weight


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("risk_controls")["cases"]):
        given, expected = case["input"], case["expected"]
        if case["kind"] == "cap_target_weight":
            weight, blocked = cap_target_weight(to_float(given["target"]), to_float(given["current"]), to_float(given["cap"]))
            assert weight == pytest.approx(to_float(expected["weight"]), abs=1e-12), index
            assert blocked == expected["blocked"], index
        else:
            locked = assess_drawdown_lock(to_float(given["daily"]), to_float(given["total"]), to_float(given["max_daily"]),
                                          to_float(given["max_total"]))
            assert locked == (expected["locked"], expected["reason"]), index
