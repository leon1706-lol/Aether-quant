"""portfolio/generation_blend.py's dynamic targets and share repair against their Lean 4 model (formal/AetherFormal/DynamicTargets.lean)."""

from __future__ import annotations

import math

import pytest

from aether_quant.formal import load_cases, to_float
from portfolio.generation_blend import GlidePolicy, dynamic_targets, repair_shares


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("dynamic_targets")["cases"]):
        given, expected = case["input"], case["expected"]
        if case["kind"] == "targets":
            policy = GlidePolicy(mode="dynamic", score_floor=to_float(given["score_floor"]), max_generations=given["max_generations"])
            scores = {name: to_float(value) for name, value in given["scores"].items()}
            caps = {name: to_float(value) for name, value in given["caps"].items()}
            out = dynamic_targets(scores, caps, policy)
            assert set(out) == set(expected["targets"]), index
            for name, value in expected["targets"].items():
                assert out[name] == pytest.approx(to_float(value), abs=1e-9), (index, name)
        else:
            shares = {f"g{i}": (math.nan if value is None else to_float(value)) for i, value in enumerate(given["shares"])}
            out = repair_shares(shares)
            assert list(out.values()) == pytest.approx([to_float(value) for value in expected["shares"]], abs=1e-12), index
