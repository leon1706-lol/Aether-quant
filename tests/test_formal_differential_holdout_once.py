"""evaluation/research_cells.py's `record_holdout_read` against its Lean 4 model (formal/AetherFormal/HoldoutOnce.lean): a holdout cell is read once."""

from __future__ import annotations

import json

import pytest

from aether_quant.formal import load_cases
from evaluation.research_cells import record_holdout_read


def _cells_in(path) -> list[str]:
    if not path.exists():
        return []
    return [cell for line in path.read_text(encoding="utf-8").splitlines() if line.strip() for cell in json.loads(line)["cells"]]


def test_python_matches_the_lean_model(tmp_path):
    cases = load_cases("holdout_once")["cases"]
    assert len(cases) >= 200
    for index, case in enumerate(cases):
        given = case["input"]
        path = tmp_path / f"ledger_{index}.jsonl"
        if given["ledger"]:
            path.write_text(json.dumps({"candidate": "earlier", "cells": given["ledger"], "digest": "d", "created_at": "t"}) + "\n", encoding="utf-8")
        if case["expected"]["refused"]:
            with pytest.raises(PermissionError):
                record_holdout_read(path, candidate="c", cells=tuple(given["cells"]), digest="d", created_at="t")
            assert _cells_in(path) == given["ledger"], (index, "a refused read writes nothing")
        else:
            record_holdout_read(path, candidate="c", cells=tuple(given["cells"]), digest="d", created_at="t")
            assert _cells_in(path) == case["expected"]["ledger"], (index, given)


def test_the_cases_cover_refusals_and_successes_and_a_non_empty_ledger():
    cases = load_cases("holdout_once")["cases"]
    assert any(case["expected"]["refused"] for case in cases) and any(not case["expected"]["refused"] for case in cases)
    assert any(case["input"]["ledger"] and not case["expected"]["refused"] for case in cases)
