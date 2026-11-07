"""`aq cycle`: argument parsing and the promote rule, against a registry in a temporary directory."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

import pytest

import aq_cli
from evaluation.generation_registry import Generation, lifecycle_is_intact, load_registry, save_registry

G = Generation(id="g1", kind="rule", tier="tier2", stage="shadow", born="2026-11-06", procedure_sha256="p")


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(aq_cli, "ML_DIR", tmp_path / "ml")
    monkeypatch.setattr(aq_cli, "ROOT_DIR", tmp_path)
    generations = tmp_path / "ml" / "generations"
    generations.mkdir(parents=True)
    save_registry(generations / "registry.json", {"g1": G})
    (generations / "policy.json").write_text(json.dumps({"enabled": False, "glide_policy": "fixed_252", "glide": {"glide_sessions": 252}}), encoding="utf-8")
    return generations


def _args(**values) -> argparse.Namespace:
    return argparse.Namespace(ledger_file=values.pop("ledger_file", None), **values)


def _empty_ledger(generations: Path) -> str:
    path = generations.parent / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    return str(path)


def test_every_verb_parses():
    parser = aq_cli.build_parser() if hasattr(aq_cli, "build_parser") else None
    if parser is None:
        pytest.skip("the parser is built inside main")
    for argv in (["cycle", "status"], ["cycle", "daily", "--dry-run"], ["cycle", "retrain", "--host", "local", "--smoke"], ["cycle", "schedule", "show"]):
        assert parser.parse_args(argv).func is aq_cli.cmd_cycle


def test_status_writes_the_view_with_no_ledger_yet(dirs):
    view = aq_cli._cycle_status(_args(ledger_file=_empty_ledger(dirs)))
    assert view["generations"][0]["id"] == "g1" and view["chain_valid"] is True
    assert json.loads((dirs / "status.json").read_text(encoding="utf-8"))["generations"][0]["id"] == "g1"
    assert any("keys" in item["action"] for item in view["due"])


def test_promote_refuses_a_jump_the_rule_forbids(dirs, capsys):
    assert aq_cli._cycle_promote(_args(generation="g1", to="ramping", ledger_file=_empty_ledger(dirs))) == 2
    assert "refused" in capsys.readouterr().err
    assert load_registry(dirs / "registry.json")["g1"].stage == "shadow"


def test_promote_refuses_an_unknown_generation(dirs):
    assert aq_cli._cycle_promote(_args(generation="nobody", to="retired", ledger_file=_empty_ledger(dirs))) == 2


def test_taking_risk_off_is_always_allowed_and_logged(dirs):
    save_registry(dirs / "registry.json", {"g1": replace(G, stage="active")})
    assert aq_cli._cycle_promote(_args(generation="g1", to="retired", ledger_file=_empty_ledger(dirs))) == 0
    assert load_registry(dirs / "registry.json")["g1"].stage == "retired"
    assert lifecycle_is_intact(dirs / "lifecycle.jsonl") == (True, None)


def test_a_full_pass_may_ramp_by_rule(dirs):
    save_registry(dirs / "registry.json", {"g1": replace(G, admission={"edge_pass": True})})
    assert aq_cli._cycle_promote(_args(generation="g1", to="ramping", ledger_file=_empty_ledger(dirs))) == 0
    assert load_registry(dirs / "registry.json")["g1"].stage == "ramping"


def test_a_broken_chain_moves_nothing(dirs):
    path = dirs.parent / "broken.jsonl"
    path.write_text(json.dumps({"prev_hash": "x", "event_type": "e", "created_at": "t", "payload": {"candidate": "g1"}, "hash": "y"}) + "\n", encoding="utf-8")
    save_registry(dirs / "registry.json", {"g1": replace(G, stage="active")})
    assert aq_cli._cycle_promote(_args(generation="g1", to="retired", ledger_file=str(path))) == 1
    assert load_registry(dirs / "registry.json")["g1"].stage == "active"


def test_show_and_a_dry_run_install_nothing(dirs, monkeypatch, capsys):
    monkeypatch.setattr(aq_cli.subprocess, "run", lambda *a, **k: pytest.fail("nothing may be registered"))
    assert aq_cli._cycle_schedule(argparse.Namespace(schedule_command="show", platform="linux", host="local", dry_run=False)) == 0
    assert "--if-due" in capsys.readouterr().out
    assert aq_cli._cycle_schedule(argparse.Namespace(schedule_command="install", platform="windows", host="local", dry_run=True)) == 0


def test_install_refuses_a_machine_under_the_minimum(dirs, monkeypatch, capsys):
    import evaluation.research_cycle as cycle

    monkeypatch.setattr(cycle, "ram_preflight", lambda host: {"ok": False, "reason": "4.0 GB of RAM, 14 GB needed"})
    monkeypatch.setattr(aq_cli.subprocess, "run", lambda *a, **k: pytest.fail("nothing may be registered"))
    assert aq_cli._cycle_schedule(argparse.Namespace(schedule_command="install", platform="windows", host="local", dry_run=False)) == 2
    assert "refusing" in capsys.readouterr().err


def test_if_due_does_nothing_when_nothing_is_due(dirs, monkeypatch):
    monkeypatch.setattr(aq_cli, "_cycle_status", lambda args, write=True: {"due": [{"action": "bring the keys"}], "chain_valid": True})
    monkeypatch.setattr(aq_cli.subprocess, "run", lambda *a, **k: pytest.fail("nothing is due"))
    assert aq_cli._cycle_retrain(argparse.Namespace(host="local", procedure="k06", smoke=False, dry_run=False, if_due=True, ledger_file=None)) == 0
