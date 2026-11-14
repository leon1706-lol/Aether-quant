"""scripts/promotion_gate_null_calibration.py (V6.6.6): the IC t-stat and negative-era count of the real scores against
permuted targets, on a small synthetic dataset spanning the gate's named eras."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from script_loader import Stop, load_script, run_script
from test_promotion_gate_null_gate_scheme import _datasets


def test_the_null_and_the_real_figures_are_reported(tmp_path, monkeypatch, capsys):
    module = load_script("promotion_gate_null_calibration")
    _datasets(tmp_path)
    monkeypatch.setattr(module, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(module, "N_PERMS", 3)
    assert module.main() == 0
    summary = json.loads((tmp_path / "ml" / "evaluation" / "promotion_gate_null_calibration.json").read_text(encoding="utf-8"))
    assert summary["n_perms"] == 3 and summary["real"]["negative_eras"] >= 1
    assert summary["null_t_stat"]["p50"] <= summary["null_t_stat"]["max"] and isinstance(summary["null_negative_eras"]["observed_real_is_unusual"], bool)
    assert "REAL: t=" in capsys.readouterr().out


def test_too_few_dates_give_a_zero_t_stat(tmp_path, monkeypatch):
    module = load_script("promotion_gate_null_calibration")
    _datasets(tmp_path)
    monkeypatch.setattr(module, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(module, "N_PERMS", 1)
    monkeypatch.setattr(module, "STRIDE", 10_000)
    assert module.main() == 0
    assert json.loads((tmp_path / "ml" / "evaluation" / "promotion_gate_null_calibration.json").read_text(encoding="utf-8"))["real"]["t_stat"] == 0.0


def test_run_as_a_script_it_stops_at_its_first_read(monkeypatch):
    def stop(path, *args, **kwargs):
        raise Stop(str(path))

    monkeypatch.setattr(pd, "read_csv", stop)
    with pytest.raises(Stop, match="full_dataset.csv"):
        run_script("promotion_gate_null_calibration", [], monkeypatch)
