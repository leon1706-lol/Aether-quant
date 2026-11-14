"""aq cycle, aq research, aq prove and the dashboard command (V6.6.6, #359): dispatch, stages and refusals, with the heavy callees stubbed."""

from __future__ import annotations

import argparse
import json
import shutil
from types import SimpleNamespace

import pytest

import aq_cli
from script_loader import ROOT


@pytest.fixture
def cycle(tmp_path, monkeypatch):
    generations = tmp_path / "ml" / "generations"
    shutil.copytree(ROOT / "ml" / "generations", generations)
    monkeypatch.setattr(aq_cli, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(aq_cli, "ML_DIR", tmp_path / "ml")
    return SimpleNamespace(root=tmp_path, generations=generations)


def _ns(**kwargs):
    return argparse.Namespace(**kwargs)


def test_research_reports_the_ic_of_a_signal_by_split_and_horizon(cycle, monkeypatch, capsys):
    import evaluation.research_runners as runners

    row = {"num_dates": 40, "mean_ic": 0.02, "t": 1.5, "nonoverlap_t": 1.1, "hac_t": 1.2, "ci95": [0.0, 0.04]}
    monkeypatch.setattr(runners, "run_signal_report", lambda signal, dataset, horizons: {"splits": {"backtest": {"h1": row, "h5": {"num_dates": 0}}, "validation": {}}})
    assert aq_cli.cmd_research(_ns(horizons="1, 5,", signal="s.csv", dataset=None, out=None)) == 0
    assert "backtest   h1" in capsys.readouterr().out and (cycle.root / "ml" / "evaluation" / "signal_report.json").exists()
    assert aq_cli.cmd_research(_ns(horizons="1", signal="s.csv", dataset=None, out=str(cycle.root / "out.json"))) == 0 and (cycle.root / "out.json").exists()


def test_every_research_stage_calls_its_round_function(cycle, monkeypatch, capsys):
    from evaluation import research_round as rounds

    spec = SimpleNamespace(out_dir=cycle.root / "round")
    seen = []
    monkeypatch.setattr(rounds, "write_rules", lambda payload, path: seen.append("rules") or "digest")
    monkeypatch.setattr(rounds, "load_round", lambda path, root: spec)
    monkeypatch.setattr(rounds, "_load_selection_cell", lambda spec, root: "cell")
    monkeypatch.setattr(rounds, "stage_score", lambda spec, **kwargs: seen.append(("score", kwargs["only"], kwargs["force"])))
    monkeypatch.setattr(rounds, "stage_placebo", lambda spec, **kwargs: seen.append(("placebo", kwargs["draws"])))
    monkeypatch.setattr(rounds, "stage_gate", lambda spec: {"gate": 1})
    monkeypatch.setattr(rounds, "stage_pbo", lambda spec, root: {"pbo": 0.4})
    monkeypatch.setattr(rounds, "stage_report", lambda spec, alpha_fn: {"report": 1, "trials": [1]})
    monkeypatch.setattr(rounds, "stage_freeze", lambda spec, payload, holdout_ledger: (cycle.root / "freeze.json", "abc"))
    monkeypatch.setattr(rounds, "stage_hold", lambda spec, trial, **kwargs: {"verdict": "no survivor", "digest": kwargs["digest"]})
    draft = cycle.root / "draft.json"
    draft.write_text("{}", encoding="utf-8")
    base = dict(round="round.json", draft=str(draft), only=None, force=False, draws=7, trial=None, digest=None)
    assert aq_cli._cycle_research(_ns(stage="rules", **base)) == 0 and "digest" in capsys.readouterr().out
    assert aq_cli._cycle_research(_ns(stage="score", **{**base, "only": ["a"], "force": True})) == 0
    assert aq_cli._cycle_research(_ns(stage="placebo", **base)) == 0
    for stage, fragment in (("gate", '"gate"'), ("pbo", '"pbo"'), ("report", '"report"')):
        assert aq_cli._cycle_research(_ns(stage=stage, **base)) == 0 and fragment in capsys.readouterr().out
    assert "trials" not in capsys.readouterr().out
    assert aq_cli._cycle_research(_ns(stage="freeze", **base)) == 2 and aq_cli._cycle_research(_ns(stage="freeze", **{**base, "trial": "k1"})) == 0
    assert aq_cli._cycle_research(_ns(stage="hold", **base)) == 2 and aq_cli._cycle_research(_ns(stage="hold", **{**base, "trial": "k1", "digest": "abc"})) == 0
    assert ("score", ("a",), True) in seen and ("placebo", 7) in seen


def test_the_round_alpha_function_regresses_against_the_three_benchmarks(cycle, monkeypatch):
    import pandas as pd

    import evaluation.alpha_proof as alpha_proof

    monkeypatch.setattr(alpha_proof, "benchmark_daily_returns", lambda root, assets, tickers, **kwargs: pd.DataFrame({"SPY": [0.0, 0.1]}, index=["2025-01-02", "2025-01-03"]))
    monkeypatch.setattr(alpha_proof, "to_sessions", lambda series, index: series)
    monkeypatch.setattr(alpha_proof, "alpha_regression", lambda series, bench: {"n": len(series)})
    assert aq_cli._round_alpha_fn()(pd.Series([0.01, 0.02], index=["2025-01-02", "2025-01-03"])) == {"n": 2}


def test_the_ledger_comes_from_a_file_or_the_branch(cycle, monkeypatch, capsys):
    row = {"payload": {"session": "2026-11-02"}}
    ledger = cycle.root / "ledger.jsonl"
    from evaluation.forward_ledger import append_row

    append_row(ledger, session="2026-11-02", candidate="g", payload={"status": "ok"}, created_at="2026-11-02T22:45:00+00:00")
    assert len(aq_cli._cycle_ledger_rows(_ns(ledger_file=str(ledger)))) == 1
    calls = []

    def run(command, **kwargs):
        calls.append(command[1])
        if command[1] == "fetch":
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout=json.dumps(row) + "\n\n", stderr="")

    monkeypatch.setattr(aq_cli.subprocess, "run", run)
    assert aq_cli._cycle_ledger_rows(_ns()) == [row] and "could not fetch" in capsys.readouterr().err
    monkeypatch.setattr(aq_cli.subprocess, "run", lambda command, **kwargs: SimpleNamespace(returncode=1 if command[1] == "show" else 0, stdout="", stderr=""))
    assert aq_cli._cycle_ledger_rows(_ns()) == []


