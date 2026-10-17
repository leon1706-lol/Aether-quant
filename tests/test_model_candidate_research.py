"""scripts/model_candidate_research.py (V6.1.0, rules R-MODEL9 / R-HEAD2): candidate specs and the live decision blend."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("model_candidate_research", ROOT / "scripts" / "model_candidate_research.py")
research = importlib.util.module_from_spec(spec)
spec.loader.exec_module(research)


def test_candidate_spec():
    name, members = research.parse_candidate("ctl=multitask:a,b;sequence:c")
    assert name == "ctl" and members == {"multitask": ["a", "b"], "sequence": ["c"]}
    with pytest.raises(ValueError):
        research.parse_candidate("bad=nothing:a")


def test_the_decision_blend_prefers_the_first_model_per_head_and_reweights_missing_heads():
    nan = np.nan
    predictions = {
        "sequence": {"rank_5d": np.array([0.2, nan, nan]), "rank_20d": np.array([0.4, 0.6, nan])},
        "multitask": {"rank_5d": np.array([0.9, 0.1, nan]), "rank_20d": np.array([0.9, 0.9, 0.3])},
    }
    score = research.blend_decision_score(predictions, {"rank_5d": 0.5, "rank_20d": 0.5}, ["sequence", "multitask"])
    # row 0: both heads from sequence; row 1: rank_5d falls back to multitask; row 2: only rank_20d exists
    np.testing.assert_allclose(score, [0.3, 0.35, 0.3])
