"""V5.3.9 - meta-tests that PIN the CI/release workflow structure.

These guard against silent drift: a job renamed, the vitest run dropped,
the coverage gate removed, or a release publish losing (or accidentally
gaining) its test-visibility wiring would all fail here before the next
push discovers it the hard way. Mirrors the repo's established
meta-test pattern (test_dockerignore_secrets.py, test_secret_scan.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    import yaml

    HAVE_YAML = True
except ImportError:  # pragma: no cover
    HAVE_YAML = False

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"

pytestmark = pytest.mark.skipif(not HAVE_YAML, reason="PyYAML not installed")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_ci_triggers_on_main_push_and_prs():
    ci = _load(CI)
    on = ci["on"] if "on" in ci else ci[True]  # PyYAML parses bare `on` as True
    assert set(on["push"]["branches"]) == {"main"}
    assert "pull_request" in on


def test_ci_python_tests_matrix_includes_windows_and_coverage_gate():
    ci = _load(CI)
    job = ci["jobs"]["python-tests"]
    matrix = job["strategy"]["matrix"]["os"]
    assert "ubuntu-latest" in matrix and "windows-latest" in matrix

    run_step = next(s for s in job["steps"] if s.get("name", "").startswith("Run full test suite"))
    script = run_step["run"]
    assert 'not lean_backtest' in script
    assert "--cov-fail-under=80" in script, "coverage fail-under gate must stay at >= 80"


def test_ci_python_lint_job_runs_ruff_and_py_compile():
    ci = _load(CI)
    steps = ci["jobs"]["python-lint"]["steps"]
    scripts = [s.get("run", "") for s in steps]
    joined = "\n".join(scripts)
    # V5.3.11 FIX: lint job runs bare `ruff check .` (NOT `aq test --ruff`)
    # because the minimal environment intentionally has no pandas/torch/etc -
    # `aq test --ruff` requires the full package import chain. Local devs use
    # `aq test --ruff`; CI uses bare ruff for speed.
    assert any("ruff check ." in s for s in scripts), "lint job must run ruff directly"
    assert "aq test --ruff" not in joined, "lint job must NOT import aq_cli chain"
    assert any("py_compile main.py" in s for s in scripts)


def test_ci_webui_job_runs_vitest_before_build():
    """The V5.3.9 gap this round closed: 100 frontend tests existed but never
    ran in CI. This pins them to the webui job permanently."""
    ci = _load(CI)
    steps = ci["jobs"]["webui-tests"]["steps"]
    scripts = [s.get("run", "") for s in steps if "run" in s]
    assert any("vitest run --pool=threads" in s for s in scripts), "frontend tests must run in CI"
    build_idx = next(i for i, s in enumerate(scripts) if "build" in s)
    vitest_idx = next(i for i, s in enumerate(scripts) if "vitest run" in s)
    assert vitest_idx < build_idx


def test_release_has_nonblocking_visibility_test_job():
    """User decision (V5.3.9): tag-push releases proceed even when tests
    fail - the tag-tests job exists purely for gap visibility and must NOT
    be wired into the publish jobs' needs chains."""
    release = _load(RELEASE)
    jobs = release["jobs"]
    assert "tag-tests" in jobs

    for publish_job in ("publish-pypi", "publish-docker", "github-release"):
        needs = jobs[publish_job].get("needs") or []
        needs_list = needs if isinstance(needs, list) else [needs]
        assert "tag-tests" not in needs_list, (
            f"{publish_job} must not gate on tag-tests (releases are deliberately non-blocking)"
        )


def test_release_publishes_all_three_targets():
    release = _load(RELEASE)
    for job in ("publish-pypi", "publish-docker", "github-release"):
        assert job in release["jobs"]


def test_readme_documents_the_monte_carlo_cli_surface():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "--monte-carlo" in readme
    assert "### Monte Carlo Simulation" in readme


def test_every_requirements_line_parses_as_a_valid_requirement():
    """Pins the V5.3.10 regression: a PowerShell-mangled append split a
    comment mid-word, leaving `uff check .)` as an unparsable requirement
    that failed the ubuntu install job after 9 seconds. Every non-comment,
    non-empty line of every requirements file must parse."""
    from packaging.requirements import Requirement

    for req_file in sorted((ROOT / "requirements").glob("*.txt")):
        for line_no, raw in enumerate(
            req_file.read_text(encoding="utf-8").splitlines(), start=1
        ):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                Requirement(line)
            except Exception as error:  # noqa: BLE001
                pytest.fail(f"{req_file.name}:{line_no} invalid requirement {line!r}: {error}")


