"""scripts/cycle_retrain.py: stages resume, a failure stops the run, and the Codespace always stops."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from cycle_retrain import (  # noqa: E402
    PROCEDURES,
    drive_codespace,
    load_state,
    local_actions,
    main,
    procedure_sha256,
    remote_command,
    resolve_codespace,
    run_stages,
    smoke_panel,
    trainer_command,
    wait_until_reachable,
)


def test_a_resume_skips_finished_stages(tmp_path):
    calls = []
    actions = {name: (lambda name=name: calls.append(name) or name) for name in ("a", "b", "c")}
    state_path = tmp_path / "state.json"

    def boom():
        raise RuntimeError("the VM rebooted")

    with pytest.raises(RuntimeError):
        run_stages(["a", "b", "c"], {**actions, "b": boom}, state_path=state_path, emit=lambda _: None)
    assert calls == ["a"] and list(load_state(state_path)["done"]) == ["a"]
    calls.clear()
    run_stages(["a", "b", "c"], actions, state_path=state_path, emit=lambda _: None)
    assert calls == ["b", "c"], "a failed stage reruns, a finished one doesn't"


def test_the_procedure_hash_follows_the_recipe_not_the_weights():
    base = procedure_sha256("k06", PROCEDURES["k06"], b"code")
    assert base == procedure_sha256("k06", PROCEDURES["k06"], b"code")
    assert base != procedure_sha256("k06", {**PROCEDURES["k06"], "seeds": "1"}, b"code")
    assert base != procedure_sha256("k06", PROCEDURES["k06"], b"other code")


def test_a_trainer_command_says_everything_and_holds_no_free_form():
    command = trainer_command("py", "k06", PROCEDURES["k06"], panel="p.parquet", out="o.csv", score_end="2018-12-31")
    assert command[:2] == ["py", "train_cross_sectional.py"]
    for flag in ("--model", "--feature-set", "--train-start", "--first-test-year", "--purge-days", "--score-end"):
        assert flag in command


def test_this_pc_refuses_a_real_local_retrain(monkeypatch, capsys):
    import cycle_retrain

    monkeypatch.setattr(cycle_retrain, "ram_preflight", lambda host, **kwargs: {"ok": False, "reason": "4.0 GB of RAM, 14 GB needed"})
    assert main(["--host", "local", "--procedure", "k06"]) == 2
    assert "refusing" in capsys.readouterr().err


def test_a_dry_run_says_the_stages_and_stops(capsys):
    assert main(["--host", "codespace", "--procedure", "k06", "--dry-run"]) == 0
    assert "walk_forward" in capsys.readouterr().out


def test_a_retrain_needs_a_procedure():
    with pytest.raises(SystemExit):
        main(["--host", "local"])


def test_a_procedure_is_never_free_form():
    with pytest.raises(SystemExit):
        main(["--host", "local", "--procedure", "rm -rf /"])


def test_local_stages_run_the_scripts_with_this_python(tmp_path, monkeypatch):
    monkeypatch.setenv("AQ_SEC_CONTACT", "a contact for this test")
    seen = []

    def runner(command, **_):
        seen.append(command)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    actions = local_actions("k06", PROCEDURES["k06"], run_dir=tmp_path, python="py", runner=runner)
    actions["bootstrap_data"]()
    actions["refresh_data"]()
    actions["walk_forward"]()
    joined = [" ".join(command) for command in seen]
    assert any("scripts/build_wide_root.py" in line for line in joined) and any("scripts/build_wide_info.py" in line for line in joined)
    assert any("data_append_refresh.py --apply" in line for line in joined) and any("train_cross_sectional.py" in line for line in joined)


def test_a_failed_step_stops_with_what_it_said(tmp_path):
    actions = local_actions("k06", PROCEDURES["k06"], run_dir=tmp_path, python="py", runner=lambda command, **_: SimpleNamespace(returncode=3, stdout="", stderr="out of memory"))
    with pytest.raises(RuntimeError, match="out of memory"):
        actions["walk_forward"]()


def test_missing_scores_are_a_failure_not_a_vintage(tmp_path):
    with pytest.raises(RuntimeError, match="was not written"):
        local_actions("k06", PROCEDURES["k06"], run_dir=tmp_path, python="py")["score"]()


def test_a_refit_registers_a_vintage_and_promotes_nothing(tmp_path):
    actions = local_actions("k06", PROCEDURES["k06"], run_dir=tmp_path, python="py")
    assert "nothing is promoted" in actions["round"]()
    registered = actions["register"]()
    assert registered["procedure"] == "k06" and len(registered["procedure_sha256"]) == 64 and registered["vintage"] == tmp_path.name


@pytest.fixture
def powershell_present(monkeypatch):
    """The push script needs PowerShell, which a Linux runner lacks; these tests drive the Codespace through a fake runner and don't care which shell it names."""
    import cycle_retrain
    monkeypatch.setattr(cycle_retrain, "sync_shell", lambda: "powershell")


