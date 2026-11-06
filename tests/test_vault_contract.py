"""The contract between Aether-quant and the real `av`: the other vault tests mock subprocess, so a change in av's output,
exit codes or ignore rules would pass them. `aether-vault` is pinned in requirements/requirements.txt, so CI runs these too; skipped
only where `av` is not installed."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from retraining.artifacts import REQUIRED_CANDIDATE_FILES
from retraining.vault_client import (
    commit_candidate_to_vault,
    restore_candidate_from_vault,
    run_av_command,
    vault_preflight,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _av_binary() -> str | None:
    configured = os.environ.get("AQ_AV_BINARY")
    if configured:
        return configured
    found = shutil.which("av")
    if found:
        return found
    appdata = os.environ.get("APPDATA")
    if appdata:
        for candidate in Path(appdata).glob("Python/Python*/Scripts/av.exe"):
            return str(candidate)
    return None


AV = _av_binary()
pytestmark = pytest.mark.skipif(AV is None, reason="real av not available")


def _supports_restore() -> bool:
    return run_av_command([AV, "restore", "--help"])["ok"]


@pytest.fixture
def repo(tmp_path):
    shutil.copy(REPO_ROOT / ".gitignore", tmp_path / ".gitignore")
    assert run_av_command([AV, "init"], cwd=tmp_path)["ok"]
    (tmp_path / "train.py").write_text("print('v1')\n")
    candidate = tmp_path / "ml" / "versions" / "v1"
    candidate.mkdir(parents=True)
    for name in REQUIRED_CANDIDATE_FILES:
        (candidate / name).write_text(f"content of {name}\n")
    return tmp_path


def _config(**overrides) -> dict:
    return {"av_binary": AV, "tag": "candidate", "push": False, "timeout_seconds": 120, **overrides}


def _tree(repo: Path, full_hash: str) -> dict:
    import json

    return json.loads((repo / ".av" / "commits" / f"{full_hash}.json").read_text(encoding="utf-8"))["tree"]


def test_preflight_passes_on_a_real_repo(repo):
    result = vault_preflight(_config(), cwd=repo)
    assert result["ok"], result
    assert result["av_version"]


def test_candidate_commit_contains_every_required_file_under_our_real_gitignore(repo):
    result = commit_candidate_to_vault("v1", ["train.py", "ml/versions/v1"], {"sharpe": 1.0}, _config(), cwd=repo)

    assert result["ok"], result
    assert len(result["vault_commit"]) == 64
    tree = _tree(repo, result["vault_commit"])
    missing = [name for name in REQUIRED_CANDIDATE_FILES if f"ml/versions/v1/{name}" not in tree]
    assert missing == []


def test_commit_hash_fits_the_registry_column(repo):
    result = commit_candidate_to_vault("v1", ["train.py"], {}, _config(), cwd=repo)
    assert len(result["vault_commit"]) <= 64  # aether_vault_commit VARCHAR(64), retraining/postgres_registry.py


def test_unreachable_push_is_reported_as_queued_not_as_success_or_failure(repo):
    set_remote = run_av_command([AV, "config", "--remote-url", "http://127.0.0.1:9"], cwd=repo)
    assert set_remote["ok"], set_remote

    result = commit_candidate_to_vault("v1", ["train.py"], {}, _config(push=True), cwd=repo)

    assert result["ok"], result
    assert result["push_state"] == "queued"

    strict = commit_candidate_to_vault("v1", ["ml/versions/v1"], {}, _config(push=True, require_push=True), cwd=repo)
    assert strict["ok"] is False
    assert strict["stage"] == "push"


def test_status_does_not_report_a_committed_candidate_as_deleted(repo):
    assert commit_candidate_to_vault("v1", ["ml/versions/v1"], {}, _config(), cwd=repo)["ok"]

    status = subprocess.run([AV, "--output", "json", "status"], cwd=repo, capture_output=True, text=True, encoding="utf-8")

    assert '"deleted": []' in status.stdout, status.stdout


def test_failed_checkout_exits_non_zero(repo):
    assert run_av_command([AV, "checkout", "0" * 64], cwd=repo)["ok"] is False


def test_restore_recovers_the_candidate_and_leaves_everything_else(repo):
    if not _supports_restore():
        pytest.skip("this av has no restore command")
    result = commit_candidate_to_vault("v1", ["train.py", "ml/versions/v1"], {}, _config(), cwd=repo)
    assert result["ok"], result

    (repo / "ml" / "versions" / "v1" / "scaler.pkl").write_text("corrupted\n")
    (repo / "train.py").write_text("print('newer, must survive')\n")

    restored = restore_candidate_from_vault(result["vault_commit"], "ml/versions/v1", _config(), cwd=repo)

    assert restored["ok"], restored
    assert (repo / "ml" / "versions" / "v1" / "scaler.pkl").read_text() == "content of scaler.pkl\n"
    assert (repo / "train.py").read_text() == "print('newer, must survive')\n"


def test_restore_of_an_unknown_commit_fails(repo):
    if not _supports_restore():
        pytest.skip("this av has no restore command")
    assert restore_candidate_from_vault("0" * 64, "ml/versions/v1", _config(), cwd=repo)["ok"] is False


def test_no_upload_commits_stay_queued_and_touch_no_network(repo):
    (repo / "x.txt").write_text("x")
    assert run_av_command([AV, "config", "--remote-url", "http://127.0.0.1:1"], cwd=repo)["ok"]
    assert run_av_command([AV, "add", "x.txt"], cwd=repo)["ok"]
    committed = run_av_command([AV, "--output", "json", "commit", "-m", "x", "--no-upload"], cwd=repo, timeout=60)
    assert committed["ok"], committed
    assert '"queued_reason": "upload_deferred"' in committed["stdout"]


def test_a_queue_entry_exists_for_every_commit_before_any_push(repo):
    import json

    assert run_av_command([AV, "config", "--remote-url", "http://127.0.0.1:1"], cwd=repo)["ok"]
    (repo / "a.txt").write_text("a")
    assert run_av_command([AV, "add", "a.txt"], cwd=repo)["ok"]
    assert run_av_command([AV, "commit", "-m", "a", "--no-upload"], cwd=repo, timeout=60)["ok"]
    head = (repo / ".av" / "refs" / "heads" / "main").read_text().strip()
    queued = [entry["commit_hash"] for entry in json.loads((repo / ".av" / "pending_push").read_text())]
    assert head in queued


def test_rm_drops_a_path_from_the_next_commit(repo):
    result = commit_candidate_to_vault("v1", ["train.py", "ml/versions/v1"], {}, _config(), cwd=repo)
    assert result["ok"], result
    assert run_av_command([AV, "rm", "train.py"], cwd=repo)["ok"]
    assert not (repo / "train.py").exists()
    committed = run_av_command([AV, "--output", "json", "commit", "-m", "drop", "--no-upload"], cwd=repo, timeout=60)
    assert committed["ok"], committed
    head = (repo / ".av" / "refs" / "heads" / "main").read_text().strip()
    assert "train.py" not in _tree(repo, head)
    assert any(path.startswith("ml/versions/v1/") for path in _tree(repo, head))


def test_a_corrupt_index_stops_the_commit_and_is_kept(repo):
    (repo / ".av" / "index").write_text('{"entries": {')
    (repo / "y.txt").write_text("y")
    added = run_av_command([AV, "--output", "json", "add", "y.txt"], cwd=repo)
    assert not added["ok"] and added["returncode"] == 15
    assert (repo / ".av" / "index").read_text() == '{"entries": {'
