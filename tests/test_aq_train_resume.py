"""`aq train --resume`, `--list-runs`, `--candidate` and `--memory-profile` (V6.6.10): every mode records a run folder when it starts and a
stopped run continues from it, and `aq pipeline run --resume` continues the newest stopped pipeline run."""

from __future__ import annotations

import json
import sys

import pytest

import aq_cli
from retraining import run_resume


@pytest.fixture
def runs(tmp_path, monkeypatch):
    monkeypatch.setattr(aq_cli, "TRAIN_RUNS_DIR", tmp_path / "cycle")
    return tmp_path / "cycle"


def _train(argv):
    args = aq_cli.build_parser().parse_args(["train", *argv])
    return args.func(args)


def _only_run(runs):
    (folder,) = runs.glob("train_*")
    return folder


def test_a_bare_run_stopped_in_its_sequence_step_resumes_there_with_its_own_settings(runs, monkeypatch, capsys):
    ran, outcomes = [], {"sequence": 1}

    def step(name):
        def action(**kwargs):
            ran.append((name, kwargs))
            return outcomes.get(name, 0)
        return action

    for name in ("gating", "multitask", "sequence"):
        monkeypatch.setattr(aq_cli, f"_train_{name}_only", step(name))
    monkeypatch.setattr(aq_cli, "_run", lambda cmd: ran.append(("train_py", cmd)) or 0)
    assert _train(["--memory-profile", "low"]) == 1
    folder = _only_run(runs)
    assert run_resume.done_steps(folder) == ["train_py", "gating", "multitask"] and not run_resume.is_finished(folder)
    assert ran[0][1][-2:] == ["--memory-profile", "low"] and ran[1][1]["memory_profile"] == "low"
    first_sequence = ran[-1][1]
    ran.clear()
    outcomes["sequence"] = 0
    assert _train(["--resume"]) == 0, "the record's settings come back: no flag needed"
    assert [name for name, _ in ran] == ["sequence"], "finished steps are skipped"
    assert ran[0][1]["version_id"] == first_sequence["version_id"] and ran[0][1]["resume"] is True and ran[0][1]["memory_profile"] == "low"
    assert run_resume.is_finished(folder) and "skipped" in capsys.readouterr().out
    assert _train(["--resume", folder.name[len("train_"):]]) == 0 and "already finished" in capsys.readouterr().out
    assert _train(["--resume"]) == 1 and "no stopped" in capsys.readouterr().err


def test_a_walk_forward_keeps_its_id_in_the_run_folder_and_a_resume_continues_its_windows(runs, monkeypatch):
    commands = []

    def fake_run(cmd):
        commands.append(cmd)
        id_file = cmd[cmd.index("--run-id-file") + 1]
        with open(id_file, "w", encoding="utf-8") as handle:
            handle.write("walk-forward-abc\n")
        return 1 if len(commands) == 1 else 0

    monkeypatch.setattr(aq_cli, "_run", fake_run)
    assert _train(["--walk-forward", "--include-sequence", "--memory-profile", "low"]) == 1
    assert "--resume-run-id" not in commands[0]
    assert _train(["--resume"]) == 0
    assert commands[1][commands[1].index("--resume-run-id") + 1] == "walk-forward-abc" and "--include-sequence" in commands[1]
    assert commands[1][-2:] == ["--memory-profile", "low"]


def test_a_candidate_trains_into_one_version_folder_across_a_resume(runs, monkeypatch, capsys):
    commands = []
    monkeypatch.setattr(aq_cli, "_run", lambda cmd: commands.append(cmd) or (1 if len(commands) == 1 else 0))
    assert _train(["--candidate"]) == 1
    assert _train(["--resume"]) == 0
    first, second = (cmd[cmd.index("--version-id") + 1] for cmd in commands)
    assert first == second and first.startswith("candidate-") and "--candidate" in commands[0]
    assert f"ml/versions/{first}/" in capsys.readouterr().out


