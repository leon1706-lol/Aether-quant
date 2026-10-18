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
