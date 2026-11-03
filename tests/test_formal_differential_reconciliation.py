"""execution/reconciliation.py against its Lean 4 model (formal/AetherFormal/Reconciliation.lean)."""

from __future__ import annotations

import pytest

from aether_quant.formal import load_cases, to_float
from execution.reconciliation import reconcile_positions


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("reconciliation")["cases"]):
        given, expected = case["input"], case["expected"]
        expected_by, actual_by = {}, {}
        for row in given["rows"]:
            if row["expected"] is not None:
                expected_by[f"N{row['sym']}"] = to_float(row["expected"])
            if row["actual"] is not None:
                actual_by[f"N{row['sym']}"] = to_float(row["actual"])
        report = reconcile_positions(expected_by, actual_by, weight_tolerance=to_float(given["weight_tolerance"]),
                                     value_tolerance_usd=to_float(given["value_tolerance_usd"]),
                                     portfolio_value=to_float(given["portfolio_value"]))
        classes = {symbol: "matched" for symbol in report.matched}
        for name in ("drifted", "orphan_broker", "missing_broker"):
            classes.update({entry["symbol"]: name for entry in getattr(report, name)})
        for row, want in zip(given["rows"], expected["classes"]):
            assert classes[f"N{row['sym']}"] == want, (index, row["sym"])
        assert report.max_abs_weight_drift == pytest.approx(to_float(expected["max_abs_weight_drift"]), abs=1e-12), index