LISTED = '[{"name": "aq-real-name-1", "displayName": "aq-Training-Ground-Fixed", "state": "Available"}]'


@pytest.mark.usefixtures("powershell_present")
def test_the_codespace_is_addressed_by_its_real_name_and_a_failed_stop_is_loud(tmp_path, capsys):
    seen = []

    def runner(command, **_):
        seen.append(command)
        if command[:3] == ["gh", "codespace", "list"]:
            return SimpleNamespace(returncode=0, stdout=LISTED, stderr="")
        if command[:3] == ["gh", "codespace", "stop"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="HTTP 500")
        return SimpleNamespace(returncode=0, stdout='{"done": {}}', stderr="")

    drive_codespace("k06", PROCEDURES["k06"], run_id="r9", smoke=False, runner=runner, emit=lambda _: None, scratch=tmp_path, sleep=lambda _: None)
    assert all("aq-Training-Ground-Fixed" not in command for command in seen if command[:3] != ["powershell", "-NoProfile", "-File"] and command[2] != "list")
    assert seen[-1] == ["gh", "codespace", "stop", "-c", "aq-real-name-1"]
    assert "DID NOT STOP" in capsys.readouterr().err


def test_a_codespace_still_shutting_down_is_waited_for_and_never_pushed_to():
    calls = []
    states = iter(["ShuttingDown", "ShuttingDown", "Shutdown"])

    def runner(command, **_):
        calls.append(command)
        if command[2] == "list":
            return SimpleNamespace(returncode=0, stdout=f'[{{"name": "c", "state": "{next(states)}"}}]', stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    wait_until_reachable("c", runner=runner, sleep=lambda _: None)
    assert [command[2] for command in calls] == ["list", "list", "list", "ssh"], "only a settled Codespace is probed"


def test_a_codespace_that_never_answers_is_an_error_not_a_hang():
    def runner(command, **_):
        return SimpleNamespace(returncode=0, stdout='[{"name": "c", "state": "Starting"}]', stderr="")

    with pytest.raises(RuntimeError, match="reachable"):
        wait_until_reachable("c", runner=runner, sleep=lambda _: None, attempts=3)


def test_an_unknown_codespace_is_an_error():
    with pytest.raises(RuntimeError, match="no Codespace"):
        resolve_codespace("gone", runner=lambda command, **_: SimpleNamespace(returncode=0, stdout=LISTED, stderr=""))


@pytest.mark.parametrize("failing", ["push", "cat", "run"])
def test_the_codespace_stops_however_the_run_ends(tmp_path, failing):
    seen = []

    def runner(command, **_):
        seen.append(command)
        text = " ".join(command)
        if command[:3] == ["gh", "codespace", "list"]:
            return SimpleNamespace(returncode=0, stdout=LISTED, stderr="")
        fails = (failing == "push" and "codespace_sync" in text) or (failing == "cat" and text.endswith("state.json")) or (failing == "run" and "cycle_retrain.py" in text)
        return SimpleNamespace(returncode=1 if fails else 0, stdout="", stderr="failed")

    with pytest.raises(RuntimeError):
        drive_codespace("k06", PROCEDURES["k06"], run_id="r1", smoke=False, runner=runner, emit=lambda _: None, scratch=tmp_path, sleep=lambda _: None)
    assert seen[-1][:3] == ["gh", "codespace", "stop"]


@pytest.mark.usefixtures("powershell_present")
def test_the_codespace_stops_after_a_good_run_too(tmp_path):
    seen = []

    def runner(command, **_):
        seen.append(command)
        if command[:3] == ["gh", "codespace", "list"]:
            return SimpleNamespace(returncode=0, stdout=LISTED, stderr="")
        if command[-1].endswith("state.json"):
            return SimpleNamespace(returncode=0, stdout='{"done": {"report": {}}}', stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    out = drive_codespace("k06", PROCEDURES["k06"], run_id="r2", smoke=False, runner=runner, emit=lambda _: None, scratch=tmp_path, sleep=lambda _: None)
    assert out["ran"] and "report" in out["state"]["done"]
    assert seen[-1][:3] == ["gh", "codespace", "stop"]


def test_the_codespace_job_runs_the_same_script_locally_there():
    command = remote_command("k06", run_id="r3")
    assert command == ["python3", "/workspaces/Aether-quant/scripts/cycle_retrain.py", "--host", "local", "--procedure", "k06", "--run-id", "r3", "--on-codespace"]
    assert "--smoke" in remote_command("smoke", run_id="r3", smoke=True)
    assert remote_command("k06", run_id="r3", resume=True)[-2:] == ["--resume", "r3"], "the settings come along, in case that machine has no record yet"
    assert not any(" " in part or '"' in part for part in command), "Windows OpenSSH strips quotes from a command line"


@pytest.mark.usefixtures("powershell_present")
def test_a_dropped_session_resumes_and_a_lasting_failure_still_stops_the_codespace(tmp_path):
    runs = []

    def flaky(command, **_):
        runs.append(command)
        if command[:3] == ["gh", "codespace", "list"]:
            return SimpleNamespace(returncode=0, stdout=LISTED, stderr="")
        if "cycle_retrain.py" in " ".join(command) and sum("cycle_retrain.py" in " ".join(item) for item in runs) < 3:
            return SimpleNamespace(returncode=255, stdout="", stderr="connection reset")
        return SimpleNamespace(returncode=0, stdout='{"done": {"report": {}}}', stderr="")

    out = drive_codespace("k06", PROCEDURES["k06"], run_id="r4", smoke=False, runner=flaky, emit=lambda _: None, scratch=tmp_path, sleep=lambda _: None)
    assert out["state"]["done"] == {"report": {}} and sum("cycle_retrain.py" in " ".join(item) for item in runs) == 3
    attempts = [item for item in runs if "cycle_retrain.py" in " ".join(item)]
    assert "--resume" not in attempts[0] and all("--resume" in item for item in attempts[1:]), "a retry continues that machine's run (V6.6.10)"
    assert runs[-1][:3] == ["gh", "codespace", "stop"]


def test_smoke_runs_every_stage_on_any_machine(monkeypatch, tmp_path):
    pytest.importorskip("sklearn")
    pytest.importorskip("pyarrow")
    import cycle_retrain

    monkeypatch.setattr(cycle_retrain, "STATE_ROOT", tmp_path)
    assert main(["--host", "local", "--smoke", "--run-id", "t"]) == 0
    state = load_state(tmp_path / "retrain_t" / "state.json")
    assert set(state["done"]) == {"refresh_data", "build_panel", "walk_forward", "score", "round", "register", "report"}
    assert state["done"]["score"]["result"]["rows"] > 0


def test_the_smoke_panel_is_what_the_trainer_reads(tmp_path):
    pytest.importorskip("pyarrow")
    from train_cross_sectional import FUNDAMENTAL_SIGNS, load_panel_frame

    path = tmp_path / "panel.parquet"
    smoke_panel(path)
    frame, features = load_panel_frame(path, feature_set="fundamental", target="target_wide_20d")
    assert sorted(features) == sorted(FUNDAMENTAL_SIGNS) and frame["_label"].notna().all()


# --- V6.6.4 (Problems #321): a refit records its vintage, the scores come home, and the shell and contact are checked up front ------------------------------

def test_a_refit_of_a_frozen_procedure_adds_its_vintage_once_and_a_candidate_adds_nothing(tmp_path):
    import json

    from cycle_retrain import register_vintage

    from evaluation.generation_registry import Generation, lifecycle_is_intact, load_registry, save_registry

    registry, lifecycle = tmp_path / "registry.json", tmp_path / "lifecycle.jsonl"
    save_registry(registry, {"g1": Generation(id="g1", kind="model", tier="tier1", stage="active", born="2026-11-07", procedure_sha256="abc")})
    first = register_vintage(registry, lifecycle, "abc", "retrain_20261108_x", created_at="2026-11-08T00:00:00+00:00")
    assert first == {"added": True, "generation": "g1"} and load_registry(registry)["g1"].vintages == ("retrain_20261108_x",)
    assert register_vintage(registry, lifecycle, "abc", "retrain_20261108_x", created_at="2026-11-08T00:00:01+00:00")["added"] is False
    candidate = register_vintage(registry, lifecycle, "someone-elses-sha", "retrain_y", created_at="2026-11-08T00:00:02+00:00")
    assert candidate["added"] is False and "candidate" in candidate["reason"]
    assert lifecycle_is_intact(lifecycle)[0] is True and len(lifecycle.read_text(encoding="utf-8").splitlines()) == 1
    assert json.loads(lifecycle.read_text(encoding="utf-8").splitlines()[0])["payload"]["event"] == "vintage_added"
    assert register_vintage(tmp_path / "missing.json", lifecycle, "abc", "v", created_at="t")["added"] is False


def test_the_sync_shell_is_found_or_the_error_says_what_to_do(monkeypatch):
    import cycle_retrain

    monkeypatch.setattr(cycle_retrain.shutil, "which", lambda name: "/bin/pwsh" if name == "pwsh" else None)
    assert cycle_retrain.sync_shell() == "/bin/pwsh"
    monkeypatch.setattr(cycle_retrain.shutil, "which", lambda name: "C:/ps/powershell.exe" if name == "powershell" else None)
    assert cycle_retrain.sync_shell() == "C:/ps/powershell.exe"
    monkeypatch.setattr(cycle_retrain.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="--on-codespace"):
        cycle_retrain.sync_shell()


def test_the_bootstrap_stage_refuses_up_front_without_a_sec_contact(tmp_path, monkeypatch):
    monkeypatch.delenv("AQ_SEC_CONTACT", raising=False)
    actions = local_actions("k06", PROCEDURES["k06"], run_dir=tmp_path, runner=lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))
    with pytest.raises(RuntimeError, match="AQ_SEC_CONTACT"):
        actions["bootstrap_data"]()


def test_the_codespace_run_brings_the_scores_back_with_the_state(tmp_path, monkeypatch):
    import json

    import cycle_retrain

    monkeypatch.setattr(cycle_retrain, "sync_shell", lambda: "pwsh")
    state = {"done": {"score": {"result": {"scores": "ml/cycle/retrain_r1/k06.csv", "sha256": "x"}}}}
    seen = []

    def runner(command, cwd=None, capture_output=None, text=None):
        seen.append(list(command))
        joined = " ".join(map(str, command))
        if "list" in command:
            return SimpleNamespace(returncode=0, stdout=json.dumps([{"name": "cs-1", "displayName": "aq-Training-Ground-Fixed", "state": "Available"}]), stderr="")
        if "state.json" in joined:
            return SimpleNamespace(returncode=0, stdout=json.dumps(state), stderr="")
        if joined.endswith("k06.csv"):
            return SimpleNamespace(returncode=0, stdout="date,ticker,score\n2024-01-02,A,0.5\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    result = drive_codespace("k06", PROCEDURES["k06"], run_id="r1", smoke=False, runner=runner, scratch=tmp_path, emit=lambda line: None, sleep=lambda seconds: None)
    assert result["ran"] is True
    assert (tmp_path / "k06.csv").read_text(encoding="utf-8").startswith("date,ticker,score"), "the scores came home"
    assert any(command[:2] == ["gh", "codespace"] and "stop" in command for command in seen), "and the Codespace still stopped"


# --- V6.6.6 (#359): the remaining paths ---------------------------------------------------------------------------------------------------------------------


def test_the_panel_is_built_once_and_scores_outside_the_repo_are_named_as_they_are(tmp_path, monkeypatch):
    import cycle_retrain

    seen = []
    runner = lambda command, **_: seen.append(command) or SimpleNamespace(returncode=0, stdout="ok", stderr="")  # noqa: E731
    monkeypatch.setattr(cycle_retrain, "ROOT", tmp_path / "repo")
    actions = local_actions("k06", PROCEDURES["k06"], run_dir=tmp_path / "run", python="py", runner=runner)
    actions["build_panel"]()
    assert any("v660_build_panel.py" in " ".join(command) for command in seen)
    (tmp_path / "repo" / "data_wide" / "reference").mkdir(parents=True)
    (tmp_path / "repo" / "data_wide" / "reference" / "panel_TA.parquet").write_text("x", encoding="utf-8")
    assert actions["build_panel"]() == "panel present"
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "k06.csv").write_text("date,ticker,score\n", encoding="utf-8")
    assert actions["score"]()["scores"] == str(tmp_path / "run" / "k06.csv") and actions["report"]() == str(tmp_path / "run")


def test_a_smoke_run_without_usable_scores_fails(tmp_path):
    import cycle_retrain

    actions = cycle_retrain.smoke_actions(run_dir=tmp_path, python="py")
    (tmp_path / "smoke.csv").write_text("date,ticker,score\n2024-01-02,A,\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="no usable scores"):
        actions["score"]()


def test_a_failed_codespace_listing_is_loud():
    with pytest.raises(RuntimeError, match="gh codespace list exit 4: auth"):
        resolve_codespace("x", runner=lambda command, **_: SimpleNamespace(returncode=4, stdout="", stderr="auth"))


def test_the_codespace_host_drives_the_codespace(monkeypatch, tmp_path):
    import cycle_retrain

    calls = []
    monkeypatch.setattr(cycle_retrain, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(cycle_retrain, "drive_codespace", lambda name, procedure, run_id, smoke, resume: calls.append((name, run_id, smoke, resume)))
    assert main(["--host", "codespace", "--smoke", "--run-id", "cs1"]) == 0 and calls == [("smoke", "cs1", True, False)]
    assert (tmp_path / "retrain_cs1" / "resume.json").exists(), "a Codespace run has a resume record on the driving machine too (V6.6.10)"
    assert main(["--resume", "cs1"]) == 0 and calls[-1] == ("smoke", "cs1", True, True)


# --- V6.6.9: the model stack (#395) -----------------------------------------------------------------------------------------


def test_the_stack_procedures_are_registered_and_a_refit_of_stack_is_a_vintage_while_stack_asof_is_a_candidate():
    assert PROCEDURES["stack"]["kind"] == "stack" and PROCEDURES["stack_asof"]["asof_labels"] is True
    assert "train_sequence.py" in PROCEDURES["stack"]["trainers"]


def test_a_stack_dry_run_lists_the_stack_stages_and_the_pc_refuses_the_real_run(capsys):
    import cycle_retrain

    assert main(["--host", "codespace", "--procedure", "stack", "--dry-run"]) == 0
    printed = capsys.readouterr().out
    assert "snapshot_active" in printed and "walk_forward" in printed and "refresh_data" not in printed
    assert cycle_retrain.ram_preflight("local", total_bytes=4 * 1024**3)["ok"] is False


def test_the_stack_smoke_validates_every_planned_flag_against_the_trainers(monkeypatch, capsys):
    import cycle_retrain

    helps = {"train.py": "--candidate --version-id --write-dataset --walk-forward --include-multitask --include-sequence --mode --resume-run-id --run-id-file",
             "train_multitask.py": "--version-id --dataset-path --feature-schema-path", "train_sequence.py": "--version-id --dataset-path --feature-schema-path", "train_gating.py": "--version-id",
             "scripts/feature_parity_audit.py": "--skip-synthetic --dataset --scaler-stats --schema --output", "scripts/v650_ml_scores.py": "--run-id --end --out", "data_pipeline.factor_file_backfill": "--audit"}

    def runner(command, **kwargs):
        key = command[2] if command[1] == "-m" else command[1]
        return SimpleNamespace(returncode=0, stdout=helps[key], stderr="")

    monkeypatch.setattr(cycle_retrain.subprocess, "run", runner)
    assert main(["--host", "local", "--procedure", "stack", "--smoke"]) == 0
    assert '"flag_problems": []' in capsys.readouterr().out
    helps["train_gating.py"] = ""
    assert main(["--host", "local", "--procedure", "stack", "--smoke"]) == 1
    assert "train_gating.py: --version-id" in capsys.readouterr().out


def test_the_stack_stages_run_their_commands_read_the_walk_forward_id_and_register_the_vintage(tmp_path, monkeypatch):
    import cycle_retrain

    monkeypatch.setattr(cycle_retrain, "ROOT", tmp_path)
    for name in PROCEDURES["stack"]["trainers"]:
        (tmp_path / name).write_text("# trainer", encoding="utf-8")
    ml = tmp_path / "ml"
    (ml / "versions" / "r1_base").mkdir(parents=True)
    (ml / "versions" / "r1_base" / "sequence_model.json").write_text("{}", encoding="utf-8")
    (ml / "sequence_model.json").write_text("{}", encoding="utf-8")
    seen = []

    def runner(command, **kwargs):
        seen.append(list(command))
        out = "walk-forward run id: walk-forward-abc-123\n" if "--walk-forward" in command else "ok"
        return SimpleNamespace(returncode=0, stdout=out, stderr="")

    actions = cycle_retrain.stack_actions("stack", PROCEDURES["stack"], run_dir=tmp_path / "run", run_id="r1", python="py", runner=runner, score_end="2023-06-30")
    assert list(actions) == __import__("evaluation.research_cycle", fromlist=["x"]).stack_stages()
    assert actions["snapshot_active"]().endswith("pre_retrain_r1.zip") and (ml / "backups" / "pre_retrain_r1.zip").exists()
    actions["factor_audit"](), actions["dataset"](), actions["parity_audit"](), actions["multitask"](), actions["sequence"](), actions["gating"]()
    actions["walk_forward"]()
    actions["scores"]()
    assert seen[-1] == ["py", "scripts/v650_ml_scores.py", "--run-id", "walk-forward-abc-123", "--end", "2023-06-30", "--out", "ml/cycle/retrain_r1/scores"]
    assert "sequence_model.json" in actions["pins"]()
    registered = actions["register"]()
    assert registered["procedure"] == "stack" and registered["registered"]["added"] is False and actions["report"]().endswith("run")


def test_a_stack_run_without_a_score_end_skips_the_scores_and_a_walk_forward_without_an_id_fails(tmp_path, monkeypatch):
    import cycle_retrain

    ok = lambda command, **kwargs: SimpleNamespace(returncode=0, stdout="no id here", stderr="")  # noqa: E731
    actions = cycle_retrain.stack_actions("stack", PROCEDURES["stack"], run_dir=tmp_path, run_id="r2", python="py", runner=ok)
    assert "pass --score-end" in actions["scores"]()
    with pytest.raises(RuntimeError, match="no run id"):
        actions["walk_forward"]()


def test_the_stack_runs_through_main_on_a_machine_that_may_train(tmp_path, monkeypatch, capsys):
    import cycle_retrain

    monkeypatch.setattr(cycle_retrain, "ram_preflight", lambda host, **kwargs: {"ok": True, "reason": "plenty"})
    monkeypatch.setattr(cycle_retrain, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(cycle_retrain, "stack_actions", lambda *args, **kwargs: {stage: (lambda stage=stage: stage) for stage in cycle_retrain.stack_stages()})
    assert main(["--host", "local", "--procedure", "stack", "--run-id", "rX", "--score-end", "2023-06-30"]) == 0
    assert set(cycle_retrain.load_state(tmp_path / "retrain_rX" / "state.json")["done"]) == set(cycle_retrain.stack_stages())


def test_the_estimate_reads_the_dataset_shape_and_prints_each_profile(tmp_path, monkeypatch, capsys):
    """V6.6.10: `--estimate` says what each memory profile would need before a night is spent on a run."""
    import json

    import cycle_retrain

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"phase_v2": {"retraining": {"sequence_training": {"window_size": 30}}}}), encoding="utf-8")
    missing = cycle_retrain.memory_estimate(tmp_path / "ml" / "datasets" / "full_dataset.csv", config)
    assert "no dataset" in missing["error"]
    (tmp_path / "ml" / "datasets").mkdir(parents=True)
    dataset = tmp_path / "ml" / "datasets" / "full_dataset.csv"
    dataset.write_text("a,b,c\n1,2,3\n4,5,6\n", encoding="utf-8")
    report = cycle_retrain.memory_estimate(dataset, config)
    assert report["rows"] == 2 and report["columns"] == 3 and report["features"] == 3 and set(report["estimated_peak_gb"]) == {"standard", "low"}
    (tmp_path / "ml" / "feature_schema.json").write_text(json.dumps({"model_input_names": ["a", "b"]}), encoding="utf-8")
    assert cycle_retrain.memory_estimate(dataset, config)["features"] == 2
    monkeypatch.setattr(cycle_retrain, "ROOT", tmp_path)
    (tmp_path / "config.json").write_text(config.read_text(encoding="utf-8"), encoding="utf-8")
    assert main(["--host", "local", "--estimate"]) == 0
    assert '"estimated_peak_gb"' in capsys.readouterr().out


def test_a_low_profile_run_reaches_the_preflight_and_the_stack_actions(tmp_path, monkeypatch, capsys):
    import cycle_retrain

    seen = {}
    monkeypatch.setattr(cycle_retrain, "ram_preflight", lambda host, **kwargs: seen.setdefault("preflight", kwargs) and {"ok": True, "reason": "fits"})
    monkeypatch.setattr(cycle_retrain, "STATE_ROOT", tmp_path)

    def actions(*args, **kwargs):
        seen["actions"] = kwargs
        return {stage: (lambda stage=stage: stage) for stage in cycle_retrain.stack_stages()}

    monkeypatch.setattr(cycle_retrain, "stack_actions", actions)
    assert main(["--host", "local", "--procedure", "stack", "--run-id", "rL", "--memory-profile", "low"]) == 0
    assert seen["preflight"] == {"min_gb": None, "profile": "low"} and seen["actions"]["profile"] == "low"
    assert '"memory_profile": "low"' in capsys.readouterr().out


def test_a_stopped_walk_forward_resumes_its_own_windows_and_the_id_is_read_from_stdout(tmp_path):
    """V6.6.10: `--resume-walk-forward` continues a stopped run; the id is found in train.py's last stdout line, or kept from the resume."""
    import cycle_retrain

    seen = []

    def runner(command, **kwargs):
        seen.append(list(command))
        return SimpleNamespace(returncode=0, stdout="Walk-forward run walk-forward-1a2b-3c: 12 windows trained" if "--walk-forward" in command else "", stderr="")

    actions = cycle_retrain.stack_actions("stack", PROCEDURES["stack"], run_dir=tmp_path, run_id="r3", python="py", runner=runner, score_end="2023-06-30",
                                          resume_walk_forward="walk-forward-old")
    actions["walk_forward"]()
    assert seen[-1][-2:] == ["--resume-run-id", "walk-forward-old"]
    actions["scores"]()
    assert seen[-1][3] == "walk-forward-1a2b-3c"
    silent = lambda command, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr="")  # noqa: E731
    resumed = cycle_retrain.stack_actions("stack", PROCEDURES["stack"], run_dir=tmp_path, run_id="r4", python="py", runner=silent, score_end="2023-06-30",
                                          resume_walk_forward="walk-forward-kept")
    resumed["walk_forward"]()
    seen.clear()
    resumed_scores = cycle_retrain.stack_actions("stack", PROCEDURES["stack"], run_dir=tmp_path, run_id="r4", python="py", runner=runner, score_end="2023-06-30",
                                                 resume_walk_forward="walk-forward-kept")
    resumed_scores["scores"]()
    assert seen[-1][3] == "walk-forward-kept"


