"""evaluation/research_cycle.py: the RAM preflight, what is due, and a schedule that renders without installing."""

from __future__ import annotations

from pathlib import Path

import pytest

from evaluation.research_cycle import (
    BOOTSTRAP_STAGE,
    RETRAIN_STAGES,
    due_actions,
    install_command,
    ram_preflight,
    render_schedule,
    retrain_due,
    retrain_stages,
    sessions_since_retrain,
    status_view,
    total_memory_bytes,
)

GIB = 1024 ** 3
HEALTHY = {"chain_valid": True, "generations": {"g1": {"sessions": 10, "sharpe": 0.4}}, "latest_allocation": {"shares": {"g1": 1.0}, "states": {"g1": "healthy"}, "tbills": 0.0}}
ACTIVE = {"g1": {"stage": "active", "tier": "installed", "kind": "rule"}}


def test_this_pc_refuses_with_the_numbers():
    report = ram_preflight("local", total_bytes=4 * GIB)
    assert report["ok"] is False and report["total_gb"] == 4.0 and "14 GB needed" in report["reason"] and "--smoke" in report["reason"]


def test_a_laptop_with_the_ram_may_train():
    assert ram_preflight("local", total_bytes=16 * GIB)["ok"] is True


def test_the_minimum_is_a_setting():
    assert ram_preflight("local", total_bytes=16 * GIB, min_gb=32.0)["ok"] is False


def test_the_codespace_host_needs_no_ram_here():
    assert ram_preflight("codespace", total_bytes=1)["ok"] is True


def test_an_unknown_host_is_an_error():
    with pytest.raises(ValueError):
        ram_preflight("somewhere")


def test_this_machines_memory_reads_as_a_number():
    total = total_memory_bytes()
    assert total is None or total > GIB // 2


def test_a_fresh_checkout_builds_its_data_first():
    assert retrain_stages(data_present=False) == [BOOTSTRAP_STAGE, *RETRAIN_STAGES]
    assert retrain_stages(data_present=True) == list(RETRAIN_STAGES)


@pytest.mark.parametrize("since,states,due", [
    (10, {"g1": "healthy"}, False), (252, {"g1": "healthy"}, True), (None, {}, True), (10, {"g1": "decaying"}, True), (10, {"g1": "tripped"}, True), (10, {"g1": "watch"}, False),
])
def test_when_a_retrain_is_due(since, states, due):
    assert retrain_due(sessions_since_retrain=since, decay_states=states)["due"] is due


def _names(actions):
    return [item["action"] for item in actions]


MODEL = {"m1": {"stage": "active", "tier": "tier1", "kind": "model"}}


def test_a_retrain_is_due_only_where_there_is_a_model_to_refit():
    assert "aq cycle retrain --host codespace" in _names(due_actions(MODEL, HEALTHY, session="s", sessions_since_retrain=300))
    assert "aq cycle retrain --host codespace" not in _names(due_actions(MODEL, HEALTHY, session="s", sessions_since_retrain=10))
    assert "aq cycle retrain --host codespace" not in _names(due_actions(ACTIVE, HEALTHY, session="s", sessions_since_retrain=None)), "the installed book is a rule"


def test_a_decaying_rule_calls_for_a_new_round():
    judged = {**HEALTHY, "latest_allocation": {"shares": {"g1": 1.0}, "states": {"g1": "decaying"}}}
    assert any("write a new round" in name for name in _names(due_actions(ACTIVE, judged, session="s")))


def test_a_smoke_run_is_no_retrain_on_record(tmp_path):
    (tmp_path / "retrain_a").mkdir()
    (tmp_path / "retrain_a" / "state.json").write_text('{"done": {"register": {"at": "2026-11-01T00:00:00", "result": "skipped"}}}', encoding="utf-8")
    assert sessions_since_retrain(tmp_path, ["2026-11-02"]) is None
    (tmp_path / "retrain_b").mkdir()
    (tmp_path / "retrain_b" / "state.json").write_text('{"done": {"register": {"at": "2026-11-01T00:00:00", "result": {"procedure": "k06"}}}}', encoding="utf-8")
    assert sessions_since_retrain(tmp_path, ["2026-10-30", "2026-11-02", "2026-11-03"]) == 2


def test_before_any_allocation_the_active_generation_holds_the_book():
    view = status_view(ACTIVE, {"chain_valid": True, "generations": {}}, [], session=None, policy={})
    assert view["generations"][0]["share"] == 1.0


