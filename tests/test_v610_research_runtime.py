"""scripts/v610_research.py's runtime (V6.6.6, #359): the phase worker, the pool and the whole rule chain (model, head, book, costs, legacy, gate and the
final holdout look) on the synthetic as-live harness, for both calibration branches."""

from __future__ import annotations

import json
import multiprocessing
import sys
from types import SimpleNamespace

import pytest

import research_fakes
from script_loader import load_script


@pytest.fixture
def research(monkeypatch):
    research_fakes.install(monkeypatch)
    return load_script("v610_research")


def _entry(validation, backtest, members=()):
    keys = ("decision_rank_20d", "decision_rank_20d_swapped_priority")
    return {
        "ensemble": {"validation": {**{key: {"non_overlapping_mean_ic": validation[key]} for key in keys}, "multitask.rank_20d": {"daily_mean_ic": 0.04}, "sequence.rank_20d": {"daily_mean_ic": 0.01},
                                    "sequence.rank_5d": {"daily_mean_ic": -0.01}, "nodot": {}, "multitask.off": {"daily_mean_ic": 0.5}},
                     "backtest": {key: {"daily_mean_ic": backtest, "hac_t": 3.0} for key in keys}},
        "members_scored": {f"m{index}": {"validation": {"decision_rank_20d": {"non_overlapping_mean_ic": value}, "decision_rank_20d_swapped_priority": {"non_overlapping_mean_ic": value}}}
                           for index, value in enumerate(members)},
    }


MODEL_IC = {"candidates": {
    "installed": _entry({"decision_rank_20d": 0.02, "decision_rank_20d_swapped_priority": 0.01}, 0.02, members=(0.01, 0.02)),
    "ctl": _entry({"decision_rank_20d": 0.02, "decision_rank_20d_swapped_priority": 0.01}, 0.02, members=(0.01, 0.02)),
    "cand": _entry({"decision_rank_20d": 0.20, "decision_rank_20d_swapped_priority": 0.05}, 0.1),
    "swap": _entry({"decision_rank_20d": 0.05, "decision_rank_20d_swapped_priority": 0.30}, 0.1),
}}
CANDIDATES = {
    "installed": {"passing_heads": ["rank_20d", "rank_5d"]},
    "cand": {"ic_pass": True, "decision_heads_pass_r_head": True, "latency_ratio": 1.0, "ml_dir": "ml/versions/x", "ensemble": True, "passing_heads": ["rank_20d"]},
    "swap": {"ic_pass": True, "decision_heads_pass_r_head": True, "latency_ratio": 2.0},
    "bad": {"ic_pass": False, "ic_checks": {"validation_beats_control_by_seed_spread": False}},
}


def test_a_phase_scores_with_or_without_the_gate_and_the_pool_is_linux_only(research, monkeypatch):
    harness = research_fakes.FakeHarness()
    research._JOB.clear()
    research._JOB.update(harness=harness, mechanisms={}, resolved={"a": 1}, mode="ungated")
    summary = research._phase_worker(0)
    assert summary["legacy_net_return"] > 0 and harness.calls[-1]["gate"] == "off"
    research._JOB.update(mode="as_live", resolved={})
    research._phase_worker(1)
    assert "gate" not in harness.calls[-1] and len(research.map_phases([0, 1], workers=1)) == 2

    class Pool:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def map(self, function, items):
            return [function(item) for item in items]

    monkeypatch.setattr(multiprocessing, "get_context", lambda kind: SimpleNamespace(Pool=lambda count: Pool()))
    monkeypatch.setattr(sys, "platform", "linux")
    assert len(research.map_phases([0, 1], workers=2)) == 2
    research._JOB.clear()


def _run(research, monkeypatch, tmp_path, *, branch, stages, adopt=False, candidates=CANDIDATES):
    paths = {name: tmp_path / name for name in ("candidates.json", "ic.json", "research.json")}
    paths["candidates.json"].write_text(json.dumps(candidates), encoding="utf-8")
    paths["ic.json"].write_text(json.dumps(MODEL_IC), encoding="utf-8")
    if adopt:
        monkeypatch.setattr(research, "decide", lambda base, variant, branch, extra_checks=None: {"ungated": {"backtest_gain": 0.5, "validation_change": 0.1, "phase_share": {}}, "adopted": True})
    argv = ["v610", "--legacy-probability", "l.csv", "--candidates", str(paths["candidates.json"]), "--model-ic", str(paths["ic.json"]), "--max-phases", "2",
            "--out", str(paths["research.json"]), "--stages", *stages]
    if branch:
        argv += ["--branch", branch]
    monkeypatch.setattr(sys, "argv", argv)
    assert research.main() == 0
    return json.loads(paths["research.json"].read_text(encoding="utf-8"))


@pytest.mark.parametrize("adopt", [False, True])
def test_the_whole_chain_runs_on_branch_a(research, monkeypatch, tmp_path, adopt):
    report = _run(research, monkeypatch, tmp_path, branch="A", stages=["model", "head", "book", "costs", "legacy", "gate"], adopt=adopt)
    assert report["branch"] == "A" and set(report["model"]["variants"]) == {"cand", "swap", "bad"} and report["model"]["variants"]["bad"]["skipped"]
    assert {"book", "costs", "legacy", "gate", "head", "final_holdout_seen"} <= set(report) and set(report["book"]["cap_report"]) == {"1.0", "0.75", "0.5"}
    assert (report["adopted"]["model"] is not None) == adopt and (report["head"]["adopted"] is not None) == adopt


def test_branch_b_freezes_the_gates_and_scores_ungated_only(research, monkeypatch, tmp_path):
    report = _run(research, monkeypatch, tmp_path, branch="B", stages=["head", "gate"], candidates={"installed": {}})
    assert "skipped" in report["gate"] and report["head"]["h1"] is None or report["head"]["variants"]["H2"]


def test_the_branch_comes_from_the_calibration_file_when_not_given(research, monkeypatch, tmp_path):
    from script_loader import ROOT

    monkeypatch.setattr(research, "ROOT_DIR", tmp_path)
    (tmp_path / "config.json").write_text((ROOT / "config.json").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "ml" / "evaluation" / "v610").mkdir(parents=True)
    (tmp_path / "ml" / "evaluation" / "v610" / "calibration.json").write_text(json.dumps({"verdict": {"branch": "B"}}), encoding="utf-8")
    out = tmp_path / "out.json"
    monkeypatch.setattr(sys, "argv", ["v610", "--legacy-probability", "l.csv", "--stages", "costs", "--max-phases", "2", "--out", str(out)])
    assert research.main() == 0
    assert json.loads(out.read_text(encoding="utf-8"))["branch"] == "B"
    monkeypatch.setattr(sys, "argv", ["v610", "--legacy-probability", "l.csv", "--stages", "costs", "--max-phases", "2", "--out", str(out), "--branch", "A"])
    assert research.main() == 0 and json.loads(out.read_text(encoding="utf-8"))["branch"] == "A"
