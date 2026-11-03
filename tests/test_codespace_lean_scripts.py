"""Static checks of the Lean-on-a-DinD-Codespace scripts (V6.3.0): scripts/codespace_lean_dind.sh runs on the
Codespace, scripts/codespace_lean_run.ps1 drives it from the PC. Neither can run in the suite (no Codespace), so these
pin the steps a past run needed: Docker's data root on /tmp, the pinned Lean CLI and image, LF endings handled, and a
delete step so the Codespace never outlives its runs (AGENTS.md rule 13)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIND = ROOT / "scripts" / "codespace_lean_dind.sh"
RUNNER = ROOT / "scripts" / "codespace_lean_run.ps1"


def test_dind_script_moves_docker_data_root_before_building_the_image():
    text = DIND.read_text(encoding="utf-8")
    assert text.index('DATA_ROOT="/tmp/docker-data"') < text.index("docker build -f Dockerfile.lean")
    assert "/etc/docker/daemon.json" in text


def test_dind_script_pins_lean_cli_and_image():
    text = DIND.read_text(encoding="utf-8")
    assert 'LEAN_CLI_VERSION="1.0.227"' in text
    assert 'IMAGE="aether-quant-lean:17900"' in text
    assert 'lean backtest . --image "${IMAGE}"' in text


def test_dind_script_reports_every_run_and_restores_config():
    text = DIND.read_text(encoding="utf-8")
    for marker in ("LEAN_RUNNING", "LEAN_DONE", "LEAN_FAILED", "ALL_DONE"):
        assert marker in text
    assert 'cp "${STATE_DIR}/config.json.orig" config.json' in text


def test_runner_strips_crlf_before_running_the_shell_script():
    text = RUNNER.read_text(encoding="utf-8")
    assert "sed -i ''s/\\r$//'' scripts/codespace_lean_dind.sh" in text


def test_runner_creates_with_idle_timeout_and_can_delete():
    text = RUNNER.read_text(encoding="utf-8")
    assert "--idle-timeout 30m" in text
    assert "gh codespace delete -c $Codespace -f" in text
    assert ".devcontainer/dind-v1-test/devcontainer.json" in text
    assert (ROOT / ".devcontainer" / "dind-v1-test" / "devcontainer.json").is_file()


def test_runner_checks_trees_after_push_and_engine_log_after_pull():
    text = RUNNER.read_text(encoding="utf-8")
    assert "-Mode status" in text
    assert "log.txt" in text


def test_pull_freezes_each_runs_config_under_its_folder_name():
    """V6.4.2: the DinD route ran `lean backtest` directly, so no `run_configs/<folder>.json` existed for lean_verdict and
    the run-folder tools; -Pull now copies the named config the status line reports and checks the hash."""
    text = RUNNER.read_text(encoding="utf-8")
    assert "ml/evaluation/run_configs/$($parts[1]).json" in text
    assert "ml/evaluation/run_configs/$(Split-Path $parts[2] -Leaf).json" in text
    assert "config freeze mismatch" in text


def test_dind_script_overlays_and_restores_per_run_model_artifacts():
    """V6.4.4: main.py reads models from fixed ml/ paths, so a run of a retrained candidate ships its files in
    ml/evaluation/run_artifacts/<run>/; the runner copies them over ml/ for that run only, restores and verifies the
    originals afterwards, and records what the run read."""
    text = DIND.read_text(encoding="utf-8")
    assert 'overlay="ml/evaluation/run_artifacts/$1"' in text
    assert text.index('apply_artifacts "${name}"') < text.index("lean backtest . --image")
    assert text.index("lean backtest . --image") < text.index('restore_artifacts "${name}"')
    assert 'cmp -s "${backup}/${rel}" "ml/${rel}" || return 1' in text
    assert "run_artifacts_manifest.json" in text
    assert "restore of ml/ after the run did not verify" in text


def test_pull_requires_the_artifacts_manifest_when_the_run_used_an_overlay():
    text = RUNNER.read_text(encoding="utf-8")
    assert "ml/evaluation/run_artifacts/$($parts[1])" in text
    assert "has no run_artifacts_manifest.json" in text


def test_create_survives_gh_notices_on_stderr():
    """V6.4.4: gh writes "Codespaces usage ... is paid for by ..." to stderr; with ErrorActionPreference 'Stop' Windows
    PowerShell 5.1 made that a terminating error and no Codespace was created."""
    text = RUNNER.read_text(encoding="utf-8")
    create = text[text.index("if ($Create) {"):text.index("if (-not $Codespace)")]
    assert "$ErrorActionPreference = 'Continue'" in create and "2>$null" in create
    assert create.index("$createExit = $LASTEXITCODE") < create.index("$ErrorActionPreference = $previousPreference")


def test_dind_script_creates_the_docker_config_folder_before_writing_daemon_json():
    """V6.4.4: the docker-in-docker feature (Docker 29) no longer creates /etc/docker; `tee` failed and dockerd never moved."""
    text = DIND.read_text(encoding="utf-8")
    assert text.index("sudo mkdir -p /etc/docker") < text.index("sudo tee /etc/docker/daemon.json")
