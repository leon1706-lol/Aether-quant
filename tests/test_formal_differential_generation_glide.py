"""portfolio/generation_blend.py's dynamic glide against its Lean 4 model (formal/AetherFormal/GenerationGlide.lean)."""

from __future__ import annotations

import pytest

from aether_quant.formal import load_cases, to_float
from portfolio.generation_blend import shrunk_sharpe, step_toward


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("generation_glide")["cases"]):
        given = case["input"]
        out = step_toward({"g": to_float(given["share"])}, {"g": to_float(given["target"])}, to_float(given["fraction"]), to_float(given["retire_share"]))
        assert out["g"] == pytest.approx(to_float(case["expected"]["share"]), abs=1e-9), index
        score = shrunk_sharpe(to_float(given["observed"]), int(given["sessions"]), to_float(given["prior"]), float(given["prior_sessions"]))
        assert score == pytest.approx(to_float(case["expected"]["score"]), abs=1e-9), index
