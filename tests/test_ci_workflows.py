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


def test_research_cycle_runs_daily_shares_the_ledgers_lock_and_writes_only_its_own_file():
    workflow = _load(ROOT / ".github" / "workflows" / "research-cycle.yml")
    forward = _load(ROOT / ".github" / "workflows" / "forward-ledger.yml")
    on = workflow["on"] if "on" in workflow else workflow[True]
    assert on["schedule"][0]["cron"] == "45 22 * * 1-5" and "workflow_dispatch" in on
    assert workflow["concurrency"]["group"] == forward["concurrency"]["group"], "two writers of one branch must not race"
    assert workflow["permissions"] == {"contents": "write"}
    job = workflow["jobs"]["cycle"]
    assert job["timeout-minutes"] == 15
    text = "\n".join(str(step.get("run", "")) for step in job["steps"])
    assert "scripts/cycle_daily.py" in text and "git add forward/generations.jsonl" in text
    assert "forward/ledger.jsonl" not in text, "the older chain belongs to forward-ledger.yml"
    assert (ROOT / "scripts" / "cycle_daily.py").exists()
    assert "secrets." not in (ROOT / ".github" / "workflows" / "research-cycle.yml").read_text(encoding="utf-8")


def test_python_compat_checks_the_minimum_python_of_the_sources_and_not_only_that_they_compile():
    steps = _load(CI)["jobs"]["python-compat"]["steps"]
    text = "\n".join(str(step.get("run", "")) for step in steps)
    assert "compileall" in text and "vermin==" in text and "-t=3.10-" in text and "--violations" in text
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.10"' in pyproject, "the check and the metadata must name the same floor"
    assert "datetime import UTC" not in (ROOT / "evaluation" / "lean_statistics.py").read_text(encoding="utf-8")


def test_formal_workflow_builds_the_proofs_with_read_only_permission_and_runs_on_spec_changes():
    path = ROOT / ".github" / "workflows" / "formal.yml"
    workflow = _load(path)
    on = workflow["on"] if "on" in workflow else workflow[True]
    assert workflow["permissions"] == {"contents": "read"}
    assert "formal/**" in on["push"]["paths"] and "aether_quant/_formal_cases/**" in on["push"]["paths"] and "workflow_dispatch" in on and on["schedule"]
    for modeled in ("audit/hash_chain.py", "execution/order_gate.py", "evaluation/generation_registry.py", "evaluation/forward_ledger.py", "evaluation/research_cells.py"):
        assert modeled in on["push"]["paths"], f"{modeled} is modelled in Lean, so a change to it re-runs the proofs"
    assert "secrets." not in path.read_text(encoding="utf-8")


def test_keepalive_re_enables_the_ledger_workflows_with_one_permission_and_no_secret():
    path = ROOT / ".github" / "workflows" / "keepalive.yml"
    workflow = _load(path)
    on = workflow["on"] if "on" in workflow else workflow[True]
    assert on["schedule"][0]["cron"] == "17 4 1 * *" and "workflow_dispatch" in on
    assert workflow["permissions"] == {"actions": "write"}, "it may enable workflows and nothing else"
    text = "\n".join(str(step.get("run", "")) for step in workflow["jobs"]["enable"]["steps"])
    for name in ("forward-ledger.yml", "research-cycle.yml", "keepalive.yml"):
        assert name in text
    assert "secrets." not in path.read_text(encoding="utf-8") and "git push" not in text


def test_ci_triggers_on_main_push_and_prs():
    ci = _load(CI)
    on = ci["on"] if "on" in ci else ci[True]  # PyYAML parses bare `on` as True
    assert set(on["push"]["branches"]) == {"main"}
    assert "pull_request" in on