def test_a_broken_chain_comes_first():
    actions = due_actions(ACTIVE, {"chain_valid": False, "first_broken_row": 3}, session="s")
    assert actions[0]["action"] == "investigate" and "row 3" in actions[0]["why"]


def test_a_stale_ledger_is_due():
    assert "gh workflow enable research-cycle.yml" in _names(due_actions(ACTIVE, HEALTHY, session="s", sessions_behind=4, sessions_since_retrain=1))
    assert "gh workflow enable research-cycle.yml" not in _names(due_actions(ACTIVE, HEALTHY, session="s", sessions_behind=3, sessions_since_retrain=1))


@pytest.mark.parametrize("sessions,due", [(59, False), (60, True), (61, False), (252, True)])
def test_judgement_is_due_at_the_checkpoints(sessions, due):
    judged = {**HEALTHY, "generations": {"g1": {"sessions": sessions}}}
    assert any("judge g1" in name for name in _names(due_actions(ACTIVE, judged, session="s", sessions_since_retrain=1))) is due


def test_a_dead_generation_should_be_retired_in_the_registry():
    judged = {**HEALTHY, "latest_allocation": {"shares": {"g1": 0.0}, "states": {"g1": "dead"}}}
    assert "aq cycle promote --generation g1 --to retired" in _names(due_actions(ACTIVE, judged, session="s", sessions_since_retrain=1))


def test_a_finished_ramp_should_become_active():
    judged = {**HEALTHY, "latest_allocation": {"shares": {"g2": 1.0}, "states": {"g2": "healthy"}}}
    assert "aq cycle promote --generation g2 --to active" in _names(due_actions({"g2": {"stage": "ramping"}}, judged, session="s", sessions_since_retrain=1))


def test_only_the_owner_brings_the_keys_or_flips_the_book():
    with_ramp = {"g2": {"stage": "ramping"}}
    actions = due_actions(with_ramp, HEALTHY, session="s", sessions_since_retrain=1, broker_keys=False, policy_enabled=False)
    urgent = {item["action"]: item["urgency"] for item in actions}
    assert urgent["bring the IB and Coinbase API keys (RUNBOOK: When the keys arrive)"] == "owner"
    assert urgent["set enabled in ml/generations/policy.json (owner decision)"] == "owner"
    assert not any("keys" in name for name in _names(due_actions(with_ramp, HEALTHY, session="s", sessions_since_retrain=1, broker_keys=True, policy_enabled=True)))


def test_the_status_view_holds_what_the_dashboard_reads():
    view = status_view(ACTIVE, HEALTHY, [{"action": "x"}], session="2026-11-06", policy={"enabled": False, "glide_policy": "fixed_252", "glide": {"glide_sessions": 252}})
    assert view["generations"][0]["share"] == 1.0 and view["generations"][0]["state"] == "healthy" and view["due"] == [{"action": "x"}] and view["enabled"] is False


def test_an_empty_ledger_still_gives_a_view():
    view = status_view({"g1": {"stage": "shadow"}}, {"chain_valid": True, "rows": 0, "generations": {}}, [], session=None, policy={})
    assert view["generations"][0]["share"] == 0.0 and view["session"] is None


def test_a_schedule_renders_for_each_platform_and_installs_nothing():
    repo = Path("/work/aq")
    linux = render_schedule("linux", repo=repo)
    assert linux.startswith("0 3 * * 0 ") and "--if-due" in linux and "--host local" in linux
    windows = render_schedule("windows", repo=repo, host="codespace")
    assert "<Task" in windows and "--host codespace --if-due" in windows and "DisallowStartIfOnBatteries" in windows
    assert install_command("windows", task_file=Path("t.xml"))[0] == "schtasks"
    assert install_command("linux", task_file=Path("t"))[0] == "crontab"
    with pytest.raises(ValueError):
        render_schedule("beos", repo=repo)


# --- V6.6.9: the model stack's retrain (#395) -------------------------------------------------------------------------------


