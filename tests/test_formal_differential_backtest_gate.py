"""retraining/backtest_gate.py against its Lean 4 model (formal/AetherFormal/BacktestGate.lean)."""

from __future__ import annotations

import math

from aether_quant.formal import load_cases, to_float
from retraining.backtest_gate import compare_backtests

PREFIX = {"threshold_invalid": "min_excess_return_vs_active_invalid", "candidate_missing": "candidate_return_missing",
          "below_threshold": "candidate_excess_return_vs_active_below_threshold"}


def _report(rational) -> dict:
    value = to_float(rational)
    return {"backtest": {"strategy": {"total_return": math.nan if value is None else value}}}


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("backtest_gate")["cases"]):
        given, expected = case["input"], case["expected"]
        threshold = to_float(given["threshold"])
        out = compare_backtests(_report(given["active"]), _report(given["candidate"]),
                                {"min_excess_return_vs_active": math.nan if threshold is None else threshold})
        assert out["passed"] is expected["passed"], index
        if expected["reason"] == "passed":
            assert out["reasons"] == [], index
        else:
            assert out["reasons"][0].startswith(PREFIX[expected["reason"]]), (index, out["reasons"])
