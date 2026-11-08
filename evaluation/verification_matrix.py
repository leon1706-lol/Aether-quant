"""Every way this project can be verified, in one table (V6.6.4): `aq verify`, and `development/verification.md` generated from it.

A surface is a command that proves something, with the host it runs on, what it costs and where its evidence lands. The table is data, so a test can hold it to the repository: every CI job,
every workflow, every Lean smoke and every formal target has a row, and a row that names an `aq` command names one that exists. Adding a way to test the project without adding its row fails
`tests/test_verification_matrix.py`. The `--quick` set is what a 4 GB machine can run between edits; the rest says where it belongs.

Pure data and one small runner; stdlib only.
"""

# ruff: noqa: E501  (a table: one surface per line, so it reads and diffs row by row)
from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

HOSTS = ("PC", "Codespace", "DinD Codespace", "CI", "GitHub", "owner")


@dataclass(frozen=True)
class Surface:
    id: str
    command: str
    proves: str
    host: tuple[str, ...]
    time: str
    evidence: str
    required: str  # when it must have passed: "every change", "every commit", "a phase", "a release", "on demand"
    quick: bool = False
    argv: tuple[str, ...] = field(default_factory=tuple)  # what `aq verify --quick` runs; empty for a surface that does not run on the PC


def _s(id, command, proves, host, time, evidence, required, argv=None):
    return Surface(id, command, proves, tuple(host), time, evidence, required, bool(argv), tuple(argv or ()))