def test_ci_python_tests_matrix_includes_windows_and_coverage_gate():
    ci = _load(CI)
    job = ci["jobs"]["python-tests"]
    matrix = job["strategy"]["matrix"]["os"]
    assert "ubuntu-24.04" in matrix and "windows-latest" in matrix

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
    assert "#### Monte Carlo Simulation" in readme


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
V665_JOBS = ("lite-install", "typecheck", "docs", "notebooks", "bandit")
CODEQL = ROOT / ".github" / "workflows" / "codeql.yml"
SCORECARD = ROOT / ".github" / "workflows" / "scorecard.yml"
PAGES = ROOT / ".github" / "workflows" / "pages.yml"


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
    assert jobs["test-count-drift"].get("continue-on-error") is True, "the badge drift is warn-only"
    for blocking in ("fast-guards", "subsystem-matrix", "wheel-smoke", "python-compat", "docker-checks", "parity-smoke", "secret-scan", *V665_JOBS):
        assert not jobs[blocking].get("continue-on-error"), f"{blocking} must be able to fail the build"
    assert "gitleaks/releases/download/v8.18.4/" in _scripts(jobs["secret-scan"]), "gitleaks must be version-pinned"
    assert "--config .gitleaks.toml" in _scripts(jobs["secret-scan"]), "the scan must use the repo allowlist"
    assert (ROOT / ".gitleaks.toml").is_file()
    # V6.6.5 (#353): the working-tree scan blocks; the history scan is the one advisory step, until its first report is reviewed
    steps = jobs["secret-scan"]["steps"]
    tree = next(s for s in steps if "--no-git" in s.get("run", ""))
    history = next(s for s in steps if "gitleaks detect" in s.get("run", "") and "--no-git" not in s.get("run", ""))
    assert not tree.get("continue-on-error") and history.get("continue-on-error") is True
    assert steps[0]["with"]["fetch-depth"] == 0, "a history scan needs the history"
    assert "check_test_count_drift.py" in _scripts(jobs["test-count-drift"])
    audit_step = next(s for s in jobs["webui-tests"]["steps"] if "npm audit" in s.get("run", ""))
    assert not audit_step.get("continue-on-error"), "V6.6.5: npm audit of runtime dependencies blocks"


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
    for name in ("test_ci_workflows", "test_packaging_modules", "test_docs_links", "test_cli_help_surface", "test_v550_parity_fixes", "test_docs_facts", "test_aether_quant_coverage"):
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



def test_v665_jobs_exist_with_timeouts_and_check_what_they_claim():
    jobs = _load(CI)["jobs"]
    assert set(V665_JOBS) <= set(jobs)
    assert not [name for name in V665_JOBS if "timeout-minutes" not in jobs[name]]
    lite = _scripts(jobs["lite-install"])
    assert "python -m build --wheel" in lite and "aq hello --offline" in lite and "pip install -e" not in lite
    assert all(heavy in lite for heavy in ("torch", "lean", "fastapi", "scipy")), "the light install is checked for every heavy package"
    assert "scripts/type_completeness.py" in _scripts(jobs["typecheck"]) and "pyright==1.1.409" in _scripts(jobs["typecheck"])
    docs = _scripts(jobs["docs"])
    assert "mkdocs build --strict" in docs and "scripts/build_docs.py --check" in docs and "requirements/requirements-docs.txt" in docs
    assert "scripts/build_notebooks.py --check --execute" in _scripts(jobs["notebooks"])
    assert '"bandit==1.9.4"' in _scripts(jobs["bandit"]) and "-lll" in _scripts(jobs["bandit"])
    assert "--cov-report=json" in _scripts(jobs["python-tests"]) and "coverage_badge.py" in _scripts(jobs["python-tests"])
    assert any("--coverage" in s.get("run", "") for s in jobs["webui-tests"]["steps"])


