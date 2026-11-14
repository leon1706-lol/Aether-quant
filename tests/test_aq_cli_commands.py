"""The smaller aq commands' last branches (V6.6.6, #359): the Lean binary lookup, users, live readiness, live deployments, secrets,
the secret scan and ml cleanup, with every outside call stubbed."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from types import SimpleNamespace


import aq_cli
from script_loader import ROOT


def _ns(**kwargs):
    return argparse.Namespace(**kwargs)


def test_the_lean_binary_is_the_one_that_is_not_lean_4(tmp_path, monkeypatch):
    monkeypatch.setattr(aq_cli, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(aq_cli.sys, "platform", "linux")
    venv = tmp_path / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "lean").write_text("", encoding="utf-8")
    on_path = "/usr/bin/lean"
    monkeypatch.setattr(aq_cli.shutil, "which", lambda name: on_path)
    answers = {str(venv / "lean"): "Lean (version 4.9.0)", on_path: "lean-cli 1.0"}

    def run(command, **kwargs):
        return SimpleNamespace(stdout=answers[command[0]], stderr="")

    monkeypatch.setattr(aq_cli.subprocess, "run", run)
    assert aq_cli._find_quantconnect_lean_binary() == on_path
    answers[on_path] = "Lean (version 4.1)"
    assert aq_cli._find_quantconnect_lean_binary() is None

    def slow(command, **kwargs):
        raise aq_cli.subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(aq_cli.subprocess, "run", slow)
    assert aq_cli._find_quantconnect_lean_binary() is None
    monkeypatch.setattr(aq_cli.shutil, "which", lambda name: None)
    (venv / "lean").unlink()
    assert aq_cli._find_quantconnect_lean_binary() is None
    monkeypatch.setattr(aq_cli.sys, "platform", "win32")
    assert aq_cli._find_quantconnect_lean_binary() is None


def test_users_are_added_listed_and_removed_with_a_token_shown_once(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AQ_USERS_FILE", str(tmp_path / "users.json"))
    assert aq_cli.cmd_users(_ns(users_command="list")) == 0 and "no users" in capsys.readouterr().out
    assert aq_cli.cmd_users(_ns(users_command="add", name="ana", role="admin", accounts="a1, a2")) == 0
    text = capsys.readouterr().out
    assert "added ana (admin, accounts a1,a2)" in text and "token (shown once" in text
    assert aq_cli.cmd_users(_ns(users_command="add", name="ana", role="admin", accounts=None)) == 1 and "exists" in capsys.readouterr().err
    assert aq_cli.cmd_users(_ns(users_command="add", name="bob", role="wizard", accounts=None)) == 2
    assert aq_cli.cmd_users(_ns(users_command="list")) == 0 and "ana" in capsys.readouterr().out
    assert aq_cli.cmd_users(_ns(users_command="remove", name="nobody")) == 1 and aq_cli.cmd_users(_ns(users_command="remove", name="ana")) == 0
    (tmp_path / "users.json").write_text("{torn", encoding="utf-8")
    assert aq_cli.cmd_users(_ns(users_command="list")) == 1 and "is invalid" in capsys.readouterr().err


def test_live_readiness_prints_marks_writes_and_exits_on_the_verdict(tmp_path, monkeypatch, capsys):
    import execution.live_readiness as readiness
    import execution.live_readiness_io as readiness_io

    monkeypatch.setattr(aq_cli, "ROOT_DIR", tmp_path)
    metric = SimpleNamespace(status="pass", group="paper", label="rebalances", value=None, threshold=">= 6")
    scorecard = SimpleNamespace(ready=False, account="default", metrics=[metric], to_dict=lambda: {"counts": {"pass": 1, "fail": 0, "unknown": 0}})
    seen = {}
    monkeypatch.setattr(readiness_io, "readiness_scorecard", lambda root, account, paper_check: seen.update(paper_check=paper_check, account=account) or scorecard)
    monkeypatch.setattr(readiness_io, "write_scorecard", lambda root, card: tmp_path / "state" / "scorecard.json")
    monkeypatch.setattr(readiness_io, "write_docs_block", lambda target, text: target.name == "paper-to-live.md" and (tmp_path / "docs").exists())
    monkeypatch.setattr(readiness, "render_markdown", lambda card: "| table |")
    (tmp_path / "state").mkdir()
    base = dict(paper_check=None, account=None, markdown=False, no_write=False, docs=False, json=None)
    assert aq_cli.cmd_live_readiness(_ns(**base)) == 1
    text = capsys.readouterr().out
    assert "NOT READY for live capital" in text and "[ pass  ] paper" in text and "wrote state/scorecard.json" in text
    paper = tmp_path / "paper.json"
    paper.write_text(json.dumps({"inside": True}), encoding="utf-8")
    out = tmp_path / "card.json"
    assert aq_cli.cmd_live_readiness(_ns(**{**base, "paper_check": str(paper), "markdown": True, "no_write": True, "docs": True, "json": str(out), "account": "desk"})) == 1
    text = capsys.readouterr().out
    assert "| table |" in text and "no AQ:READINESS markers in docs/live/paper-to-live.md" in text and seen == {"paper_check": {"inside": True}, "account": "desk"} and out.exists()
    scorecard.ready = True
    (tmp_path / "docs").mkdir()
    assert aq_cli.cmd_live_readiness(_ns(**{**base, "no_write": True, "docs": True})) == 0 and "updated docs/live/paper-to-live.md" in capsys.readouterr().out
    assert aq_cli.cmd_live_readiness(_ns(**{**base, "paper_check": str(tmp_path / "none.json")})) == 2


def test_a_live_deployment_names_its_container_renders_commands_and_refuses_without_a_config(tmp_path, monkeypatch, capsys):
    from execution.accounts import Account

    monkeypatch.setattr(aq_cli, "ROOT_DIR", tmp_path)
    paper = SimpleNamespace(id="default", is_default=True, broker="paper", lean_environment="live-paper")
    desk = SimpleNamespace(id="desk", is_default=False, broker="coinbase", lean_environment="live-coinbase")
    assert aq_cli.live_container_name(paper) == "aether-quant-lean-live" and aq_cli.live_container_name(desk) == "aether-quant-lean-live-desk"
    commands, env = aq_cli.live_compose_commands(desk, lean_config="lean.live.desk.json")
    assert env["AQ_ACCOUNT"] == "desk" and commands[1][-1] == "aether-quant-lean-live-desk"
    accounts = {"default": paper, "desk": desk}
    monkeypatch.setattr(aq_cli, "_accounts_or_error", lambda: list(accounts.values()))
    import execution.accounts as accounts_module

    monkeypatch.setattr(accounts_module, "resolve_account", lambda registry, name: accounts[name or "default"] if (name or "default") in accounts else (_ for _ in ()).throw(ValueError("no account " + str(name))))
    assert aq_cli.cmd_live(_ns(account="nobody", live_command="up", dry_run=True)) == 1 and "no account" in capsys.readouterr().err
    assert aq_cli.cmd_live(_ns(account="desk", live_command="up", dry_run=True)) == 1 and "aq render-lean-config --account desk" in capsys.readouterr().err
    (tmp_path / "lean.live.desk.json").write_text("{}", encoding="utf-8")
    assert aq_cli.cmd_live(_ns(account="desk", live_command="up", dry_run=True)) == 0 and "docker compose" in capsys.readouterr().out
    assert aq_cli.cmd_live(_ns(account="default", live_command="up", dry_run=True)) == 0
    ran = []
    codes = iter([0, 5])
    monkeypatch.setattr(aq_cli.subprocess, "run", lambda command, cwd, env, check: ran.append(command) or SimpleNamespace(returncode=next(codes)))
    assert aq_cli.cmd_live(_ns(account="desk", live_command="up", dry_run=False)) == 5 and len(ran) == 2
    codes = iter([0, 0])
    assert aq_cli.cmd_live(_ns(account="desk", live_command="up", dry_run=False)) == 0 and len(ran) == 4
    assert aq_cli.cmd_live(_ns(account="desk", live_command="down", dry_run=True)) == 0 and "docker rm -f" in capsys.readouterr().out
    monkeypatch.setattr(aq_cli, "_run", lambda command: 0)
    assert aq_cli.cmd_live(_ns(account="desk", live_command="down", dry_run=False)) == 0
    assert Account is not None


def test_secrets_status_set_delete_and_unknown_names(tmp_path, monkeypatch, capsys):
    import getpass

    import execution.secrets_io as secrets_io
    from execution.secrets import SECRET_NAMES

    rows = [{"name": SECRET_NAMES[0], "resolved": True, "stored_safely": True, "where": "keyring"}, {"name": SECRET_NAMES[1], "resolved": True, "stored_safely": False, "where": "env"},
            {"name": SECRET_NAMES[2], "resolved": False, "stored_safely": False, "where": None}]
    monkeypatch.setattr(secrets_io, "all_secret_status", lambda account: rows)
    out = tmp_path / "status.json"
    assert aq_cli.cmd_secrets(_ns(secrets_command="status", account=None, json=str(out))) == 0
    text = capsys.readouterr().out
    assert "stored safely" in text and "plain environment variable" in text and "not set" in text and out.exists()
    assert aq_cli.cmd_secrets(_ns(secrets_command="set", account=None, name="nope")) == 2
    stored = []
    monkeypatch.setattr(secrets_io, "keyring_set", lambda name, value, account: stored.append((name, value)))
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "hunter2")
    assert aq_cli.cmd_secrets(_ns(secrets_command="set", account="desk", name=SECRET_NAMES[0].lower())) == 0 and stored == [(SECRET_NAMES[0], "hunter2")]
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "")
    assert aq_cli.cmd_secrets(_ns(secrets_command="set", account=None, name=SECRET_NAMES[0])) == 1
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "x")
    monkeypatch.setattr(secrets_io, "keyring_set", lambda name, value, account: (_ for _ in ()).throw(RuntimeError("no keyring")))
    assert aq_cli.cmd_secrets(_ns(secrets_command="set", account=None, name=SECRET_NAMES[0])) == 1 and "no keyring" in capsys.readouterr().err
    monkeypatch.setattr(secrets_io, "keyring_delete", lambda name, account: name == SECRET_NAMES[0])
    assert aq_cli.cmd_secrets(_ns(secrets_command="delete", account=None, name=SECRET_NAMES[0])) == 0 and "removed" in capsys.readouterr().out
    assert aq_cli.cmd_secrets(_ns(secrets_command="delete", account=None, name=SECRET_NAMES[1])) == 0 and "nothing stored" in capsys.readouterr().out


def test_the_secret_scan_fails_on_a_populated_field_or_a_tracked_env_file(tmp_path, monkeypatch, capsys):
    import execution.secret_scan as secret_scan

    monkeypatch.setattr(aq_cli, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(aq_cli, "LEAN_JSON_PATH", tmp_path / "lean.json")
    (tmp_path / "lean.json").write_text(json.dumps({"ib-password": "hunter2"}), encoding="utf-8")
    monkeypatch.setattr(secret_scan, "find_populated_secret_fields", lambda config: ["ib-password"])
    monkeypatch.setattr(aq_cli.subprocess, "run", lambda command, **kwargs: SimpleNamespace(returncode=0, stdout=".env\nREADME.md\n"))
    monkeypatch.setattr(secret_scan, "is_tracked_env_secret", lambda path: path == ".env")
    assert aq_cli.cmd_secrets_check(_ns()) == 1
    err = capsys.readouterr().err
    assert "populated secret field" in err and "tracked secret file must not be committed: .env" in err
    monkeypatch.setattr(secret_scan, "find_populated_secret_fields", lambda config: [])
    monkeypatch.setattr(aq_cli.subprocess, "run", lambda command, **kwargs: (_ for _ in ()).throw(FileNotFoundError("git")))
    assert aq_cli.cmd_secrets_check(_ns()) == 0 and "passed" in capsys.readouterr().out
    (tmp_path / "lean.json").unlink()
    assert aq_cli.cmd_secrets_check(_ns()) == 0


def test_ml_cleanup_lists_deletes_and_prints_json(tmp_path, monkeypatch, capsys):
    import evaluation.ml_cleanup as cleanup

    file = tmp_path / "old.pt"
    file.write_text("x", encoding="utf-8")
    folder = tmp_path / "versions" / "v1"
    folder.mkdir(parents=True)
    plan = {"total_bytes": 2_000_000, "protected": ["a"], "active_version_ids": ["v9"], "items": [
        {"bytes": 1_000_000, "kind": "file", "path": str(file), "reason": "old"}, {"bytes": 1_000_000, "kind": "dir", "path": str(folder), "reason": "old"}, {"bytes": 1, "kind": "gone", "path": str(tmp_path / "nothing"), "reason": "x"}]}
    monkeypatch.setattr(cleanup, "plan_ml_cleanup", lambda ml_dir, **kwargs: plan)
    base = dict(keep_versions=2, keep_backups=1, strip_walk_forward_datasets=False, json=False, apply=False)
    assert aq_cli.cmd_clean(_ns(**base)) == 0 and "dry run" in capsys.readouterr().out and file.exists()
    assert aq_cli.cmd_clean(_ns(**{**base, "json": True})) == 0 and '"total_bytes"' in capsys.readouterr().out
    assert aq_cli.cmd_clean(_ns(**{**base, "apply": True})) == 0 and not file.exists() and not folder.exists() and "deleted 3 items" in capsys.readouterr().out
    assert shutil is not None and Path is not None and ROOT is not None


def test_a_windows_backtest_runs_lean_through_the_project_wrapper_and_another_system_runs_it_directly(monkeypatch):
    from unittest.mock import MagicMock, patch

    import aq_cli

    for platform in ("win32", "linux"):
        run_mock = MagicMock(return_value=0)
        monkeypatch.setattr(aq_cli.sys, "platform", platform)
        with patch("aq_cli._find_quantconnect_lean_binary", return_value="lean"), patch("aq_cli._ensure_local_lean_engine_image", return_value=True), patch(
            "generate_backtest_report.update_readme_from_latest_backtest", return_value=False
        ), patch("aq_cli._run", run_mock), patch("aq_cli._refresh_readme_evaluation_sections"), patch("aq_cli._resolve_lean_run_dir", return_value=None):
            parser = aq_cli.build_parser()
            args = parser.parse_args(["backtest"])
            args.func(args)
        command = run_mock.call_args.args[0]
        assert (command[1].endswith("run_lean_cli_windows.py")) is (platform == "win32") and command[0 if platform == "linux" else 2] in ("lean", "backtest")