PY = sys.executable
SURFACES: tuple[Surface, ...] = (
    # --- code style and compatibility
    _s("ruff", "ruff check .", "style and the obvious errors", ["PC", "CI"], "10 s", "stdout", "every change", [PY, "-m", "ruff", "check", "."]),
    _s("vermin", "vermin -t=3.10- --no-tips --violations -q <first-party>", "no source needs more than Python 3.10 (#326)", ["PC", "CI"], "5 s", "stdout; CI python-compat", "every commit"),
    # --- the suite
    _s("suite", "aq test", "the whole offline suite, coverage >= 80%, refreshes the badge", ["Codespace", "CI"], "4-6 min (PC: out of memory)", "stdout, coverage.xml", "every commit"),
    _s("buckets", "aq test --<bucket>", "each of 15 subsystems is self-contained", ["PC", "CI"], "1-2 min each", "stdout", "every commit"),
    _s("guards", "pytest tests/test_ci_workflows.py tests/test_docs_facts.py tests/test_aether_quant_coverage.py ...", "workflows, docs facts, the library gate, packaging, help surface", ["PC", "CI"], "30 s", "stdout; CI fast-guards", "every change", [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_ci_workflows.py", "tests/test_docs_facts.py", "tests/test_aether_quant_coverage.py", "tests/test_module_has_test.py", "tests/test_formal_no_sorry.py", "tests/test_verification_matrix.py"]),
    _s("clean_checkout", "scripts/clean_checkout_test.ps1 or scripts/codespace_verify.ps1 -Start", "no test depends on a gitignored file; every CI job once, before the push", ["Codespace"], "40-60 min", "/tmp/aq_verify/status, <stage>.log", "a phase"),
    # --- the library
    _s("library_gate", "python scripts/library_gate.py", "a public function is in aether_quant or explained; the backlog only shrinks", ["PC", "CI"], "1 s", "stdout; pre-commit hook", "every commit", [PY, "scripts/library_gate.py"]),
    _s("api_pin", "aq test --meta (tests/test_aether_quant_api.py)", "every export resolves to the real function; the import stays light; the public surface only changes on purpose", ["PC", "CI"], "1 min", "tests/data/aether_quant_api.json", "every commit"),
    _s("quickstart", "tests/test_aether_quant_quickstart.py", "the library works from an uninstalled checkout, examples included", ["PC", "CI"], "1 min", "stdout", "every commit"),
    _s("wheel_smoke", "python scripts/wheel_smoke.py (built wheel, outside the checkout)", "every shipped module imports, every aq subcommand has --help, one real call into each library module", ["Codespace", "CI"], "2 min", "stdout; CI wheel-smoke", "a release"),
    # --- proofs
    _s("prove", "aq prove", "the Lean 4 specs build (Mathlib)", ["Codespace", "CI"], "5 min (Mathlib cached)", "stdout; CI formal.yml", "every change to formal/ or a modelled file"),
    _s("prove_sorry", "aq prove --check-sorry", "no sorry or admit in any spec", ["PC", "CI"], "1 s", "stdout; tests/test_formal_no_sorry.py", "every commit", [PY, "aq_cli.py", "prove", "--check-sorry"]),
    _s("axioms", "python scripts/check_axioms.py", "every theorem rests on the three standard axioms, but two named native_decide findings", ["Codespace", "CI"], "2 min", "stdout; CI formal.yml", "every change to formal/"),
    _s("differential", "aq test --formal", "the Python functions equal the Lean models on thousands of computed cases (16 targets)", ["PC", "CI"], "1 min", "aether_quant/_formal_cases/*.json", "every commit"),
    # --- other kinds of test
    _s("properties", "pytest tests/test_v664_properties.py", "invariants of the order gate, admission, session, shares, weight caps, hash chain and JSON safety hold for every input (hypothesis, derandomized)", ["PC", "CI"], "2 min", "stdout", "every commit"),
    _s("mutation", "python scripts/mutation_check.py --out ml/evaluation/v664/mutation.json", "the tests of seven safety and ledger modules notice a changed comparison, operator or constant", ["Codespace"], "1-2 h", "ml/evaluation/v664/mutation.json", "a phase"),
    _s("on_data", "pytest tests/test_main_on_data_target_weights.py", "on_data() on the shipped path places the orders the pure rebalance function says, across a week", ["PC", "CI"], "10 s", "stdout", "every change to main.py"),
    _s("module_has_test", "pytest tests/test_module_has_test.py", "every shipped module has its own test file or is on the frozen list", ["PC", "CI"], "5 s", "stdout", "every commit", [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_module_has_test.py"]),
    # --- docs, secrets, dependencies, images
    _s("docs_sync", "aq docs sync --check", "every number quoted in a doc is a current fact", ["PC", "CI"], "10 s", "stdout", "every commit", [PY, "aq_cli.py", "docs", "sync", "--check"]),
    _s("secrets", "aq secrets-check", "no secret in a tracked file", ["PC", "CI"], "2 s", "stdout; pre-commit hook", "every commit", [PY, "aq_cli.py", "secrets-check"]),
    _s("readme_freshness", "python scripts/readme_freshness.py --since <date>", "the README's generated blocks are newer than their inputs", ["PC"], "10 s", "stdout", "a phase"),
    # --- the engine
    _s("lean_backtest", "aq backtest", "a real Lean backtest of the shipped book (the owner runs it)", ["owner"], "1 h+", "backtests/<run>/log.txt", "a material change to the book"),
    _s("lean_runs", "scripts/codespace_lean_run.ps1 -Create/-Push/-Run/-Pull -Delete", "frozen run configs on a DinD Codespace, engine log read for completion (rule 7)", ["DinD Codespace"], "2 min per 3 years", "backtests/<run>/", "a change to the book"),
    _s("lean_smoke:option_structures", "bash scripts/lean_smoke/run.sh option_structures", "all 43 option structures fill in Lean's engine on its sample chain", ["DinD Codespace"], "30 s", "backtests/smoke_option_structures", "a phase"),
    _s("lean_smoke:futures_margin", "bash scripts/lean_smoke/run.sh futures_margin", "futures margin calls main.py makes return a number", ["DinD Codespace"], "30 s", "backtests/smoke_futures_margin", "a phase"),
    _s("lean_smoke:exception_scope", "bash scripts/lean_smoke/run.sh exception_scope", "Lean's star import shadows Exception, which main.py corrects (#276)", ["DinD Codespace"], "30 s", "backtests/smoke_exception_scope", "on demand"),
    _s("lean_smoke:main_option_order", "bash scripts/lean_smoke/run_main_option_order.sh", "main.py's own multi-leg order fills on the sample chain", ["DinD Codespace"], "2 min", "backtests/smoke_main_option_order", "a phase"),
    _s("lean_smoke:main_option_scenarios", "bash scripts/lean_smoke/run_main_option_scenarios.sh <scale|all43|arb|assign>", "scale-down, rotation, every structure, the arbitrage router and the assignment sweep through main.py", ["DinD Codespace"], "2 min each", "ml/evaluation/v664/lean_smoke_option_*.jsonl", "a phase"),
    _s("lean_smoke:live_plumbing", "bash scripts/lean_smoke/live_plumbing.sh", "main.py runs in Lean's live-paper mode on PaperBrokerage and fake ticks with no login or key, survives Redis then Postgres stopping under it, restarts, and the audit chain verifies", ["DinD Codespace"], "10 min", "ml/evaluation/v664/live_plumbing.json", "a phase"),
    _s("engine_check", "scripts/codespace_engine_check.sh", "the pinned engine image runs a teardown-clean algorithm", ["DinD Codespace"], "5 min", "/tmp/aq_lean/engine_status", "on demand"),
    # --- evaluation audits
    _s("lean_report", "aq evaluate --lean-report --backtest-dir <run>", "statistics, alpha proof, attribution and every run-folder tool for a pinned run (rule 8)", ["PC"], "2 min", "ml/evaluation/*.json, README blocks", "every new pin"),
    _s("reconcile_features", "aq evaluate --reconcile-features --symbol <X>", "a backtest's feature snapshot equals the dataset's row (rule 12)", ["PC"], "1 min", "ml/evaluation/feature_reconciliation.json", "a change to features"),
    _s("paper_check", "aq evaluate --paper-check --backtest-dir <run> --reference-dir <pin>", "a paper run sits inside the frozen bands of the pinned run", ["PC"], "10 s", "ml/evaluation/paper_check.json", "a paper period"),
    _s("forward_ledger", "aq evaluate --forward-ledger; aq cycle status", "the forward chains are intact and current", ["PC", "GitHub"], "5 s", "forward/*.jsonl on the forward-ledger branch", "every session"),
    _s("research_round", "aq cycle research score|placebo|gate|pbo|report --round <file>", "a pre-registered round, rule file hashed in the vault before any score", ["PC", "Codespace"], "5 min - 2 h", "ml/evaluation/<phase>/", "a research round"),
    # --- services and field tests
    _s("audit_verify", "aq audit-log --verify", "the audit chain in Postgres is intact (a real database; #339)", ["Codespace"], "5 s", "stdout", "a phase"),
    _s("paper_readiness", "aq paper-readiness", "the paper-readiness checklist against real services", ["Codespace"], "5 s", "visualization/grafana/paper_readiness_report.json", "a phase"),
    _s("field_test_services", "python scripts/field_test_services.py (scripts/field_services.sh up)", "audit events flow Redis to Postgres, a tampered row is found, each service restarts underneath a running pipeline", ["Codespace"], "2 min", "ml/evaluation/v664/field_test_services.json", "a phase"),
    # --- CI jobs (one row each; the table is held to ci.yml)
    _s("ci:python-tests", "CI: ubuntu and windows, coverage gate 80%", "the suite on both platforms", ["CI"], "6 min", "GitHub Actions", "every push"),
    _s("ci:python-lint", "CI: ruff and py_compile main.py", "lint and syntax", ["CI"], "1 min", "GitHub Actions", "every push"),
    _s("ci:dependency-audit", "CI: pip-audit", "no known-vulnerable pinned dependency", ["CI"], "3 min", "GitHub Actions", "every push"),
    _s("ci:webui-tests", "CI: tsc, oxlint, vitest, build", "the dashboard builds and its tests pass", ["CI"], "1 min", "GitHub Actions", "every push"),
    _s("ci:cli-smoke", "CI: aq --help, config get, secrets-check", "the CLI starts from a clean install", ["CI"], "1 min", "GitHub Actions", "every push"),
    _s("ci:workflows-lint", "CI: actionlint", "workflow syntax", ["CI"], "10 s", "GitHub Actions", "every push"),
    _s("ci:fast-guards", "CI: guard tests", "registration, help surface, workflows, packaging, docs, library gate", ["CI"], "1 min", "GitHub Actions", "every push"),
    _s("ci:subsystem-matrix", "CI: aq test --<bucket> for each of 15 buckets", "each bucket stands alone", ["CI"], "2 min each", "GitHub Actions", "every push"),
    _s("ci:wheel-smoke", "CI: build and install the wheel outside the checkout", "the package works installed", ["CI"], "1 min", "GitHub Actions", "every push"),
    _s("ci:python-compat", "CI: byte-compile and vermin on Python 3.10", "the floor in requires-python holds", ["CI"], "1 min", "GitHub Actions", "every push"),
    _s("ci:docker-checks", "CI: hadolint, compose config", "the Dockerfiles lint and the compose file parses", ["CI"], "1 min", "GitHub Actions", "every push"),
    _s("ci:parity-smoke", "CI: parity tests and feature_parity_audit --synthetic-only", "live and offline compute the same features", ["CI"], "1 min", "GitHub Actions", "every push"),
    _s("ci:secret-scan", "CI: gitleaks", "no secret in history", ["CI"], "10 s", "GitHub Actions", "every push"),
    _s("ci:test-count-drift", "CI: README badge against the collected count", "the badge is current (advisory)", ["CI"], "1 min", "GitHub Actions", "every push"),
    # --- the other workflows
    _s("wf:formal", ".github/workflows/formal.yml", "the proofs, the sorry scan, regenerated cases and axioms on spec changes and monthly", ["GitHub"], "10 min", "GitHub Actions", "every change to formal/"),
    _s("wf:forward-ledger", ".github/workflows/forward-ledger.yml", "one hash-chained forward row a session for the frozen rule", ["GitHub"], "30 s", "branch forward-ledger", "every session"),
    _s("wf:research-cycle", ".github/workflows/research-cycle.yml", "one row per tracked generation and the allocation a session", ["GitHub"], "30 s", "branch forward-ledger", "every session"),
    _s("wf:keepalive", ".github/workflows/keepalive.yml", "the schedules stay enabled", ["GitHub"], "10 s", "GitHub Actions", "monthly"),
    _s("wf:release", ".github/workflows/release.yml", "the tagged commit's suite, PyPI and the image (the tag is the owner's)", ["GitHub", "owner"], "15 min", "GitHub Actions", "a release"),
    _s("wf:ci", ".github/workflows/ci.yml", "the jobs above", ["GitHub"], "6 min", "GitHub Actions", "every push"),
)


def by_id() -> dict[str, Surface]:
    return {surface.id: surface for surface in SURFACES}


def quick_set() -> list[Surface]:
    return [surface for surface in SURFACES if surface.quick]


def markdown() -> str:
    """The table `development/verification.md` carries between its markers."""
    lines = ["| Surface | Command | What it proves | Host | Time | Evidence | When |", "|---|---|---|---|---|---|---|"]
    for surface in SURFACES:
        lines.append(
            f"| `{surface.id}` | `{surface.command}` | {surface.proves} | {', '.join(surface.host)} | {surface.time} | {surface.evidence} | {surface.required} |"
        )
    return "\n".join(lines)


def run_quick(root: Path, *, runner: Callable = subprocess.run, emit: Callable[[str], None] = print) -> list[dict]:
    """Runs the PC-safe surfaces one after another and reports each: id, exit code, seconds, the last lines of output."""
    results = []
    for surface in quick_set():
        started = time.time()
        result = runner(list(surface.argv), cwd=str(root), capture_output=True, text=True)
        text = ((result.stdout or "") + (result.stderr or "")).strip().splitlines()
        results.append({"id": surface.id, "exit": result.returncode, "seconds": round(time.time() - started, 1), "tail": text[-3:]})
        emit(f"{'ok  ' if result.returncode == 0 else 'FAIL'} {surface.id} ({results[-1]['seconds']} s)")
    return results


def record(path: Path, results: Sequence[Mapping]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps({"surfaces": len(SURFACES), "quick_run": list(results), "all_quick_passed": all(item["exit"] == 0 for item in results)}, indent=1), encoding="utf-8", newline="\n")
