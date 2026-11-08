"""evaluation/generation_registry.py's R-ADMIT1 (`next_stage`, `share_cap`) against its Lean 4 model (formal/AetherFormal/Admission.lean)."""

from __future__ import annotations

import pytest

from aether_quant.formal import load_cases, to_float
from evaluation.generation_registry import AdmissionEvidence, Generation, next_stage, share_cap

SCORES = {"absent": None, "positive": 0.5, "nonpositive": -0.5, "nan": float("nan")}


def _evidence(given: dict) -> AdmissionEvidence:
    """The float behind each class the model reads: a finite figure past the threshold, or short of it."""
    return AdmissionEvidence(
        selection_pass=given["selection_pass"], hold_pass=given["hold_pass"], edge_pass=given["edge_pass"], holdouts_spent=given["holdouts_spent"], forward_ok_sessions=int(given["forward_ok"]),
        no_data_share=0.05 if given["no_data_ok"] else 0.5, mean_diff_vs_incumbent=0.001 if given["diff_ok"] else -0.001, guard_tripped=given["guard_tripped"], decay_state=given["decay"],
        forward_alpha_t=2.5 if given["alpha_lifted"] else 1.0, score=SCORES[given["score"]],
    )


def test_python_matches_the_lean_model():
    cases = load_cases("admission")["cases"]
    assert len(cases) >= 500
    for index, case in enumerate(cases):
        given = case["input"]
        generation = Generation(id="g", kind="rule", tier=given["tier"], stage=given["stage"], born="2026-11-07", procedure_sha256="p")
        evidence = _evidence(given)
        assert next_stage(generation, evidence) == case["expected"]["stage"], (index, given)
        assert share_cap(generation, evidence, tier2_cap=to_float(given["cap"])) == pytest.approx(to_float(case["expected"]["cap"]), abs=1e-12), (index, given)


def test_the_cases_cover_every_tier_stage_and_class():
    cases = load_cases("admission")["cases"]
    assert {case["input"]["tier"] for case in cases} == {"installed", "tier1", "tier2", "none"}
    assert len({case["input"]["stage"] for case in cases}) == 9
    assert {case["input"]["score"] for case in cases} == set(SCORES) and {case["input"]["decay"] for case in cases} == {"healthy", "watch", "decaying", "dead"}
    assert {case["expected"]["stage"] for case in cases} >= {"ramping", "shadow", "retired", "rejected", "fading", "active"}
