"""scripts/v620_research.py's runtime (V6.6.6, #359): the phase worker, the pool and the rule chain (R-DEDUPE, R-STAGGER, R-MODEL10) on the synthetic harness."""

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
    return load_script("v620_research")


def test_a_phase_carries_the_sweep_and_legacy_returns_and_the_pool_is_linux_only(research, monkeypatch):
    harness = research_fakes.FakeHarness()
    research._JOB.clear()
    research._JOB.update(harness=harness, mechanisms={}, resolved={}, mode="ungated", tranches=2, cash_sweep=True)
    summary = research._phase_worker(0)
    assert summary["legacy_net_return"] > 0 and summary["cash_sweep_return"] == 0 and harness.calls[-1]["gate"] == "off" and harness.calls[-1]["tranches"] == 2
    research._JOB.update(mode="as_live")
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


CANDIDATES = {
    "installed": {},
    "good": {"ic_pass": True, "ic_checks": {"decision_priority": "swapped"}, "decision_heads_pass_r_head": True, "latency_ratio": 1.0, "ml_dir": "ml/versions/x", "ensemble": True},
    "plain": {"ic_pass": True, "ic_checks": {"decision_priority": "live"}, "decision_heads_pass_r_head": True, "latency_ratio": 1.0, "legacy_probability": "p.csv"},
    "bad": {"ic_pass": False, "ic_checks": {"x": False}},
}


def _run(research, monkeypatch, tmp_path, *, adopt, stages=("dedupe", "stagger", "model"), candidates=CANDIDATES):
    candidates_file = tmp_path / "candidates.json"
    candidates_file.write_text(json.dumps(candidates), encoding="utf-8")
    out = tmp_path / "research.json"
    if adopt:
        monkeypatch.setattr(research, "rule_verdict", lambda base, variant: {"passes": True, "backtest_gain": 0.5, "validation_change": 0.1, "checks": {}})
        monkeypatch.setattr(research, "stagger_checks", lambda base, variant: {"ok": True})
    model_ic = tmp_path / "model_ic.json"
    model_ic.write_text("{}", encoding="utf-8")  # read, never consulted: every candidate carries its own ic_checks
    monkeypatch.setattr(sys, "argv", ["v620", "--legacy-probability", "l.csv", "--model-ic", str(model_ic), "--candidates", str(candidates_file), "--max-phases", "2", "--out", str(out), "--stages", *stages])
    assert research.main() == 0
    return json.loads(out.read_text(encoding="utf-8"))


@pytest.mark.parametrize("adopt", [False, True])
def test_the_chain_adopts_only_what_passes(research, monkeypatch, tmp_path, adopt):
    report = _run(research, monkeypatch, tmp_path, adopt=adopt)
    assert report["branch"] == "B" and report["model"]["variants"]["bad"]["skipped"] and {"dedupe", "stagger", "model", "sweep_report", "final_holdout_seen"} <= set(report)
    if adopt:
        assert report["adopted"]["tranches"] > 1 and report["adopted"]["model"] and report["sweep_report"]["with"] is None
    else:
        assert report["adopted"]["tranches"] == 1 and report["adopted"]["model"] is None and report["sweep_report"]["with"] is not None


def test_a_run_without_candidates_skips_the_model_stage(research, monkeypatch, tmp_path):
    out = tmp_path / "r.json"
    monkeypatch.setattr(sys, "argv", ["v620", "--legacy-probability", "l.csv", "--max-phases", "2", "--out", str(out), "--stages", "model"])
    assert research.main() == 0 and "model" not in json.loads(out.read_text(encoding="utf-8"))
