"""Tests for retraining.vault_client — V2-17.

Conventions: no test classes, module-level helpers, subprocess.run mocked
via unittest.mock.patch (mirrors retraining.lean_backtest's test style).
"""

import subprocess
from unittest.mock import MagicMock, patch

from retraining.vault_client import (
    commit_candidate_to_vault,
    parse_vault_commit_hash,
    run_av_command,
)

_CONFIG = {
    "av_binary": "av",
    "commit_message_template": "candidate model {version_id}",
    "tag": "candidate",
    "push": True,
    "timeout_seconds": 30,
}


def _completed(returncode=0, stdout="", stderr=""):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def test_run_av_command_returns_ok_false_when_binary_not_found():
    with patch("retraining.vault_client.subprocess.run", side_effect=FileNotFoundError()):
        result = run_av_command(["av", "status"])

    assert result["ok"] is False
    assert result["error"] == "av_binary_not_found"


def test_run_av_command_returns_ok_false_on_timeout():
    with patch(
        "retraining.vault_client.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="av", timeout=1),
    ):
        result = run_av_command(["av", "commit"], timeout=1)

    assert result["ok"] is False
    assert result["error"] == "av_command_timed_out"


def test_run_av_command_returns_ok_true_on_success():
    with patch("retraining.vault_client.subprocess.run", return_value=_completed(returncode=0, stdout="ok")):
        result = run_av_command(["av", "status"])

    assert result["ok"] is True
    assert result["returncode"] == 0


def test_parse_vault_commit_hash_finds_hex_token():
    assert parse_vault_commit_hash("Committed as a1b2c3d4e5f6.") == "a1b2c3d4e5f6"


def test_parse_vault_commit_hash_returns_none_when_absent():
    assert parse_vault_commit_hash("no hash here") is None


def test_commit_candidate_to_vault_stops_at_add_failure():
    with patch("retraining.vault_client.subprocess.run", side_effect=FileNotFoundError()):
        result = commit_candidate_to_vault("v1", ["train.py"], {}, _CONFIG)

    assert result["ok"] is False
    assert result["stage"] == "add"
    assert "commit" not in result["steps"]


def test_commit_candidate_to_vault_stops_at_commit_failure():
    responses = [_completed(returncode=0), _completed(returncode=1, stderr="boom")]
    with patch("retraining.vault_client.subprocess.run", side_effect=responses):
        result = commit_candidate_to_vault("v1", ["train.py"], {}, _CONFIG)

    assert result["ok"] is False
    assert result["stage"] == "commit"
    assert "push" not in result["steps"]


def test_commit_candidate_to_vault_succeeds_through_push():
    responses = [
        _completed(returncode=0),  # add
        _completed(returncode=0, stdout="committed a1b2c3d4"),  # commit
        _completed(returncode=0),  # push
    ]
    with patch("retraining.vault_client.subprocess.run", side_effect=responses):
        result = commit_candidate_to_vault("v1", ["train.py"], {"sharpe": 1.0}, _CONFIG)

    assert result["ok"] is True
    assert result["stage"] == "done"
    assert result["vault_commit"] == "a1b2c3d4"


def test_commit_candidate_to_vault_skips_push_when_configured_off():
    responses = [_completed(returncode=0), _completed(returncode=0, stdout="committed a1b2c3d4")]
    config = {**_CONFIG, "push": False}
    with patch("retraining.vault_client.subprocess.run", side_effect=responses):
        result = commit_candidate_to_vault("v1", ["train.py"], {}, config)

    assert result["ok"] is True
    assert result["stage"] == "done"
    assert "push" not in result["steps"]
