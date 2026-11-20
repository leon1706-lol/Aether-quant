"""evaluation/premia_research.passes_sharpe_clauses against its Lean 4 model (formal/AetherFormal/SharpeClauses.lean), V6.6.10."""

from __future__ import annotations

from aether_quant.formal import load_cases, to_float
from evaluation.premia_research import passes_sharpe_clauses


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("sharpe_clauses")["cases"]):
        given = case["input"]
        score = {key: to_float(given[key]) for key in ("sharpe", "sharpe_first_half", "sharpe_second_half")}
        assert passes_sharpe_clauses(score, half_floor=to_float(given["half_floor"]), pooled_floor=to_float(given["pooled_floor"])) is case["expected"]["passes"], index