def test_resume_continues_a_stopped_run_with_its_own_settings(tmp_path, monkeypatch, capsys):
    """V6.6.10: `--resume` reads the run folder's resume.json and walk_forward_run_id, skips finished stages and needs no other flag."""
    import cycle_retrain

    monkeypatch.setattr(cycle_retrain, "ram_preflight", lambda host, **kwargs: {"ok": True, "reason": "fits"})
    monkeypatch.setattr(cycle_retrain, "STATE_ROOT", tmp_path)
    seen = {}

    def actions(*args, **kwargs):
        seen.update(kwargs)
        return {stage: (lambda stage=stage: stage) for stage in cycle_retrain.stack_stages()}

    monkeypatch.setattr(cycle_retrain, "stack_actions", actions)
    monkeypatch.setattr(cycle_retrain, "run_stages", lambda stages, acts, state_path: seen.setdefault("state", state_path))
    assert main(["--host", "local", "--procedure", "stack", "--run-id", "rR", "--memory-profile", "low", "--score-end", "2023-06-30"]) == 0
    record = json.loads((tmp_path / "retrain_rR" / "resume.json").read_text(encoding="utf-8"))
    assert record["memory_profile"] == "low" and record["score_end"] == "2023-06-30" and record["snapshot"].endswith("pre_retrain_rR.zip")
    (tmp_path / "retrain_rR" / "walk_forward_run_id").write_text("walk-forward-abc\n", encoding="utf-8")
    seen.clear()
    assert main(["--resume"]) == 0
    assert seen["resume_walk_forward"] == "walk-forward-abc" and seen["profile"] == "low" and seen["score_end"] == "2023-06-30"
    assert "resuming rR (walk-forward walk-forward-abc)" in capsys.readouterr().out
    assert main(["--resume", "rR"]) == 0 and main(["--resume", "nope"]) == 1
    assert "nothing to resume" in capsys.readouterr().err


