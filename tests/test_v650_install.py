"""scripts/v650_install.py (V6.6.6): installs only the verdict's winner, from the median phase, and only the frozen weights."""

from __future__ import annotations

import hashlib
import json

import pytest

from script_loader import Stop, load_script, run_script, stop_at_first_read


def _tree(tmp_path, *, install="t3", weights=b"date,BTCUSD\n2024-01-02,0.1\n", tamper=False):
    v650 = tmp_path / "ml" / "evaluation" / "v650"
    v650.mkdir(parents=True)
    phases = {"p0": {"strategy_sharpe": 0.9, "run": "run_hi"}, "p1": {"strategy_sharpe": 0.5, "run": "run_mid"}, "p2": {"strategy_sharpe": 0.1, "run": "run_lo"}}
    (v650 / "r_lean19.json").write_text(json.dumps({"verdict": {"install": install}, "detail": {"t3": {"phases": phases}}}), encoding="utf-8")
    (tmp_path / "ml" / "frozen.csv").write_bytes(weights)
    digest = hashlib.sha256(weights).hexdigest()
    config = {"phase_v2": {"target_weights": {"weights_path": "ml/frozen.csv", "weights_sha256": "0" * 64 if tamper else digest}}, "runtime": {"lean_window_override": ["a", "b"]}}
    (tmp_path / "ml" / "evaluation" / "run_configs").mkdir()
    (tmp_path / "ml" / "evaluation" / "run_configs" / "run_mid.json").write_text(json.dumps(config), encoding="utf-8")
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    return tmp_path


def _module(monkeypatch, root):
    module = load_script("v650_install")
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "V650", root / "ml" / "evaluation" / "v650")
    return module


def test_the_median_phase_is_installed_with_its_frozen_weights(tmp_path, monkeypatch, capsys):
    root = _tree(tmp_path)
    module = _module(monkeypatch, root)
    assert module.median_phase({"a": {"strategy_sharpe": 2}, "b": {"strategy_sharpe": 1}, "c": {"strategy_sharpe": 3}}) == "a"
    assert module.main() == 0
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    assert config["phase_v2"]["target_weights"]["weights_path"] == "ml/target_weights.csv" and config["runtime"]["lean_window_override"] is None
    assert (root / "ml" / "target_weights.csv").read_bytes() == (root / "ml" / "frozen.csv").read_bytes()
    candidate = json.loads((root / "ml" / "target_weights_candidate.json").read_text(encoding="utf-8"))
    assert candidate == {"survivors": ["t3"], "method": None, "phase_index": 1, "history_start": "2023-07-01", "pinned_run": "run_mid"}
    assert json.loads(capsys.readouterr().out)["phase"] == "p1"


def test_it_refuses_no_winner_and_unfrozen_weights(tmp_path, monkeypatch, capsys):
    module = _module(monkeypatch, _tree(tmp_path / "a", install=None))
    assert module.main() == 1 and "installs nothing" in capsys.readouterr().err
    module = _module(monkeypatch, _tree(tmp_path / "b", tamper=True))
    assert module.main() == 1 and "not the file the run froze" in capsys.readouterr().err
    assert json.loads((tmp_path / "b" / "config.json").read_text(encoding="utf-8")) == {}


def test_run_as_a_script_it_stops_at_its_first_read(monkeypatch):
    stop_at_first_read(monkeypatch)
    with pytest.raises(Stop, match="r_lean19.json"):
        run_script("v650_install", [], monkeypatch)
