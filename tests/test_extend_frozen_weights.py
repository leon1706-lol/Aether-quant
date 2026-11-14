"""scripts/extend_frozen_weights.py (V6.6.6): a copy of a frozen weight file, extended by its own rule, never rewriting history."""

from __future__ import annotations

import json

import pytest

from script_loader import load_script


def test_frozen_rows_stay_and_only_later_rows_are_added():
    module = load_script("extend_frozen_weights")
    source = {"2024-01-02": {"A": 0.1}, "2024-01-09": {"A": 0.2}}
    new = {"2024-01-02": {"A": 0.9}, "2024-01-09": {"A": 0.9}, "2024-01-16": {"A": 0.3}}
    assert module.extended_rows(source, new, "2024-01-09") == {"2024-01-02": {"A": 0.1}, "2024-01-09": {"A": 0.2}, "2024-01-16": {"A": 0.3}}


def test_main_writes_the_extended_copy_and_its_hash(tmp_path, monkeypatch, capsys):
    from portfolio.target_weights import load_weight_file, write_weight_file

    import v650_lean
    import v650_research

    module = load_script("extend_frozen_weights")
    source = tmp_path / "frozen.csv"
    write_weight_file({"2024-01-02": {"BTCUSD": 0.1}}, source)
    definition = tmp_path / "definition.json"
    definition.write_text(json.dumps({"history_start": "2023-07-01", "phase_index": 2}), encoding="utf-8")
    seen = {}
    monkeypatch.setattr(v650_research, "load_context", lambda: "context")
    monkeypatch.setattr(v650_lean, "candidate_rows", lambda definition, context, start, end, phase_index: seen.update(start=start, end=end, phase=phase_index) or {"2024-01-09": {"BTCUSD": 0.2}})
    out = tmp_path / "forward.csv"
    assert module.main(["--definition", str(definition), "--source", str(source), "--out", str(out), "--end", "2024-02-01"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["added"] == 1 and printed["last_row"] == "2024-01-09" and seen == {"start": "2023-07-01", "end": "2024-02-01", "phase": 2}
    assert load_weight_file(out)["2024-01-09"] == {"BTCUSD": 0.2}


def test_it_refuses_to_overwrite_the_frozen_file(tmp_path, capsys):
    module = load_script("extend_frozen_weights")
    frozen = tmp_path / "frozen.csv"
    with pytest.raises(SystemExit):
        module.main(["--definition", "d.json", "--source", str(frozen), "--out", str(frozen), "--end", "2024-02-01"])
    assert "never the frozen file" in capsys.readouterr().err