def test_status_is_written_and_the_chain_decides_the_exit(cycle, monkeypatch, capsys):
    import evaluation.generation_ledger as ledger_module
    import evaluation.research_cycle as research_cycle

    monkeypatch.setattr(aq_cli, "_cycle_ledger_rows", lambda args: [{"payload": {"session": "2026-11-02"}}])
    monkeypatch.setattr(aq_cli, "_broker_keys_present", lambda: False)
    monkeypatch.setattr(ledger_module, "judge_generations", lambda rows: {"chain_valid": True, "generations": {}})
    monkeypatch.setattr(research_cycle, "due_actions", lambda *args, **kwargs: [{"action": "aq cycle retrain k06"}])
    monkeypatch.setattr(research_cycle, "status_view", lambda *args, **kwargs: {"chain_valid": True, "due": [{"action": "aq cycle retrain k06"}]})
    assert aq_cli.cmd_cycle(_ns(cycle_command="status")) == 0 and (cycle.generations / "status.json").exists()
    monkeypatch.setattr(research_cycle, "status_view", lambda *args, **kwargs: {"chain_valid": False, "due": []})
    assert aq_cli.cmd_cycle(_ns(cycle_command="status")) == 1
    monkeypatch.setattr(aq_cli, "_cycle_ledger_rows", lambda args: [])
    assert aq_cli._cycle_status(_ns(), write=False)["chain_valid"] is False


def test_a_stage_changes_only_by_rule_or_to_take_risk_off(cycle, monkeypatch, capsys):
    import evaluation.generation_registry as registry_module
    import evaluation.generation_ledger as ledger_module

    monkeypatch.setattr(aq_cli, "_cycle_ledger_rows", lambda args: [])
    monkeypatch.setattr(ledger_module, "judge_generations", lambda rows: {"chain_valid": True, "generations": {}, "latest_allocation": {"shares": {"g0001": 0.0, "g0002": 0.5}}})
    monkeypatch.setattr(ledger_module, "evidence_for", lambda *args, **kwargs: {})
    monkeypatch.setattr(registry_module, "next_stage", lambda generation, evidence: "active")
    assert aq_cli._cycle_promote(_ns(generation="nobody", to="active")) == 2 and "not in the registry" in capsys.readouterr().err
    assert aq_cli._cycle_promote(_ns(generation="g0001", to="shadow")) == 2 and "refused" in capsys.readouterr().err
    assert aq_cli._cycle_promote(_ns(generation="g0001", to="retired")) == 0
    text = capsys.readouterr().out
    assert "g0001: active -> retired" in text and "lifecycle intact" in text
    monkeypatch.setattr(ledger_module, "judge_generations", lambda rows: {"chain_valid": False})
    assert aq_cli._cycle_promote(_ns(generation="g0002", to="active")) == 1 and "chain is broken" in capsys.readouterr().err


