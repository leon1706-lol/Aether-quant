"""portfolio/generation_blend.py against its Lean 4 model (formal/AetherFormal/GenerationBlend.lean)."""

from __future__ import annotations

import pytest

from aether_quant.formal import load_cases, to_float
from portfolio.generation_blend import GlidePolicy, update_generation_shares


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("generation_blend")["cases"]):
        given = case["input"]
        policy = GlidePolicy(glide_sessions=int(given["glide_sessions"]), entry_share=to_float(given["entry_share"]), retire_share=to_float(given["retire_share"]))
        out = update_generation_shares(
            {"old": to_float(given["old"]), "new": to_float(given["new"])}, {"old": "active", "new": "ramping"}, {}, {"new": to_float(given["cap"])}, policy,
        )
        assert out["old"] == pytest.approx(to_float(case["expected"]["old"]), abs=1e-9), index
        assert out["new"] == pytest.approx(to_float(case["expected"]["new"]), abs=1e-9), index
