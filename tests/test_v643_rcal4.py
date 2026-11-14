"""scripts/v643_rcal4.py (V6.6.6): R-CAL4's clauses, and the run over BT5/BT7/BT8 with a stand-in calibration ladder."""

from __future__ import annotations

import json

from script_loader import fake_module, load_script, run_script


def test_the_verdict_adopts_only_a_bt5_gain_that_bt7_and_bt8_keep():
    module = load_script("v643_rcal4")
    base = {"bt5": 0.80, "bt7": 0.85, "bt8": 0.88}
    adopted = module.verdict(base, {"bt5": 0.91, "bt7": 0.92, "bt8": 0.95})
    assert adopted["adopted"] is True and adopted["branch"] == "A"
    rejected = module.verdict(base, {"bt5": 0.82, "bt7": 0.90, "bt8": None})
    assert rejected["adopted"] is False and rejected["gains"]["bt8"] is None and rejected["branch"] == "B"


def test_main_scores_every_window_and_writes_the_result(tmp_path, monkeypatch, capsys):
    module = load_script("v643_rcal4")
    calibration = {"windows": {name: {"variants": {"calibrated": {"daily_correlation": 0.8}}} for name in module.WINDOWS}}
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(calibration), encoding="utf-8")
    fake_module(
        monkeypatch, "lean_calibration", BOOK_COMPONENTS="components", parse_window=lambda text: text,
        run_window=lambda window, dataset, config, components, extra_ladder: {"variants": {module.CANDIDATE: {"daily_correlation": 0.9, "disagreement": [1]}}},
    )
    import evaluation.sim_lean_calibration as calibration_module

    monkeypatch.setattr(calibration_module, "gap_report", lambda payload: {"gap": 1})
    out = tmp_path / "result.json"
    monkeypatch.setattr(module.sys, "argv", ["x", "--calibration", str(path), "--out", str(out)])
    assert module.main() == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["adopted"] is True and "disagreement" not in result["candidate_rows"]["bt5"] and result["gap_report"] == {"gap": 1}
    assert "R-CAL4:" in capsys.readouterr().out


def test_help_runs_as_a_script(monkeypatch, capsys):
    fake_module(monkeypatch, "lean_calibration", BOOK_COMPONENTS=None, parse_window=None, run_window=None)
    assert run_script("v643_rcal4", ["--help"], monkeypatch) == 0
    assert "--calibration" in capsys.readouterr().out