def test_the_stack_plan_names_every_stage_and_never_writes_over_the_installed_models():
    from evaluation.research_cycle import STACK_STAGES, stack_plan, stack_stages

    plan = stack_plan({"mode": "expanding"}, run_id="r1", python="py", score_end="2023-06-30", resume_id="walk-forward-abc")
    assert [stage for stage, _ in plan] == list(STACK_STAGES) == stack_stages()
    commands = dict(plan)
    assert commands["dataset"] == ["py", "train.py", "--candidate", "--version-id", "r1_base"]
    assert commands["multitask"][-1] == "r1_mt" and commands["sequence"][-1] == "r1_seq" and commands["gating"][-1] == "r1_gate"
    assert commands["walk_forward"][-2:] == ["--resume-run-id", "walk-forward-abc"] and "--include-sequence" in commands["walk_forward"]
    assert commands["scores"] == ["py", "scripts/v650_ml_scores.py", "--run-id", "walk-forward-abc", "--end", "2023-06-30"]
    assert commands["snapshot_active"] is None and commands["pins"] is None and commands["register"] is None
    bare = dict(stack_plan({}, run_id="r1"))
    assert bare["scores"] is None and "--resume-run-id" not in bare["walk_forward"] and bare["walk_forward"][-1] == "expanding"
    assert dict(stack_plan({}, run_id="r1", score_end="2023-06-30"))["scores"][3] == "<walk-forward run id>"


def test_a_planned_flag_a_trainer_does_not_list_is_named():
    from types import SimpleNamespace

    from evaluation.research_cycle import stack_plan, validate_plan_flags

    plan = stack_plan({}, run_id="r1", python="py", score_end="2023-06-30", resume_id="x")
    helps = {"train.py": "--candidate --version-id --walk-forward --include-multitask --include-sequence --mode --resume-run-id",
             "train_multitask.py": "--version-id", "train_sequence.py": "--version-id", "train_gating.py": "--version-id",
             "scripts/feature_parity_audit.py": "--skip-synthetic", "scripts/v650_ml_scores.py": "--run-id --end", "data_pipeline.factor_file_backfill": "--audit"}
    seen = []

    def runner(command, **kwargs):
        seen.append(command)
        key = command[2] if command[1] == "-m" else command[1]
        return SimpleNamespace(returncode=0, stdout=helps[key], stderr="")

    assert validate_plan_flags(plan, runner=runner) == [] and len(seen) == 8 and seen[0][-1] == "--help"
    helps["train.py"] = helps["train.py"].replace("--resume-run-id", "")
    assert validate_plan_flags(plan, runner=runner) == ["train.py: --resume-run-id"]

    def failing(command, **kwargs):
        return SimpleNamespace(returncode=2, stdout="", stderr="no such file")

    assert validate_plan_flags(plan, runner=failing)[0] == "factor_audit: `-m data_pipeline.factor_file_backfill --help` exit 2"


def test_aging_models_suggest_a_retrain_before_the_kill_switch_stops_them():
    assert "aq cycle retrain --host codespace --procedure stack" not in _names(due_actions(MODEL, HEALTHY, session="s", sessions_since_retrain=10, model_age_days=100.0))
    soon = due_actions(MODEL, HEALTHY, session="s", sessions_since_retrain=10, model_age_days=160.0)
    assert "aq cycle retrain --host codespace --procedure stack" in _names(soon)
    assert "20 days left" in next(item["why"] for item in soon if item["action"].endswith("--procedure stack"))
    already = due_actions(MODEL, HEALTHY, session="s", sessions_since_retrain=300, model_age_days=170.0)
    assert _names(already).count("aq cycle retrain --host codespace") == 1 and "aq cycle retrain --host codespace --procedure stack" not in _names(already)
    assert "aq cycle retrain --host codespace --procedure stack" not in _names(due_actions(ACTIVE, HEALTHY, session="s", model_age_days=170.0))


def test_an_installed_blends_fixed_shares_are_what_the_view_shows_until_the_glide_writes_a_row():
    two = {"g1": {"stage": "active", "tier": "installed", "kind": "rule"}, "g6": {"stage": "active", "tier": "installed", "kind": "model"}}
    view = status_view(two, {"chain_valid": True, "generations": {}}, [], session=None, policy={"enabled": False, "installed_shares": {"g1": 0.7, "g6": 0.3, "gone": 1.0}})
    assert {row["id"]: row["share"] for row in view["generations"]} == {"g1": 0.7, "g6": 0.3}
    unset = status_view(two, {"chain_valid": True, "generations": {}}, [], session=None, policy={})
    assert {row["id"]: row["share"] for row in unset["generations"]} == {"g1": 0.5, "g6": 0.5}
    judged = {"chain_valid": True, "generations": {}, "latest_allocation": {"shares": {"g1": 0.6, "g6": 0.4}, "states": {}}}
    assert {row["id"]: row["share"] for row in status_view(two, judged, [], session=None, policy={"installed_shares": {"g1": 0.7, "g6": 0.3}})["generations"]} == {"g1": 0.6, "g6": 0.4}
