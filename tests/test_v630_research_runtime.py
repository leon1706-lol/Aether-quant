"""scripts/v630_research.py's runtime (V6.6.6, #359): the perturbed phase worker, the pool and the rule chain (R-KILL, R-STAGGER2, R-GATE3), for
branch A (gates scored) and branch B (gates frozen), on the synthetic harness."""

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
    return load_script("v630_research")


def test_a_seeded_phase_perturbs_the_kill_switch_input_and_the_pool_is_linux_only(research, monkeypatch):
    harness = research_fakes.FakeHarness()
    research._JOB.clear()
    research._JOB.update(harness=harness, mechanisms={}, resolved={}, mode="ungated", dates=research_fakes.DATES)
    plain = research._phase_worker((0, None))
    seeded = research._phase_worker((0, 3))
    assert plain["locked_dates"] and "kill_switch_extra_returns" in harness.calls[-1] and "kill_switch_extra_returns" not in harness.calls[0] and seeded
    research._JOB.update(mode="as_live")
    assert len(research.map_tasks([(0, None), (1, None)], workers=1)) == 2

    class Pool:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def map(self, function, items):
            return [function(item) for item in items]

    monkeypatch.setattr(multiprocessing, "get_context", lambda kind: SimpleNamespace(Pool=lambda count: Pool()))
    monkeypatch.setattr(sys, "platform", "linux")
    assert len(research.map_tasks([(0, None), (1, None)], workers=2)) == 2
    research._JOB.clear()


def _run(research, monkeypatch, tmp_path, *, branch, adopt, stages=("kill", "stagger", "gates")):
    calibration = tmp_path / "calibration.json"
    if branch:
        calibration.write_text(json.dumps({"verdict": {"branch": branch}}), encoding="utf-8")
    out, adopted = tmp_path / "research.json", tmp_path / "adopted.json"
    if adopt:
        monkeypatch.setattr(research, "rule_verdict", lambda base, variant: {"passes": True, "backtest_gain": 0.5, "validation_change": 0.1, "checks": {}})
        monkeypatch.setattr(research, "kill_checks", lambda *args: {"ok": True})
        monkeypatch.setattr(research, "kill_branch", lambda variants: ("A", next(iter(variants))))
        monkeypatch.setattr(research, "stagger2_checks", lambda base, variant: {"ok": True})
    monkeypatch.setattr(sys, "argv", ["v630", "--legacy-probability", "l.csv", "--calibration", str(calibration), "--max-phases", "2", "--out", str(out),
                                      "--adopted-config-out", str(adopted), "--stages", *stages])
    assert research.main() == 0
    return json.loads(out.read_text(encoding="utf-8")), json.loads(adopted.read_text(encoding="utf-8"))


@pytest.mark.parametrize("adopt", [False, True])
def test_branch_a_scores_the_gates_and_adopts_only_what_passes(research, monkeypatch, tmp_path, adopt):
    report, adopted = _run(research, monkeypatch, tmp_path, branch="A", adopt=adopt)
    assert report["calibration_branch"] == "A" and {"kill", "stagger", "gates"} <= set(report) and "variants" in report["gates"]
    assert (report["stagger"]["adopted"] is True) == adopt and (adopted["tranches"] > 1) == adopt and (bool(adopted["config"]) or not adopt)


def test_branch_b_leaves_the_gates_frozen_and_a_missing_calibration_means_branch_b(research, monkeypatch, tmp_path):
    report, _ = _run(research, monkeypatch, tmp_path, branch="B", adopt=False, stages=("stagger", "gates"))
    assert "skipped" in report["gates"]
    again, _ = _run(research, monkeypatch, tmp_path / "x" if (tmp_path / "x").mkdir() is None else tmp_path, branch=None, adopt=False, stages=("gates",))
    assert again["calibration_branch"] == "B"
