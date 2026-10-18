"""Tests for scripts/build_trial_registry.py (V6.3.0): every backtest-split median Sharpe in a research payload is a trial,
a summary re-scored verbatim in a later stage counts once."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("_build_trial_registry", ROOT / "scripts" / "build_trial_registry.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _summary(value: float) -> dict:
    return {"validation": {"median_net_sharpe": value - 1.0}, "backtest": {"median_net_sharpe": value, "phases": 10}}


def test_collect_trials_walks_every_variant_and_skips_validation():
    registry = _load()
    payload = {"book": {"base": {"ungated": _summary(0.74)}, "K1": {"ungated": _summary(0.84)}}, "branch": "B"}
    trials = registry.collect_trials(payload, "v610")
    assert sorted((trial["trial"], trial["median_sharpe"]) for trial in trials) == [
        ("book/K1/ungated", 0.84), ("book/base/ungated", 0.74)]
    assert all(trial["split"] == "backtest" and trial["phase"] == "v610" for trial in trials)


def test_the_same_score_in_two_stages_is_one_trial(tmp_path):
    registry = _load()
    (tmp_path / "v610").mkdir()
    (tmp_path / "v610" / "research.json").write_text(json.dumps({
        "head": {"base": {"ungated": _summary(0.74)}, "H1": {"ungated": _summary(0.25)}},
        "book": {"base": {"ungated": _summary(0.74)}},
    }), encoding="utf-8")
    (tmp_path / "v620").mkdir()
    (tmp_path / "v620" / "research.json").write_text(json.dumps({"stagger": {"S2": {"ungated": _summary(1.26)}}}), encoding="utf-8")
    built = registry.build_registry(tmp_path)
    assert built["num_trials"] == 3
    assert built["sources"] == ["v610/research.json", "v620/research.json"]
