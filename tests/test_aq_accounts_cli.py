"""`aq accounts`, `aq live` and `aq secrets` (V6.6.5, #348, #349)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import aq_cli
from execution.accounts import DEFAULT_ACCOUNT, Account

ROOT = Path(__file__).resolve().parents[1]


def _run(argv):
    try:
        aq_cli.main(argv)
    except SystemExit as exit_:
        return exit_.code
    return None


@pytest.fixture
def registry(monkeypatch, tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text((ROOT / "accounts.example.json").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("AQ_ACCOUNTS_FILE", str(path))
    monkeypatch.setenv("AQ_SKIP_UPDATE_CHECK", "1")
    return path


def test_validate_list_and_status(registry, capsys, tmp_path):
    assert _run(["accounts", "validate"]) == 0 and "3 account(s)" in capsys.readouterr().out
    assert _run(["accounts", "list"]) == 0 and "paper-b" in capsys.readouterr().out
    out = tmp_path / "status.json"
    assert _run(["accounts", "status", "--json", str(out)]) == 0
    assert [row["id"] for row in json.loads(out.read_text(encoding="utf-8"))["accounts"]] == ["default", "paper-a", "paper-b"]


def test_an_invalid_registry_fails(registry, capsys):
    registry.write_text(json.dumps({"accounts": [{"id": "x", "risk_overrides": {"live.max_allowed_total_drawdown_pct": 0.9}}]}), encoding="utf-8")
    assert _run(["accounts", "validate"]) == 1 and "looser" in capsys.readouterr().err


def test_live_dry_run_and_refusals(registry, capsys):
    assert _run(["live", "up", "--account", "paper-b", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "--name aether-quant-lean-live-paper-b" in out and "AQ_ACCOUNT=paper-b" in out
    assert _run(["live", "down", "--account", "paper-b", "--dry-run"]) == 0 and "docker rm -f aether-quant-lean-live-paper-b" in capsys.readouterr().out
    assert _run(["live", "up", "--account", "typo", "--dry-run"]) == 1 and "unknown account" in capsys.readouterr().err
    registry.write_text(json.dumps({"accounts": [{"id": "cb", "broker": "coinbase"}]}), encoding="utf-8")
    assert _run(["live", "up", "--account", "cb", "--dry-run"]) == 1 and "render-lean-config --account cb" in capsys.readouterr().err


def test_compose_commands_are_the_defaults_for_the_default_account():
    commands, env = aq_cli.live_compose_commands(DEFAULT_ACCOUNT, lean_config="lean.json")
    assert env == {"LEAN_LIVE_ENVIRONMENT": "live-paper", "LEAN_LIVE_CONFIG": "lean.json", "AQ_ACCOUNT": ""}
    assert "aether-quant-lean-live" in commands[0] and commands[1][:3] == ["docker", "update", "--restart"]
    _, named = aq_cli.live_compose_commands(Account("b", "coinbase", "live-coinbase"), lean_config="lean.live.b.json")
    assert named["LEAN_LIVE_ENVIRONMENT"] == "live-coinbase" and named["AQ_ACCOUNT"] == "b"


def test_secrets_status_never_prints_a_value(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("AQ_SKIP_UPDATE_CHECK", "1")
    monkeypatch.setenv("AETHER_TELEGRAM_BOT_TOKEN", "123456:very-secret-token")
    monkeypatch.setattr("execution.secrets_io.keyring_get", lambda service, user: None)
    out = tmp_path / "s.json"
    assert _run(["secrets", "status", "--json", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "very-secret-token" not in printed and "very-secret-token" not in out.read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN" in printed and "plain environment variable" in printed
    assert _run(["secrets", "set", "NOT_A_SECRET"]) == 2


def test_users_add_list_remove(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("AQ_SKIP_UPDATE_CHECK", "1")
    monkeypatch.setenv("AQ_USERS_FILE", str(tmp_path / "users.json"))
    assert _run(["users", "list"]) == 0 and "no users" in capsys.readouterr().out
    assert _run(["users", "add", "ada", "--role", "admin"]) == 0
    out = capsys.readouterr().out
    token = out.split("token (shown once, store it now): ")[1].split()[0]
    assert token not in (tmp_path / "users.json").read_text(encoding="utf-8")
    assert _run(["users", "add", "ada"]) == 1
    assert _run(["users", "add", "bob", "--role", "root"]) == 2
    assert _run(["users", "list"]) == 0 and "ada" in capsys.readouterr().out
    assert _run(["users", "remove", "ada"]) == 0 and _run(["users", "remove", "ada"]) == 1


def test_trade_lock_on_a_named_account_writes_its_own_file(registry, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(aq_cli, "ROOT_DIR", tmp_path)
    assert _run(["trade-lock", "--on", "--account", "paper-b"]) == 0
    target = tmp_path / "state" / "accounts" / "paper-b" / "overrides.json"
    assert json.loads(target.read_text(encoding="utf-8"))["phase_v2"]["risk"]["manual_trade_lock_override"] is True
    assert _run(["kill-switch", "--status", "--account", "paper-b"]) == 0


def test_paper_readiness_reports_the_live_gate(monkeypatch):
    from execution.paper_readiness_report import live_broker_view

    monkeypatch.delenv("AETHER_POSTGRES_DSN", raising=False)
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    present, reason = live_broker_view(config)
    assert present is False and reason
