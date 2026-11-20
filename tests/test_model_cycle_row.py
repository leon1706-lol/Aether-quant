"""scripts/model_cycle_row.py (V6.6.10): the weekly model cycle's ledger row, once per session."""

from __future__ import annotations

import json

from script_loader import load_script, run_script


def _run_dir(tmp_path):
    run = tmp_path / "runs" / "model-cycle"
    run.mkdir(parents=True)
    (run / "report.json").write_text(json.dumps({"name": "pipeline", "gate": {"signal": {"passed": False}}}), encoding="utf-8")
    return run


def test_a_row_holds_the_gate_and_the_example_hashes_and_is_written_once(tmp_path):
    module = load_script("model_cycle_row")
    run = _run_dir(tmp_path)
    examples = tmp_path / "ex"
    examples.mkdir()
    (examples / "example_models_manifest.json").write_text(json.dumps({"models": {"b": {"sha256": "2", "size": 2, "kind": "x"}, "a": {"sha256": "1", "size": 1}}}), encoding="utf-8")
    row = module.cycle_row(run, examples, session="2026-11-23")
    assert list(row["examples"]) == ["a", "b"] and row["gate"]["signal"]["passed"] is False
    ledger = tmp_path / "ledger" / "forward" / "model_cycle.jsonl"
    assert module.append_row(ledger, row) is True and module.append_row(ledger, row) is False
    assert module.cycle_row(run, tmp_path / "none", session="s")["examples"] == {}


def test_main_appends_and_runs_as_a_script(tmp_path, monkeypatch, capsys):
    run = _run_dir(tmp_path)
    argv = ["--run-dir", str(run), "--examples", str(tmp_path / "none"), "--ledger", str(tmp_path / "l.jsonl")]
    assert run_script("model_cycle_row", argv, monkeypatch) == 0 and "appended" in capsys.readouterr().out
    assert run_script("model_cycle_row", argv, monkeypatch) == 0 and "already recorded" in capsys.readouterr().out
    assert run_script("model_cycle_row", [*argv, "--session", "2020-01-01"], monkeypatch) == 0
    assert len((tmp_path / "l.jsonl").read_text(encoding="utf-8").splitlines()) == 2