def test_a_ramping_generation_with_the_whole_book_may_go_active(cycle, monkeypatch, capsys):
    from dataclasses import replace

    import evaluation.generation_ledger as ledger_module
    import evaluation.generation_registry as registry_module

    registry = registry_module.load_registry(cycle.generations / "registry.json")
    registry["g0002"] = replace(registry["g0002"], stage="ramping")
    registry_module.save_registry(cycle.generations / "registry.json", registry)
    monkeypatch.setattr(aq_cli, "_cycle_ledger_rows", lambda args: [{"payload": {}}])
    monkeypatch.setattr(ledger_module, "judge_generations", lambda rows: {"chain_valid": True, "generations": {}, "latest_allocation": {"shares": {"g0002": 1.0, "g0001": 0.0}}})
    monkeypatch.setattr(ledger_module, "evidence_for", lambda *args, **kwargs: {})
    monkeypatch.setattr(registry_module, "next_stage", lambda generation, evidence: "ramping")
    assert aq_cli._cycle_promote(_ns(generation="g0002", to="active")) == 0 and "ramping -> active" in capsys.readouterr().out


def test_the_schedule_is_shown_or_installed_only_where_the_ram_allows(cycle, monkeypatch, capsys):
    import evaluation.research_cycle as research_cycle

    monkeypatch.setattr(research_cycle, "render_schedule", lambda platform, repo, host: f"job for {platform}")
    monkeypatch.setattr(research_cycle, "install_command", lambda platform, task_file: ["install", str(task_file)])
    base = dict(platform="linux", host="local", dry_run=False)
    assert aq_cli._cycle_schedule(_ns(schedule_command="show", **base)) == 0 and "job for linux" in capsys.readouterr().out
    monkeypatch.setattr(research_cycle, "ram_preflight", lambda host: {"ok": False, "reason": "4 GB"})
    assert aq_cli._cycle_schedule(_ns(schedule_command="install", **base)) == 2 and "refusing to schedule" in capsys.readouterr().err
    monkeypatch.setattr(research_cycle, "ram_preflight", lambda host: {"ok": True})
    ran = []
    monkeypatch.setattr(aq_cli.subprocess, "run", lambda command, cwd: ran.append(command) or SimpleNamespace(returncode=0))
    assert aq_cli._cycle_schedule(_ns(schedule_command="install", **{**base, "platform": "windows"})) == 0
    assert (cycle.root / "ml" / "cycle" / "schedule.xml").exists() and ran
    assert aq_cli._cycle_schedule(_ns(schedule_command="install", **{**base, "platform": None})) == 0 and aq_cli._cycle_schedule(_ns(schedule_command="install", **{**base, "dry_run": True})) == 0


def test_retrain_and_the_script_commands_pass_their_arguments_on(cycle, monkeypatch):
    ran = []
    monkeypatch.setattr(aq_cli.subprocess, "run", lambda command, cwd: ran.append(command) or SimpleNamespace(returncode=0))
    base = dict(host="local", if_due=False, procedure=None, smoke=False, dry_run=False)
    assert aq_cli._cycle_retrain(_ns(**base)) == 2
    assert aq_cli._cycle_retrain(_ns(**{**base, "procedure": "k06", "dry_run": True})) == 0 and "--dry-run" in ran[-1] and "--procedure" in ran[-1]
    assert aq_cli._cycle_retrain(_ns(**{**base, "smoke": True})) == 0 and "--smoke" in ran[-1]
    monkeypatch.setattr(aq_cli, "_cycle_status", lambda args, write: {"due": [{"action": "something else"}]})
    assert aq_cli._cycle_retrain(_ns(**{**base, "if_due": True, "smoke": True})) == 0 and len(ran) == 2
    monkeypatch.setattr(aq_cli, "_cycle_status", lambda args, write: {"due": [{"action": "aq cycle retrain k06"}]})
    assert aq_cli._cycle_retrain(_ns(**{**base, "if_due": True, "smoke": True})) == 0 and len(ran) == 3
    assert aq_cli.cmd_cycle(_ns(cycle_command="daily", dry_run=True, ledger_file=None)) == 0 and "--dry-run" in ran[-1]
    assert aq_cli.cmd_cycle(_ns(cycle_command="decide", generation="g0005", weights="w.csv", ledger_file="l.jsonl", session="2026-11-02")) == 0 and "cycle_decide.py" in ran[-1][1]
    monkeypatch.setattr(aq_cli, "_cycle_retrain", lambda args: 7)
    monkeypatch.setattr(aq_cli, "_cycle_promote", lambda args: 8)
    monkeypatch.setattr(aq_cli, "_cycle_schedule", lambda args: 9)
    monkeypatch.setattr(aq_cli, "_cycle_research", lambda args: 10)
    assert [aq_cli.cmd_cycle(_ns(cycle_command=name)) for name in ("retrain", "promote", "schedule", "research")] == [7, 8, 9, 10]
    with pytest.raises(SystemExit):
        aq_cli.cmd_cycle(_ns(cycle_command="nope"))


