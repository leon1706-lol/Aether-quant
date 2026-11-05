"""scripts/vault_record.py: records a phase gate in the local vault; subprocess mocked, the real `av` is in test_vault_contract."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "vault_record", Path(__file__).resolve().parent.parent / "scripts" / "vault_record.py"
)
vault_record = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vault_record)


def _completed(returncode=0, stdout="", stderr=""):
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


def test_parse_metrics():
    assert vault_record.parse_metrics(["a=1", "b=-0.5"]) == {"a": 1.0, "b": -0.5}
    with pytest.raises(ValueError):
        vault_record.parse_metrics(["nonsense"])


def test_record_never_uploads_and_returns_the_full_hash(tmp_path):
    (tmp_path / ".av").mkdir()
    responses = [_completed(stdout="av 1.4.1"), _completed(), _completed(stdout='{"ok": true, "data": {"hash": "abc"}, "error": null}')]
    with patch("retraining.vault_client.subprocess.run", side_effect=responses) as run_mock:
        result = vault_record.record("rules", ["rules.json"], {"trials": 0.0}, cwd=tmp_path, av_binary="av")

    assert result == {"ok": True, "stage": "done", "commit": "abc", "detail": None}
    commit_argv = run_mock.call_args_list[2].args[0]
    assert "--no-upload" in commit_argv
    assert commit_argv[commit_argv.index("--tag") + 1] == "gate:rules"


def test_record_treats_unchanged_files_as_already_recorded(tmp_path):
    (tmp_path / ".av").mkdir()
    refused = '{"ok": false, "data": null, "error": {"code": "nothing_to_commit", "message": "Nothing to commit"}}'
    responses = [_completed(stdout="av 1.4.1"), _completed(), _completed(returncode=11, stdout=refused)]
    with patch("retraining.vault_client.subprocess.run", side_effect=responses):
        result = vault_record.record("rules", ["rules.json"], {}, cwd=tmp_path, av_binary="av")

    assert result["ok"] is True
    assert result["stage"] == "unchanged"


def test_record_reports_a_missing_binary_without_raising(tmp_path):
    with patch("retraining.vault_client.subprocess.run", side_effect=FileNotFoundError()):
        result = vault_record.record("rules", ["rules.json"], {}, cwd=tmp_path, av_binary="av")

    assert result["ok"] is False
    assert result["stage"] == "preflight"