def test_single_model_modes_record_a_step_and_init_only_keeps_no_folder(runs, monkeypatch):
    monkeypatch.setattr(aq_cli, "_train_topology_only", lambda: 0)
    assert _train(["--topology-only"]) == 0 and run_resume.done_steps(_only_run(runs)) == ["topology"]
    monkeypatch.setattr(aq_cli, "_run", lambda cmd: 0)
    assert _train(["--init-only", "--memory-profile", "low"]) == 0 and len(list(runs.glob("train_*"))) == 1


def test_the_trainers_get_the_recorded_version_profile_and_checkpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(aq_cli, "ROOT_DIR", tmp_path)
    commands = []
    monkeypatch.setattr(aq_cli, "_run", lambda cmd: commands.append(cmd) or 0)
    aq_cli._train_gating_only(version_id="g1", memory_profile="low")
    aq_cli._train_multitask_only(version_id="m1", memory_profile="low")
    aq_cli._train_sequence_only(version_id="s1", memory_profile="low", resume=True)
    assert commands[0][2:] == ["--version-id", "g1", "--memory-profile", "low"]
    assert commands[1][2:] == ["--version-id", "m1", "--memory-profile", "low"]
    assert commands[2][2:] == ["--version-id", "s1", "--memory-profile", "low", "--resume"]


def test_a_context_objective_is_refused_for_the_multitask_trainer(runs, capsys):
    assert _train(["--multitask-only", "--ranking-objective", "ls_sharpe"]) == 2
    assert "--sequence-only" in capsys.readouterr().err
    assert aq_cli.build_parser().parse_args(["train", "--sequence-only", "--ranking-objective", "cost_aware"]).ranking_objective == "cost_aware"


def test_list_runs_shows_train_and_retrain_runs(runs, capsys):
    run_resume.start_record(runs / "train_a", {})
    run_resume.mark_done(runs / "train_a", "train_py")
    run_resume.start_record(runs / "retrain_b", {})
    run_resume.mark_done(runs / "retrain_b", "report")
    assert _train(["--list-runs"]) == 0
    out = capsys.readouterr().out
    assert "a " in out and "resumable" in out and "finished" in out and "train_py" in out


def test_cycle_retrain_list_runs_is_forwarded(monkeypatch):
    seen = []
    monkeypatch.setattr(aq_cli.subprocess, "run", lambda command, **kwargs: seen.append(command) or type("R", (), {"returncode": 0})())
    args = aq_cli.build_parser().parse_args(["cycle", "retrain", "--list-runs"])
    assert args.func(args) == 0 and seen[-1][-1] == "--list-runs" and seen[-1][0] == sys.executable


def test_a_pipeline_run_resumes_the_newest_stopped_run_with_its_own_file(tmp_path, monkeypatch, capsys):
    from evaluation import pipeline

    monkeypatch.chdir(tmp_path)
    (tmp_path / "custom.toml").write_text("", encoding="utf-8")
    calls = []

    def fake_run_stages(stages, actions, *, state_path):
        calls.append(state_path.parent.name)
        if len(calls) == 1:
            raise RuntimeError("stopped")
        state_path.parent.mkdir(parents=True, exist_ok=True)
        (state_path.parent / "report.md").write_text("report", encoding="utf-8")
        return {"done": {"gate": {"result": {"a": {"passed": True}}}}}

    loaded = []
    monkeypatch.setattr(pipeline, "load_pipeline", lambda config: loaded.append(config) or {"pipeline": {"name": "p"}})
    monkeypatch.setattr(pipeline, "pipeline_actions", lambda spec, run_dir: {})
    monkeypatch.setattr(pipeline, "run_stages", fake_run_stages)
    run = aq_cli.build_parser().parse_args(["pipeline", "run", "--config", "custom.toml"])
    with pytest.raises(RuntimeError):
        run.func(run)
    record = json.loads((tmp_path / "runs" / calls[0] / "resume.json").read_text(encoding="utf-8"))
    assert record["config"].endswith("custom.toml")
    again = aq_cli.build_parser().parse_args(["pipeline", "run", "--resume"])
    assert again.func(again) == 0
    assert calls[1] == calls[0] and loaded[-1].name == "custom.toml" and "resuming run" in capsys.readouterr().out
    run_resume.mark_done(tmp_path / "runs" / calls[0], "report")
    assert again.func(again) == 1 and "no stopped run" in capsys.readouterr().err