def test_resume_picks_the_newest_unfinished_run_and_needs_a_host_otherwise(tmp_path, monkeypatch):
    import argparse as _argparse
    import os as _os

    import cycle_retrain

    for name, done in (("old", {}), ("finished", {"report": {}}), ("new", {})):
        folder = tmp_path / f"retrain_{name}"
        folder.mkdir()
        (folder / "resume.json").write_text(json.dumps({"run_id": name}), encoding="utf-8")
        (folder / "state.json").write_text(json.dumps({"done": done}), encoding="utf-8")
    _os.utime(tmp_path / "retrain_old" / "resume.json", (1, 1))
    assert cycle_retrain.find_resumable(tmp_path).name == "retrain_new"
    assert cycle_retrain.find_resumable(tmp_path / "empty") is None
    args = _argparse.Namespace(resume="latest", resume_walk_forward="walk-forward-forced", host=None, procedure=None, smoke=False, memory_profile="standard",
                               score_end=None, min_ram_gb=None, run_id=None)
    assert cycle_retrain.resume_args(args, state_root=tmp_path).resume_walk_forward == "walk-forward-forced"
    with pytest.raises(SystemExit):
        main(["--procedure", "stack"])
    assert main(["--estimate"]) == 0


def test_list_runs_shows_every_retrain_and_train_run(tmp_path, monkeypatch, capsys):
    """V6.6.10: `--list-runs` lists the run folders with their finished stages, so a run id never has to be looked up."""
    import cycle_retrain

    monkeypatch.setattr(cycle_retrain, "STATE_ROOT", tmp_path)
    for name, done in (("retrain_g1", {"dataset": {}}), ("retrain_g0", {"report": {}}), ("train_t1", {"train_py": {}})):
        (tmp_path / name).mkdir()
        (tmp_path / name / "resume.json").write_text(json.dumps({"run_id": name}), encoding="utf-8")
        (tmp_path / name / "state.json").write_text(json.dumps({"done": done}), encoding="utf-8")
    assert main(["--list-runs"]) == 0
    out = capsys.readouterr().out
    assert "g1" in out and "t1" in out and "finished" in out and "resumable" in out and "dataset" in out


def test_a_resume_with_its_settings_but_no_record_yet_starts_the_run(tmp_path, monkeypatch, capsys):
    """V6.6.10: a Codespace retry sends the settings with `--resume`; when the first attempt never wrote its record, the run starts."""
    import cycle_retrain

    monkeypatch.setattr(cycle_retrain, "ram_preflight", lambda host, **kwargs: {"ok": True, "reason": "fits"})
    monkeypatch.setattr(cycle_retrain, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(cycle_retrain, "stack_actions", lambda *args, **kwargs: {})
    monkeypatch.setattr(cycle_retrain, "run_stages", lambda stages, acts, state_path: None)
    assert main(["--host", "local", "--procedure", "stack", "--run-id", "fresh", "--on-codespace", "--resume", "fresh"]) == 0
    assert "no resume record for fresh yet: starting it" in capsys.readouterr().out and (tmp_path / "retrain_fresh" / "resume.json").exists()
