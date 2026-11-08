"""scripts/cycle_retrain.py: stages resume, a failure stops the run, and the Codespace always stops."""

from __future__ import annotations

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

    monkeypatch.setattr(cycle_retrain, "ram_preflight", lambda host, min_gb=14.0: {"ok": False, "reason": "4.0 GB of RAM, 14 GB needed"})
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
            return SimpleNamespace(returncode=0, stdout='[{"name": "c", "state": "%s"}]' % next(states), stderr="")
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
