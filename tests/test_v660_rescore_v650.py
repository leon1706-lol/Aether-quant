"""scripts/v660_rescore_v650.py (V6.6.6): V6.5.0's sleeves rescored beside their frozen scores, resumable, report only."""

from __future__ import annotations

import json
from types import SimpleNamespace

from script_loader import load_script


def test_each_sleeve_is_rescored_once_and_changed_clauses_are_named(tmp_path, monkeypatch, capsys):
    module = load_script("v660_rescore_v650")
    v650 = tmp_path / "v650"
    v650.mkdir()
    (v650 / "rules.json").write_text("{}", encoding="utf-8")
    out = tmp_path / "out.json"
    out.write_text(json.dumps({"done": {"frozen_passed_sharpe_clauses": True, "rescored_passes_sharpe_clauses": True}}), encoding="utf-8")
    specs = [
        SimpleNamespace(id="done", params={}), SimpleNamespace(id="skipped_by_only", params={}),
        SimpleNamespace(id="no_table", params={"table": "absent"}), SimpleNamespace(id="a", params={}), SimpleNamespace(id="b", params={"table": "here"}),
    ]
    frozen = {"a": {"sharpe": 0.6, "sharpe_first_half": 0.5, "sharpe_second_half": 0.7}}
    monkeypatch.setattr(module, "V650", v650)
    monkeypatch.setattr(module, "OUT", out)
    monkeypatch.setattr(module, "ALL_SPECS", specs)
    monkeypatch.setattr(module, "read_json", lambda path, default: frozen if path.name == "selection_scores.json" else json.loads(path.read_text(encoding="utf-8")))
    monkeypatch.setattr(module, "load_context", lambda: SimpleNamespace(panel=SimpleNamespace(extras={"here": object()})))
    monkeypatch.setattr(module, "window_of", lambda spec, rules: ("s", "m", "e"))
    monkeypatch.setattr(module, "score_sleeve", lambda spec, context, start, split, end: {"daily": [], "sharpe": 0.3, "sharpe_first_half": 0.2, "sharpe_second_half": 0.4})
    monkeypatch.setattr(module, "passes_sharpe_clauses", lambda score: score.get("sharpe", 0) >= 0.5)
    monkeypatch.setattr(module.sys, "argv", ["x", "--only", "done", "no_table", "a", "b"])

    assert module.main() == 0

    report = json.loads(out.read_text(encoding="utf-8"))
    assert set(report) == {"done", "a", "b"}
    assert report["a"]["frozen"]["sharpe"] == 0.6 and report["a"]["rescored"]["sharpe"] == 0.3 and report["a"]["frozen_passed_sharpe_clauses"] is True
    assert report["b"]["frozen_passed_sharpe_clauses"] is None
    assert "3 rescored, 2 changed their Sharpe clauses: ['a', 'b']" in capsys.readouterr().out


def test_run_as_a_script_it_stops_at_its_first_read(monkeypatch):
    import pytest

    from script_loader import Stop, run_script, stop_at_first_read

    stop_at_first_read(monkeypatch)
    with pytest.raises(Stop, match="rules.json"):
        run_script("v660_rescore_v650", [], monkeypatch)
