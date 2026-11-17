"""scripts/check_artifact_pins.py: a clean checkout passes, a matching set passes, a changed file fails (V6.6.9, #382)."""

from __future__ import annotations

from retraining.artifact_pins import write_artifact_pins
from script_loader import load_script, run_script


def _world(monkeypatch, tmp_path):
    module = load_script("check_artifact_pins")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / "ml").mkdir()
    return module


def test_a_checkout_without_models_has_nothing_to_check(monkeypatch, tmp_path, capsys):
    assert _world(monkeypatch, tmp_path).main() == 0
    assert "nothing to check" in capsys.readouterr().out


def test_a_set_that_matches_its_pins_passes_and_a_changed_file_fails(monkeypatch, tmp_path, capsys):
    module = _world(monkeypatch, tmp_path)
    ml = tmp_path / "ml"
    (ml / "sequence_model.json").write_text("{}", encoding="utf-8")
    (ml / "scaler_stats.json").write_text('{"mean": [0.0]}', encoding="utf-8")
    write_artifact_pins(ml, ml / "artifact_pins.json")
    assert module.main() == 0 and "match their pins" in capsys.readouterr().out
    (ml / "scaler_stats.json").write_text('{"mean": [1.0]}', encoding="utf-8")
    assert module.main() == 1
    captured = capsys.readouterr()
    assert "scaler_stats.json does not match its pin" in captured.err and "1 problem(s)" in captured.out


def test_run_as_a_script_it_checks_the_real_tree(monkeypatch):
    assert run_script("check_artifact_pins", [], monkeypatch) in (0, 1)
