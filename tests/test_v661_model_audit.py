"""scripts/v661_model_audit.py (V6.6.6): every group x horizon look is counted in the ledger once, with no Sharpe."""

from __future__ import annotations

import json
from types import SimpleNamespace

from script_loader import load_script, run_script


def test_looks_are_counted_once_and_the_report_written(tmp_path, monkeypatch, capsys):
    module = load_script("v661_model_audit")
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setattr(module, "LEDGER", ledger)
    monkeypatch.setattr(module, "equity_cell", lambda root, base, name: SimpleNamespace(features="f", member="m"))
    monkeypatch.setattr(module, "fundamental_coverage", lambda features, member: {"share": 0.5})
    monkeypatch.setattr(module, "feature_group_ic", lambda cell: {"value": {"20d": {"mean_ic": 0.01, "nonoverlap_t": None}, "60d": None}})
    out = tmp_path / "audit" / "model_audit.json"
    assert module.main(["--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    looks = len(module.FEATURE_GROUPS) * len(module.HORIZONS)
    assert len(report["looks_added"]) == looks and report["coverage"] == {"share": 0.5}
    assert module.count_looks(ledger) == [] and len(ledger.read_text(encoding="utf-8").splitlines()) == looks
    assert "value {'20d': (0.01, 0.0), '60d': None}" in capsys.readouterr().out


def test_help_runs_as_a_script(monkeypatch, capsys):
    assert run_script("v661_model_audit", ["--help"], monkeypatch) == 0
    assert "--out" in capsys.readouterr().out