def test_actionlint_is_pinned_to_a_fixed_version():
    """The first workflows-lint implementation downloaded `latest` via a
    third-party script and then lost the binary between steps (command not
    found). Pinned single-step install + explicit relative invocation."""
    release = _load(RELEASE)
    assert "tag-tests" in release["jobs"]

    ci = _load(CI)
    lint_steps = ci["jobs"]["workflows-lint"]["steps"]
    run_scripts = [s.get("run", "") for s in lint_steps]
    joined = "\n".join(run_scripts)
    assert "actionlint_1.7.7" in joined, "actionlint must be version-pinned"
    assert "./actionlint" in joined, "must invoke the extracted binary explicitly"


# ---------------------------------------------------------------------------
# V5.5.0 - the guard jobs added for the offline/live-parity round. Each test
# pins one property that a refactor of ci.yml could silently lose.
# ---------------------------------------------------------------------------

import re  # noqa: E402

V550_JOBS = (
    "fast-guards", "subsystem-matrix", "wheel-smoke", "python-compat", "docker-checks",
    "parity-smoke", "secret-scan", "test-count-drift",
)


def _scripts(job: dict) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_ci_has_every_v550_guard_job_and_the_originals_survive():
    jobs = set(_load(CI)["jobs"])
    assert set(V550_JOBS) <= jobs
    assert {"python-tests", "python-lint", "dependency-audit", "webui-tests", "cli-smoke", "workflows-lint"} <= jobs


def test_every_new_job_has_a_timeout_so_a_hung_runner_cannot_burn_hours():
    jobs = _load(CI)["jobs"]
    missing = [name for name in V550_JOBS if "timeout-minutes" not in jobs[name]]
    assert not missing, f"jobs without timeout-minutes: {missing}"


def test_subsystem_matrix_covers_exactly_the_registered_test_buckets():
    """A bucket added to aq_cli.py::_SUBSYSTEM_TEST_FILES must also join the
    matrix (and vice versa), or its files only ever run in the full tree."""
    import aq_cli

    matrix = _load(CI)["jobs"]["subsystem-matrix"]["strategy"]["matrix"]["subsystem"]
    assert sorted(matrix) == sorted(aq_cli._SUBSYSTEM_TEST_FILES)
    assert _load(CI)["jobs"]["subsystem-matrix"]["strategy"]["fail-fast"] is False
    assert "aq test --${{ matrix.subsystem }}" in _scripts(_load(CI)["jobs"]["subsystem-matrix"])


def test_wheel_smoke_builds_a_real_wheel_and_runs_the_script_outside_the_checkout():
    job = _load(CI)["jobs"]["wheel-smoke"]
    checkout = job["steps"][0]
    assert checkout["with"]["fetch-depth"] == 0, "setuptools-scm needs the tags to version the wheel"
    script = _scripts(job)
    assert "python -m build --wheel" in script
    assert "dist/*.whl" in script
    smoke = next(step for step in job["steps"] if "wheel_smoke.py" in step.get("run", ""))
    assert smoke["working-directory"] == "${{ runner.temp }}", "must run OUTSIDE the checkout, or -e-style masking returns"
    assert "pip install -e" not in script, "an editable install would hide every packaging gap"


def test_python_compat_leg_compiles_on_the_oldest_supported_python():
    job = _load(CI)["jobs"]["python-compat"]
    versions = [step["with"]["python-version"] for step in job["steps"] if "with" in step and "python-version" in step["with"]]
    assert versions == ["3.10"]
    assert "compileall" in _scripts(job)
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.10"' in pyproject, "the compat leg exists because 3.10 is still supported"


def test_docker_checks_lint_validate_and_never_build_the_lean_image():
    job = _load(CI)["jobs"]["docker-checks"]
    script = _scripts(job)
    assert "hadolint/releases/download/v2.12.0/" in script, "hadolint must be version-pinned"
    assert "--failure-threshold error" in script
    assert "docker compose -f docker-compose.yml config -q" in script
    assert "--profile lean config -q" in script
    build_lines = [line for line in script.splitlines() if "docker build" in line or "buildx" in line]
    assert build_lines and all("Dockerfile.lean" not in line for line in build_lines), (
        "Dockerfile.lean's ~40 GB quantconnect/lean base cannot be built on a hosted runner"
    )


