"""portfolio/book_optimizer.drop_classes, class_gross and stress_scaler against their Lean 4 model (formal/AetherFormal/BookGuards.lean), V6.6.10."""

from __future__ import annotations

import pandas as pd
import pytest

from aether_quant.formal import load_cases, to_float
from portfolio.book_optimizer import class_gross, drop_classes, stress_scaler


def _row(pairs):
    return {name: to_float(value) for name, value in pairs}


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("book_guards")["cases"]):
        given, expected = case["input"], case["expected"]
        row = _row(given["row"])
        classes = dict(given["classes"])
        assert drop_classes(row, classes, given["blocked"]) == _row(expected["dropped"]), index
        level = to_float(given["level"])
        ratio = pd.Series({"d": level if level is not None else float("nan")})
        stressed = stress_scaler(ratio, to_float(given["threshold"]), to_float(given["factor"]))("d", row)
        assert list(stressed) == [name for name, _ in expected["stressed"]], index
        assert list(stressed.values()) == pytest.approx(list(_row(expected["stressed"]).values()), abs=1e-12), index
        gross = class_gross(row, classes)
        for name, value in expected["class_gross"]:
            assert gross.get(name, 0.0) == pytest.approx(to_float(value), abs=1e-12), (index, name)
