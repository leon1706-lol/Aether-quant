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


def _clean_status():
    return _completed(stdout='{"ok": true, "data": {"staged": [], "removed": []}, "error": null, "meta": {}}')


def test_parse_metrics():
    assert vault_record.parse_metrics(["a=1", "b=-0.5"]) == {"a": 1.0, "b": -0.5}
    with pytest.raises(ValueError):
        vault_record.parse_metrics(["nonsense"])


def test_record_never_uploads_and_returns_the_full_hash(tmp_path):
    (tmp_path / ".av").mkdir()
    responses = [_completed(stdout="av 1.4.1"), _clean_status(), _completed(), _completed(stdout='{"ok": true, "data": {"hash": "abc"}, "error": null}')]
    with patch("retraining.vault_client.subprocess.run", side_effect=responses) as run_mock:
        result = vault_record.record("rules", ["rules.json"], {"trials": 0.0}, cwd=tmp_path, av_binary="av")

    assert result == {"ok": True, "stage": "done", "commit": "abc", "detail": None}
    commit_argv = run_mock.call_args_list[3].args[0]
    assert "--no-upload" in commit_argv
    assert commit_argv[commit_argv.index("--tag") + 1] == "gate:rules"


def test_record_treats_unchanged_files_as_already_recorded(tmp_path):
    (tmp_path / ".av").mkdir()
    refused = '{"ok": false, "data": null, "error": {"code": "nothing_to_commit", "message": "Nothing to commit"}}'
    responses = [_completed(stdout="av 1.4.1"), _clean_status(), _completed(), _completed(returncode=11, stdout=refused)]
    with patch("retraining.vault_client.subprocess.run", side_effect=responses):
        result = vault_record.record("rules", ["rules.json"], {}, cwd=tmp_path, av_binary="av")

    assert result["ok"] is True
    assert result["stage"] == "unchanged"


def test_record_reports_a_missing_binary_without_raising(tmp_path):
    with patch("retraining.vault_client.subprocess.run", side_effect=FileNotFoundError()):
        result = vault_record.record("rules", ["rules.json"], {}, cwd=tmp_path, av_binary="av")

    assert result["ok"] is False
    assert result["stage"] == "preflight"


def test_record_refuses_when_something_is_already_staged(tmp_path):
    (tmp_path / ".av").mkdir()
    dirty = _completed(stdout='{"ok": true, "data": {"staged": ["left_over.csv"], "removed": []}, "error": null, "meta": {}}')
    with patch("retraining.vault_client.subprocess.run", side_effect=[_completed(stdout="av 1.4.1"), dirty]) as run_mock:
        result = vault_record.record("rules", ["rules.json"], {}, cwd=tmp_path, av_binary="av")
    assert result["ok"] is False and result["stage"] == "staged_leftovers" and "left_over.csv" in result["detail"]
    assert run_mock.call_count == 2, "nothing is added under this gate's label"


def test_a_failed_add_or_commit_names_its_stage(tmp_path):
    (tmp_path / ".av").mkdir()
    with patch("retraining.vault_client.subprocess.run", side_effect=[_completed(stdout="av 1.4.1"), _clean_status(), _completed(returncode=2, stderr="no such file")]):
        assert vault_record.record("rules", ["x"], {}, cwd=tmp_path, av_binary="av")["stage"] == "add"
    broken = '{"ok": false, "data": null, "error": {"code": "disk_full", "message": "full"}}'
    with patch("retraining.vault_client.subprocess.run", side_effect=[_completed(stdout="av 1.4.1"), _clean_status(), _completed(), _completed(returncode=5, stdout=broken)]):
        assert vault_record.record("rules", ["x"], {}, cwd=tmp_path, av_binary="av")["stage"] == "commit"


def test_the_av_binary_is_found_by_setting_path_appdata_or_name(tmp_path, monkeypatch):
    monkeypatch.setenv("AQ_AV_BINARY", "C:/tools/av.exe")
    assert vault_record.find_av_binary() == "C:/tools/av.exe"
    monkeypatch.delenv("AQ_AV_BINARY")
    monkeypatch.setattr(vault_record.shutil, "which", lambda name: "/usr/bin/av")
    assert vault_record.find_av_binary() == "/usr/bin/av"
    monkeypatch.setattr(vault_record.shutil, "which", lambda name: None)
    scripts = tmp_path / "Python" / "Python311" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "av.exe").write_text("", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert vault_record.find_av_binary() == str(scripts / "av.exe")
    monkeypatch.setenv("APPDATA", str(tmp_path / "empty"))
    assert vault_record.find_av_binary() == "av"
    monkeypatch.delenv("APPDATA")
    assert vault_record.find_av_binary() == "av"


def test_main_prints_the_result_and_exits_on_its_outcome(monkeypatch, capsys):
    results = iter([{"ok": True, "stage": "done"}, {"ok": False, "stage": "add"}])
    monkeypatch.setattr(vault_record, "record", lambda label, paths, metrics: next(results))
    assert vault_record.main(["--label", "g", "--metric", "a=1", "f.json"]) == 0
    assert vault_record.main(["--label", "g", "f.json"]) == 1 and '"stage": "add"' in capsys.readouterr().out