def test_advisory_jobs_are_advisory_and_blocking_jobs_are_not():
    jobs = _load(CI)["jobs"]
    for advisory in ("secret-scan", "test-count-drift"):
        assert jobs[advisory].get("continue-on-error") is True, f"{advisory} is advisory until proven against real history"
    for blocking in ("fast-guards", "subsystem-matrix", "wheel-smoke", "python-compat", "docker-checks", "parity-smoke"):
        assert not jobs[blocking].get("continue-on-error"), f"{blocking} must be able to fail the build"
    assert "gitleaks/releases/download/v8.18.4/" in _scripts(jobs["secret-scan"]), "gitleaks must be version-pinned"
    assert "--config .gitleaks.toml" in _scripts(jobs["secret-scan"]), "the scan must use the repo allowlist"
    assert (ROOT / ".gitleaks.toml").is_file()
    assert "check_test_count_drift.py" in _scripts(jobs["test-count-drift"])
    audit_step = next(s for s in jobs["webui-tests"]["steps"] if "npm audit" in s.get("run", ""))
    assert audit_step.get("continue-on-error") is True


def test_every_job_that_installs_the_requirements_on_linux_installs_cpu_torch_first():
    jobs = _load(CI)["jobs"]
    for name in ("python-tests", "fast-guards", "subsystem-matrix", "parity-smoke", "cli-smoke", "test-count-drift"):
        runs = [step.get("run", "") for step in jobs[name]["steps"]]
        cpu = next((i for i, run in enumerate(runs) if "download.pytorch.org/whl/cpu" in run), None)
        install = next((i for i, run in enumerate(runs) if "-r requirements/requirements.txt" in run), None)
        assert cpu is not None and install is not None and cpu < install, f"{name}: CPU torch must precede the requirements install"
    windows_safe = next(s for s in jobs["python-tests"]["steps"] if "download.pytorch.org" in s.get("run", ""))
    assert windows_safe["if"] == "runner.os == 'Linux'"


def test_scripts_and_test_files_the_workflows_reference_exist():
    text = CI.read_text(encoding="utf-8")
    for path in set(re.findall(r"(?:scripts|tests)/[A-Za-z0-9_./]+\.py", text)):
        assert (ROOT / path).exists(), f"ci.yml references missing file {path}"


def test_fast_guards_and_parity_smoke_run_the_expected_test_files():
    jobs = _load(CI)["jobs"]
    fast = _scripts(jobs["fast-guards"])
    for name in ("test_ci_workflows", "test_packaging_modules", "test_docs_links", "test_cli_help_surface", "test_v550_parity_fixes"):
        assert name in fast
    assert "test_subsystem_test_files_maps_every_real_test_file_to_exactly_one_bucket" in fast
    parity = _scripts(jobs["parity-smoke"])
    for name in ("test_backtest_audit", "test_live_parity", "test_legacy_sleeve", "test_volatility_threshold_calibration"):
        assert name in parity
    assert "feature_parity_audit.py --synthetic-only" in parity


def test_dependabot_covers_pip_npm_and_github_actions():
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    assert config["version"] == 2
    ecosystems = {update["package-ecosystem"]: update["directory"] for update in config["updates"]}
    assert ecosystems == {"pip": "/requirements", "npm": "/webui", "github-actions": "/"}
    assert all(update["schedule"]["interval"] == "weekly" for update in config["updates"])


def test_dev_requirements_pin_the_same_ruff_as_the_lint_job():
    ci_pin = re.search(r'pip install "ruff==([0-9.]+)"', CI.read_text(encoding="utf-8"))
    dev_pin = re.search(r"^ruff==([0-9.]+)$", (ROOT / "requirements" / "requirements-dev.txt").read_text(encoding="utf-8"), re.M)
    assert ci_pin and dev_pin, "both places must pin ruff exactly"
    assert ci_pin.group(1) == dev_pin.group(1)


def test_agents_md_describes_the_real_ci_not_the_old_single_job_version():
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "Python 3.10 → install" not in agents and "setup-python 3.10" not in agents
    assert "Python 3.11" in agents
    for job in ("fast-guards", "wheel-smoke", "subsystem-matrix"):
        assert job in agents
