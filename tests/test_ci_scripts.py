"""Tests for the CI helper scripts under scripts/ (V5.5.0): the synthetic-only
mode of the feature-parity audit. Loaded
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
