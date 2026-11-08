"""The table of verification surfaces is held to the repository (V6.6.4): a new way to test the project must be listed, and every row must be real."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml

from evaluation import verification_matrix as matrix

ROOT = Path(__file__).resolve().parents[1]
IDS = matrix.by_id()


def test_every_ci_job_has_a_row():
    jobs = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))["jobs"]
    missing = [f"ci:{job}" for job in jobs if f"ci:{job}" not in IDS]
    assert not missing, f"add rows to evaluation/verification_matrix.py for {missing}"
    stale = [identifier for identifier in IDS if identifier.startswith("ci:") and identifier[3:] not in jobs]
    assert not stale, f"rows for CI jobs that no longer exist: {stale}"


def test_every_workflow_has_a_row():
    names = {path.stem for path in (ROOT / ".github" / "workflows").glob("*.yml")}
    assert names <= {identifier[3:] for identifier in IDS if identifier.startswith("wf:")}, sorted(names - {identifier[3:] for identifier in IDS if identifier.startswith("wf:")})
    assert {identifier[3:] for identifier in IDS if identifier.startswith("wf:")} <= names


def test_every_lean_smoke_algorithm_has_a_row():
    smokes = {path.stem for path in (ROOT / "scripts" / "lean_smoke").glob("*.py") if not path.stem.startswith("make_") and not path.stem.endswith("_report")}
    listed = {identifier.split(":", 1)[1] for identifier in IDS if identifier.startswith("lean_smoke:")}
    assert smokes <= listed | {"main_option_scenarios"}, sorted(smokes - listed)
    assert "main_option_scenarios" in listed


def test_every_formal_target_and_spec_is_covered_by_the_proof_rows():
    for needed in ("prove", "prove_sorry", "axioms", "differential"):
        assert needed in IDS
    targets = sorted(path.stem for path in (ROOT / "aether_quant" / "_formal_cases").glob("*.json"))
    assert f"({len(targets)} targets)" in IDS["differential"].proves, f"the differential row names {len(targets)} targets"


def test_a_row_that_names_an_aq_command_names_one_that_exists():
    import aq_cli

    commands = set()
    for action in aq_cli.build_parser()._actions:
        commands |= set(getattr(action, "choices", {}) or {})
    for surface in matrix.SURFACES:
        for found in re.findall(r"\baq (?:--help|([a-z][a-z-]*))", surface.command):
            if found:
                assert found in commands, f"{surface.id}: `aq {found}` is not a command"
    assert "verify" in commands


def test_the_table_in_the_doc_is_the_generated_one():
    text = (ROOT / "development" / "verification.md").read_text(encoding="utf-8")
    start, end = "<!-- AQ:VERIFICATION_START -->", "<!-- AQ:VERIFICATION_END -->"
    body = text.split(start, 1)[1].split(end, 1)[0].strip()
    assert body == matrix.markdown(), "run `aq verify --write-doc`"


def test_ids_are_unique_and_every_row_names_a_known_host_and_a_moment():
    assert len(IDS) == len(matrix.SURFACES)
    for surface in matrix.SURFACES:
        assert surface.host and set(surface.host) <= set(matrix.HOSTS), surface.id
        assert surface.required.strip() and surface.proves.strip() and surface.command.strip(), surface.id


def test_the_quick_set_is_what_a_small_machine_runs_and_each_entry_is_a_real_command():
    quick = matrix.quick_set()
    assert {surface.id for surface in quick} >= {"ruff", "library_gate", "prove_sorry", "docs_sync", "secrets", "guards"}
    for surface in quick:
        assert surface.argv and set(surface.host) & {"PC"}, surface.id


def test_aq_verify_lists_the_table_and_runs_through_a_fake_runner(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "aq_cli.py"), "verify", "--list"], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0 and "| Surface |" in result.stdout and "`library_gate`" in result.stdout
    calls = []

    def runner(command, **_):
        calls.append(command)
        return type("Result", (), {"returncode": 0, "stdout": "fine", "stderr": ""})()

    results = matrix.run_quick(ROOT, runner=runner, emit=lambda line: None)
    assert len(results) == len(matrix.quick_set()) == len(calls) and all(item["exit"] == 0 for item in results)
    matrix.record(tmp_path / "out.json", results)
    assert '"all_quick_passed": true' in (tmp_path / "out.json").read_text(encoding="utf-8")
