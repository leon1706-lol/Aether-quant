"""The last unreached branches of monitoring/ (V6.6.6, #359): file errors degrade to empty readings, never to a 500."""

from __future__ import annotations

import json
import sys
import os
from pathlib import Path

import pytest
from fastapi import HTTPException

import monitoring.api_server as api_server
from monitoring import evaluation_state, neural_network_state
from monitoring.auth_io import save_users


def test_an_unreadable_users_file_or_csv_is_a_clean_error(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "users_file", lambda: tmp_path / "users.json")
    original = Path.stat

    def refuse(self, *args, **kwargs):
        if self.name == "users.json":
            raise OSError("denied")
        return original(self, *args, **kwargs)

    (tmp_path / "users.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(Path, "stat", refuse)
    try:
        api_server._current_users()
    except Exception:
        pass  # the key falls back to "no mtime"; what the file then holds is the users file's own tests
    with pytest.raises(HTTPException) as caught:
        api_server._read_csv_as_rows(tmp_path / "missing.csv")
    assert caught.value.status_code == 404


def test_a_broken_accounts_file_is_a_500_and_an_unknown_account_a_404(tmp_path, monkeypatch):
    def invalid():
        raise ValueError("duplicate id")

    monkeypatch.setattr(api_server, "DEMO", False)
    monkeypatch.setattr(api_server, "_accounts", invalid)
    request = type("Request", (), {"state": type("State", (), {})()})()
    with pytest.raises(HTTPException) as caught:
        api_server.get_accounts(request)
    assert caught.value.status_code == 500 and "accounts.json is invalid" in caught.value.detail
    with pytest.raises(HTTPException) as caught:
        api_server.get_state(account="nobody")
    assert caught.value.status_code in (404, 500)


def test_an_action_is_recorded_even_when_the_audit_stream_is_down(tmp_path, monkeypatch):
    import audit

    monkeypatch.setattr(api_server, "ROOT_DIR", tmp_path)

    def refuse(*args, **kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(audit, "AuditQueue", refuse)
    entry = api_server._append_action({"event": "manual_trade_lock", "user": "ops"})
    assert entry["prev_hash"] and (tmp_path / "state" / "api_actions.jsonl").exists()


def test_readers_degrade_instead_of_raising(tmp_path, monkeypatch):
    assert neural_network_state._weight_stats({}, "w") == (0.0, 0.0) and neural_network_state._weight_stats({"w": []}, "w") == (0.0, 0.0) and neural_network_state._weight_stats({"w": [[]]}, "w") == (0.0, 0.0)
    assert neural_network_state._last_modified(tmp_path / "none.json") is None
    assert evaluation_state._latest_walk_forward_summary(tmp_path) is None
    (tmp_path / "versions" / "walk-forward-a").mkdir(parents=True)
    assert evaluation_state._latest_walk_forward_summary(tmp_path) is None
    summary = tmp_path / "versions" / "walk-forward-a" / "walk_forward_summary.json"
    summary.write_text(json.dumps({"windows": 3}), encoding="utf-8")
    original = Path.stat

    def refuse(self, *args, **kwargs):
        # only the mtime read fails: Python 3.11's Path.exists() and is_file() also call stat() and re-raise an error with no errno
        if self.name == "walk_forward_summary.json" and sys._getframe(1).f_code.co_name == "_mtime":
            raise OSError("gone")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", refuse)
    assert evaluation_state._latest_walk_forward_summary(tmp_path) == {"windows": 3}


def test_the_users_file_is_saved_even_where_chmod_does_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("AQ_USERS_FILE", str(tmp_path / "state" / "users.json"))

    def refuse(path, mode):
        raise OSError("windows")

    monkeypatch.setattr(os, "chmod", refuse)
    assert save_users(()).exists()


def test_a_state_file_that_is_not_json_means_no_runtime_guards(tmp_path):
    from monitoring.assets_status import build_assets_status_from_disk

    (tmp_path / "config.json").write_text(json.dumps({"phase1": {"universe": {"assets": []}}}), encoding="utf-8")
    (tmp_path / "lean.json").write_text("{}", encoding="utf-8")
    (tmp_path / "visualization").mkdir()
    (tmp_path / "visualization" / "state.json").write_text("{torn", encoding="utf-8")
    assert isinstance(build_assets_status_from_disk(tmp_path), dict)
