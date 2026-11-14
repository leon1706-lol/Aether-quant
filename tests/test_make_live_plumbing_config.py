"""scripts/lean_smoke/make_live_plumbing_config.py and make_field_test_config.py (V6.6.6): the launcher config on Lean's
fake data queue, and each project config, written by their command lines."""

from __future__ import annotations

import json

from script_loader import ROOT, load_script, run_script


def _files(tmp_path):
    lean = tmp_path / "lean.json"
    lean.write_text(json.dumps({"job-user-id": "1", "environments": {"live-paper": {"live-mode-brokerage": "PaperBrokerage", "data-queue-handler": ["x"]}}}), encoding="utf-8")
    project = tmp_path / "project_config.json"
    project.write_text((ROOT / "config.json").read_text(encoding="utf-8"), encoding="utf-8")
    return lean, project


def test_the_launcher_runs_on_the_fake_queue_and_the_project_is_trimmed(tmp_path, monkeypatch, capsys):
    lean, project = _files(tmp_path)
    out = tmp_path / "launcher.json"
    assert run_script("lean_smoke/make_live_plumbing_config", ["--lean-json", str(lean), "--out", str(out), "--project-config", str(project)], monkeypatch) == 0
    launcher = json.loads(out.read_text(encoding="utf-8"))
    assert launcher["data-queue-handler"] == [load_script("lean_smoke/make_live_plumbing_config").FAKE_QUEUE] and launcher["job-user-id"] == "1"
    trimmed = json.loads(project.read_text(encoding="utf-8"))
    assert trimmed["runtime"]["mode"] == "paper" and {asset["ticker"] for asset in trimmed["phase1"]["universe"]["assets"]} <= {"BTCUSD", "ETHUSD", "SOLUSD", "SPY", "TLT"}
    assert "trimmed" in capsys.readouterr().out


def test_the_field_test_project_turns_on_the_plan_on_two_coins(tmp_path, monkeypatch, capsys):
    lean, project = _files(tmp_path)
    out = tmp_path / "launcher.json"
    assert run_script("lean_smoke/make_field_test_config", ["--lean-json", str(lean), "--out", str(out), "--project-config", str(project)], monkeypatch) == 0
    config = json.loads(project.read_text(encoding="utf-8"))
    assert [asset["ticker"] for asset in config["phase1"]["universe"]["assets"]] == ["BTCUSD", "ETHUSD"]
    assert config["phase_v2"]["diagnostics"]["field_test"]["enabled"] is True and config["phase_v2"]["runtime"] == {"mode": "paper", "allow_live_orders": True}
    assert out.exists() and "field-test project config" in capsys.readouterr().out
