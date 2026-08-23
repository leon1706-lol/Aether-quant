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
    names = [s.get("name", "") for s in steps]
    scripts = [s.get("run", "") for s in steps]
    assert any("Ruff check" in n for n in names)
    # The py_compile gate may live in the step name OR its run script.
    assert any("py_compile main.py" in n or "py_compile main.py" in s for n, s in zip(names, scripts))


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
