"""Tests for the CI helper scripts under scripts/ (V5.5.0): the test-count
drift check and the synthetic-only mode of the feature-parity audit. Loaded
by file path (scripts/ is not a package). Conventions match the rest of this
repo: no test classes, module-level helpers."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_ci_script_{name}", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- check_test_count_drift


def test_readme_count_reads_the_badge_marker():
    drift = _load("check_test_count_drift")
    assert drift.readme_count("x <!-- AQ:TEST_COUNT_START -->2935<!-- AQ:TEST_COUNT_END --> y") == 2935
    assert drift.readme_count("<!--AQ:TEST_COUNT_START-->  12  <!--AQ:TEST_COUNT_END-->") == 12
    assert drift.readme_count("no badge here") is None


def test_collected_count_parses_both_pytest_summary_shapes():
    drift = _load("check_test_count_drift")
    assert drift.collected_count("tests/a.py::t\n2935 tests collected in 3.10s") == 2935
    assert drift.collected_count("2935/2936 tests collected (1 deselected) in 3.10s") == 2935
    assert drift.collected_count("1 test collected in 0.01s") == 1
    assert drift.collected_count("no summary") is None


def test_drift_is_a_warning_by_default_and_a_failure_under_strict(monkeypatch, capsys):
    drift = _load("check_test_count_drift")
    monkeypatch.setattr(drift, "run_collect_only", lambda: "2940 tests collected in 1s")
    monkeypatch.setattr(drift, "readme_count", lambda _text: 2935)
    assert drift.main([]) == 0
    assert "::warning::" in capsys.readouterr().out
    assert drift.main(["--strict"]) == 1


def test_matching_counts_pass_silently(monkeypatch, capsys):
    drift = _load("check_test_count_drift")
    monkeypatch.setattr(drift, "run_collect_only", lambda: "2935 tests collected in 1s")
    monkeypatch.setattr(drift, "readme_count", lambda _text: 2935)
    assert drift.main(["--strict"]) == 0
    assert "::warning::" not in capsys.readouterr().out


def test_an_unparsable_collection_is_a_warning_not_a_crash(monkeypatch, capsys):
    drift = _load("check_test_count_drift")
    monkeypatch.setattr(drift, "run_collect_only", lambda: "boom")
    assert drift.main([]) == 0
    assert "could not compare" in capsys.readouterr().out
    assert drift.main(["--strict"]) == 1


# ---------------------------------------------------------------- feature_parity_audit --synthetic-only


def test_synthetic_only_mode_runs_the_real_check_and_it_is_not_silently_dead(tmp_path, monkeypatch):
    """The V5.5.0 find: check 1 raised (a length mismatch, then a changed
    replica signature), the blanket `except` reported it as SKIPPED, and the
    audit still printed PASS - so the replica-vs-train.py parity check had
    been dead. `--synthetic-only` must exit 0 only when the check RAN."""
    audit = _load("feature_parity_audit")
    output = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["feature_parity_audit.py", "--synthetic-only", "--output", str(output)])
    assert audit.main() == 0
    report = json.loads(output.read_text(encoding="utf-8"))["synthetic_formula_parity"]
    assert report["_status"] == "OK"
    verdicts = {name: entry["verdict"] for name, entry in report.items() if isinstance(entry, dict)}
    assert len(verdicts) >= 20  # base technicals + liquidity + the three macro proxies
    assert set(verdicts.values()) == {"PASS"}


def test_synthetic_only_mode_fails_when_the_check_did_not_run(tmp_path, monkeypatch, capsys):
    audit = _load("feature_parity_audit")
    monkeypatch.setattr(audit, "check_synthetic_formula_parity", lambda: {"_status": "SKIPPED: TypeError: boom"})
    monkeypatch.setattr(sys, "argv", ["feature_parity_audit.py", "--synthetic-only", "--output", str(tmp_path / "r.json")])
    assert audit.main() == 1
    assert "check_did_not_run" in capsys.readouterr().out


def test_synthetic_only_and_skip_synthetic_are_mutually_exclusive(monkeypatch):
    audit = _load("feature_parity_audit")
    monkeypatch.setattr(sys, "argv", ["feature_parity_audit.py", "--synthetic-only", "--skip-synthetic"])
    with pytest.raises(SystemExit):
        audit.main()