def test_prove_scans_for_sorry_or_builds_with_lake(cycle, monkeypatch, capsys):
    formal = cycle.root / "formal"
    (formal / "AetherFormal").mkdir(parents=True)
    (formal / "AetherFormal" / "Good.lean").write_text("theorem a : True := trivial\n", encoding="utf-8")
    monkeypatch.setattr(aq_cli, "FORMAL_DIR", formal)
    assert aq_cli.cmd_prove(_ns(check_sorry=True)) == 0 and "0 sorry/admit" in capsys.readouterr().out
    (formal / "AetherFormal" / "Bad.lean").write_text("theorem b : True := by\n  sorry\n", encoding="utf-8")
    assert aq_cli.cmd_prove(_ns(check_sorry=True)) == 1 and "unfinished proof: formal" in capsys.readouterr().out
    monkeypatch.setattr(aq_cli.shutil, "which", lambda name: None)
    assert aq_cli.cmd_prove(_ns(check_sorry=False, module=None, regen_cases=False)) == 2 and "lake not found" in capsys.readouterr().err
    monkeypatch.setattr(aq_cli.shutil, "which", lambda name: "lake")
    built = []
    codes = iter([1, 0, 3, 0, 0])
    monkeypatch.setattr(aq_cli, "_run", lambda command, cwd=None: built.append(command) or next(codes))
    assert aq_cli.cmd_prove(_ns(check_sorry=False, module="Book", regen_cases=True)) == 1 and built[0][-1] == "AetherFormal.Book"
    assert aq_cli.cmd_prove(_ns(check_sorry=False, module=None, regen_cases=False)) == 0
    assert aq_cli.cmd_prove(_ns(check_sorry=False, module=None, regen_cases=True)) == 3
    cases = cycle.root / "cases"
    cases.mkdir()
    (cases / "x.json").write_text(json.dumps({"spec_files": []}), encoding="utf-8")
    monkeypatch.setattr(aq_cli, "FORMAL_CASES_DIR", cases)
    import aether_quant.formal as formal_module

    monkeypatch.setattr(formal_module, "spec_sha256", lambda directory, files: "sha")
    monkeypatch.setattr(aq_cli, "FORMAL_CASES_DIR", cases)
    monkeypatch.setattr(cases.__class__, "relative_to", lambda self, other: self, raising=False)
    assert aq_cli.cmd_prove(_ns(check_sorry=False, module=None, regen_cases=True)) == 0
    assert json.loads((cases / "x.json").read_text(encoding="utf-8"))["spec_sha256"] == "sha"


def test_the_dashboard_command_mounts_data_only_when_asked_and_the_webui_runs_docker_or_npm(cycle, monkeypatch, tmp_path):
    plain = aq_cli.dashboard_docker_command(image="img", port=8080, data=None)
    assert plain[-1] == "img" and "-v" not in plain and "127.0.0.1:8080:8000" in plain
    mounted = aq_cli.dashboard_docker_command(image="img", port=8080, data=str(tmp_path))
    assert "-v" in mounted and "AQ_DASHBOARD_DEMO=0" in mounted
    ran = []
    codes = iter([0, 0, 0, 4])
    monkeypatch.setattr(aq_cli, "_run", lambda command, cwd=None: ran.append(command) or next(codes, 0))
    assert aq_cli.cmd_webui(_ns(docker=True, image="img", build=False, port=8080, data=None)) == 0
    assert aq_cli.cmd_webui(_ns(docker=True, image="img", build=True, port=8080, data=str(tmp_path))) == 0 and ran[1][1] == "build" and "aether-quant-dashboard:latest" in ran[-1]
    assert aq_cli.cmd_webui(_ns(docker=True, image="img", build=True, port=8080, data=None)) == 4
    assert aq_cli.cmd_webui(_ns()) == 0 and ran[-1][1:] == ["run", "dev"]