def test_docker_checks_build_and_smoke_the_dashboard_and_scan_with_a_pinned_trivy():
    job = _load(CI)["jobs"]["docker-checks"]
    script = _scripts(job)
    assert "docker build --target dashboard" in script and "/api/health" in script and '"demo":true' in script
    assert "--profile dashboard config -q" in script and "docker-compose.secrets.yml" in script
    trivy = [step for step in job["steps"] if "trivy-action" in step.get("uses", "")]
    assert len(trivy) == 2 and all(step["uses"] == "aquasecurity/trivy-action@57a97c7e7821a5776cebc9bb87c984fa69cba8f1" for step in trivy)
    assert all(step["with"]["exit-code"] == "1" and step["with"]["severity"] == "CRITICAL" for step in trivy)


def test_codeql_scorecard_and_pages_have_least_privilege():
    codeql = _load(CODEQL)
    assert codeql["permissions"] == {"contents": "read"}
    assert codeql["jobs"]["analyze"]["permissions"]["security-events"] == "write"
    assert set(codeql["jobs"]["analyze"]["strategy"]["matrix"]["language"]) == {"python", "javascript-typescript", "actions"}
    scorecard = _load(SCORECARD)
    assert scorecard["permissions"] == "read-all"
    assert any(step.get("with", {}).get("publish_results") is True for step in scorecard["jobs"]["analysis"]["steps"])
    pages = _load(PAGES)
    on = pages.get(True) or pages.get("on")
    assert on["workflow_run"]["workflows"] == ["CI"] and on["workflow_run"]["branches"] == ["main"]
    assert "head_branch == 'main'" in pages["jobs"]["build"]["if"] and "conclusion == 'success'" in pages["jobs"]["build"]["if"]
    assert pages["permissions"] == {"contents": "read"}
    assert pages["jobs"]["deploy"]["permissions"] == {"pages": "write", "id-token": "write"}
    assert "coverage_badge.py" in _scripts(pages["jobs"]["build"])


def test_release_publishes_both_images_with_sbom_and_provenance():
    release = _load(RELEASE)
    docker = release["jobs"]["publish-docker"]
    targets = {entry["target"]: entry["image"] for entry in docker["strategy"]["matrix"]["include"]}
    assert targets == {"engine": "ghcr.io/leon1706-lol/aether-quant", "dashboard": "ghcr.io/leon1706-lol/aether-quant-dashboard"}
    uses = [step.get("uses", "") for step in docker["steps"]]
    assert any(u.startswith("actions/attest-build-provenance@") for u in uses) and any(u.startswith("anchore/sbom-action@") for u in uses)
    pypi_uses = [step.get("uses", "") for step in release["jobs"]["publish-pypi"]["steps"]]
    assert any(u.startswith("actions/attest-build-provenance@") for u in pypi_uses)
    assert "cyclonedx-py" in _scripts(release["jobs"]["publish-pypi"])
    assert "--outfile" in _scripts(release["jobs"]["publish-pypi"])  # cyclonedx-bom 4.x has no --output-file (v6.6.5 release)



def test_ci_and_release_default_to_a_read_only_token_and_pages_deploys_only_this_repos_pushes():
    """V6.6.5 (#355): CodeQL actions/missing-workflow-permissions, and a fork's branch named main must not reach Pages."""
    for workflow in (".github/workflows/ci.yml", ".github/workflows/release.yml"):
        assert _load(ROOT / workflow)["permissions"] == {"contents": "read"}, workflow
    guard = _load(ROOT / ".github" / "workflows" / "pages.yml")["jobs"]["build"]["if"]
    assert "github.event.workflow_run.event == 'push'" in guard and "head_repository.full_name == github.repository" in guard


def test_the_release_can_run_again_on_a_moved_tag():
    """v6.6.5: the image SBOM step tried to attach to the release (needs contents: write), and a second run of a tag
    must not fail on the release that already exists."""
    release = _load(ROOT / ".github" / "workflows" / "release.yml")
    sbom = [step for step in release["jobs"]["publish-docker"]["steps"] if "anchore/sbom-action" in step.get("uses", "")]
    assert sbom and all(step["with"].get("upload-release-assets") is False for step in sbom)
    assert 'gh release view "$TAG"' in _scripts(release["jobs"]["github-release"])

