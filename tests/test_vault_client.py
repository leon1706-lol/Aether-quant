"""Tests for retraining.vault_client — V2-17.

Conventions: no test classes, module-level helpers, subprocess.run mocked
via unittest.mock.patch (mirrors retraining.lean_backtest's test style).
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from retraining.vault_client import (
    commit_candidate_to_vault,
    parse_av_envelope,
    parse_push_state,
    parse_vault_commit_hash,
    restore_candidate_from_vault,
    run_av_command,
    vault_preflight,
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


FULL_HASH = "f7bc8d766817ba50a8fcc689629558bd6985f370d2f3f6cffb629b6cb04af23a"
COMMIT_OUT = (
    '{"ok": true, "data": {"committed": true, "hash": "' + FULL_HASH + '", "short": "f7bc8d7", "queued": true}, '
    '"error": null, "meta": {"command": "commit"}}'
)
PUSH_QUEUED = '{"ok": true, "data": {"drained": 0, "still_queued": 1, "reachable": false}, "error": null}'
PUSH_DRAINED = '{"ok": true, "data": {"drained": 1, "still_queued": 0, "reachable": true}, "error": null}'


_NOTHING_STAGED = _completed(stdout='{"ok": true, "data": {"staged": [], "removed": []}, "error": null, "meta": {}}')


def test_run_av_command_decodes_utf8_whatever_the_system_codepage():
    with patch("retraining.vault_client.subprocess.run", return_value=_completed()) as run_mock:
        run_av_command(["av", "status"])

    assert run_mock.call_args.kwargs["encoding"] == "utf-8"
    assert run_mock.call_args.kwargs["errors"] == "replace"


def test_parse_vault_commit_hash_reads_the_full_hash_from_the_envelope():
    assert parse_vault_commit_hash("Uploading...\n" + COMMIT_OUT) == FULL_HASH


def test_parse_vault_commit_hash_reads_real_human_output():
    assert parse_vault_commit_hash("[f7bc8d7] candidate v1") == "f7bc8d7"


def test_parse_vault_commit_hash_accepts_none_stdout():
    assert parse_vault_commit_hash(None) is None


def test_parse_av_envelope_ignores_non_envelope_lines():
    assert parse_av_envelope('{"not": "an envelope"}') is None
    assert parse_av_envelope("plain text") is None


def test_parse_push_state():
    assert parse_push_state(PUSH_QUEUED) == "queued"
    assert parse_push_state(PUSH_DRAINED) == "drained"
    assert parse_push_state("no envelope") == "unknown"


def test_commit_records_a_queued_push_as_a_safe_outcome_by_default():
    responses = [_NOTHING_STAGED, _completed(), _completed(stdout=COMMIT_OUT), _completed(stdout=PUSH_QUEUED)]
    with patch("retraining.vault_client.subprocess.run", side_effect=responses):
        result = commit_candidate_to_vault("v1", ["train.py"], {}, _CONFIG)

    assert result["ok"] is True
    assert result["push_state"] == "queued"
    assert result["vault_commit"] == FULL_HASH


def test_commit_fails_on_a_queued_push_when_push_is_required():
    responses = [_NOTHING_STAGED, _completed(), _completed(stdout=COMMIT_OUT), _completed(stdout=PUSH_QUEUED)]
    with patch("retraining.vault_client.subprocess.run", side_effect=responses):
        result = commit_candidate_to_vault("v1", ["train.py"], {}, {**_CONFIG, "require_push": True})

    assert result["ok"] is False
    assert result["stage"] == "push"
    assert result["vault_commit"] == FULL_HASH


def test_commit_fails_when_push_itself_crashes():
    responses = [_NOTHING_STAGED, _completed(), _completed(stdout=COMMIT_OUT), _completed(returncode=1, stderr="boom")]
    with patch("retraining.vault_client.subprocess.run", side_effect=responses):
        result = commit_candidate_to_vault("v1", ["train.py"], {}, _CONFIG)

    assert result["ok"] is False
    assert result["push_state"] == "failed"


def test_preflight_reports_a_missing_binary():
    with patch("retraining.vault_client.subprocess.run", side_effect=FileNotFoundError()):
        result = vault_preflight(_CONFIG)

    assert result == {"ok": False, "reason": "av_binary_not_found", "av_version": None}


def test_preflight_requires_an_initialised_repo(tmp_path):
    with patch("retraining.vault_client.subprocess.run", return_value=_completed(stdout="av 1.4.1")):
        result = vault_preflight(_CONFIG, cwd=tmp_path)

    assert result["ok"] is False
    assert result["reason"].startswith("not_an_av_repo")


def test_preflight_passes_on_an_initialised_repo(tmp_path):
    (tmp_path / ".av").mkdir()
    with patch("retraining.vault_client.subprocess.run", return_value=_completed(stdout="av 1.4.1.dev8+g1")):
        result = vault_preflight(_CONFIG, cwd=tmp_path)

    assert result == {"ok": True, "reason": "ready", "av_version": "av 1.4.1.dev8+g1"}


def test_preflight_enforces_min_version(tmp_path):
    (tmp_path / ".av").mkdir()
    with patch("retraining.vault_client.subprocess.run", return_value=_completed(stdout="av 1.4.1")):
        low = vault_preflight({**_CONFIG, "min_version": "1.5.0"}, cwd=tmp_path)
        high = vault_preflight({**_CONFIG, "min_version": "1.4.0"}, cwd=tmp_path)

    assert low["ok"] is False and "below_minimum" in low["reason"]
    assert high["ok"] is True


def test_preflight_does_nothing_when_the_vault_is_disabled():
    with patch("retraining.vault_client.subprocess.run") as run_mock:
        result = vault_preflight({**_CONFIG, "enabled": False})

    run_mock.assert_not_called()
    assert result["ok"] is True


def test_restore_candidate_never_uses_a_repo_wide_checkout():
    with patch("retraining.vault_client.subprocess.run", return_value=_completed()) as run_mock:
        restore_candidate_from_vault("abc", "ml/versions/v1", _CONFIG)

    argv = run_mock.call_args.args[0]
    assert "checkout" not in argv
    assert argv[-4:] == ["restore", "--source", "abc", "ml/versions/v1"]


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
    responses = [_NOTHING_STAGED, _completed(returncode=0), _completed(returncode=1, stderr="boom")]
    with patch("retraining.vault_client.subprocess.run", side_effect=responses):
        result = commit_candidate_to_vault("v1", ["train.py"], {}, _CONFIG)

    assert result["ok"] is False
    assert result["stage"] == "commit"
    assert "push" not in result["steps"]


def test_commit_candidate_to_vault_succeeds_through_push():
    responses = [
        _NOTHING_STAGED,
        _completed(returncode=0),  # add
        _completed(returncode=0, stdout=COMMIT_OUT),  # commit
        _completed(returncode=0, stdout=PUSH_DRAINED),  # push
    ]
    with patch("retraining.vault_client.subprocess.run", side_effect=responses):
        result = commit_candidate_to_vault("v1", ["train.py"], {"sharpe": 1.0}, _CONFIG)

    assert result["ok"] is True
    assert result["stage"] == "done"
    assert result["vault_commit"] == FULL_HASH
    assert result["push_state"] == "drained"


def test_commit_candidate_to_vault_skips_push_when_configured_off():
    responses = [_NOTHING_STAGED, _completed(returncode=0), _completed(returncode=0, stdout=COMMIT_OUT)]
    config = {**_CONFIG, "push": False}
    with patch("retraining.vault_client.subprocess.run", side_effect=responses):
        result = commit_candidate_to_vault("v1", ["train.py"], {}, config)

    assert result["ok"] is True
    assert result["stage"] == "done"
    assert "push" not in result["steps"]


def test_commit_refuses_a_failed_gates_leftovers():
    dirty = _completed(stdout='{"ok": true, "data": {"staged": ["old.csv"], "removed": []}, "error": null, "meta": {}}')
    with patch("retraining.vault_client.subprocess.run", side_effect=[dirty]) as run_mock:
        result = commit_candidate_to_vault("v1", ["train.py"], {}, _CONFIG)
    assert result["ok"] is False and result["stage"] == "staged_leftovers"
    assert run_mock.call_count == 1


def test_an_unchanged_candidate_is_success_with_the_existing_hash():
    refused = _completed(returncode=11, stdout='{"ok": false, "data": {}, "error": {"code": "nothing_to_commit", "message": "Nothing"}, "meta": {}}')
    head = _completed(stdout='{"ok": true, "data": {"commits": [{"hash": "abc123"}]}, "error": null, "meta": {}}')
    with patch("retraining.vault_client.subprocess.run", side_effect=[_NOTHING_STAGED, _completed(), refused, head, _completed(stdout=PUSH_DRAINED)]):
        result = commit_candidate_to_vault("v1", ["train.py"], {}, _CONFIG)
    assert result["ok"] is True and result["vault_commit"] == "abc123"


def test_a_real_commit_failure_is_still_a_failure():
    refused = _completed(returncode=15, stdout='{"ok": false, "data": {}, "error": {"code": "validation", "message": "no"}, "meta": {}}')
    with patch("retraining.vault_client.subprocess.run", side_effect=[_NOTHING_STAGED, _completed(), refused]):
        result = commit_candidate_to_vault("v1", ["train.py"], {}, _CONFIG)
    assert result["ok"] is False and result["stage"] == "commit"


def test_the_docker_worker_has_a_vault_repo_that_outlives_its_container():
    """`.av` is dockerignored, so without a volume and an init `vault_preflight` fails every cycle in the container."""
    import yaml

    compose = yaml.safe_load((Path(__file__).resolve().parent.parent / "docker-compose.yml").read_text(encoding="utf-8"))
    worker = compose["services"]["retraining-worker"]
    assert "retraining-vault:/app/.av" in worker["volumes"] and "retraining-vault" in compose["volumes"]
    assert "av init" in worker["command"] and "exec python -m retraining.worker" in worker["command"]
