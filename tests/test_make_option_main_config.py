"""scripts/lean_smoke/make_option_main_config.py (V6.6.6): the option smoke config from the shipped one, per scenario."""

from __future__ import annotations

import json

import pytest

from script_loader import ROOT, load_script


@pytest.mark.parametrize("scenario", [None, "scale", "assign", "arb"])
def test_the_config_keeps_the_option_universe_and_turns_on_what_the_scenario_needs(scenario):
    module = load_script("lean_smoke/make_option_main_config")
    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    config = module.option_main_config(base, scenario)
    tickers = [asset["ticker"] for asset in config["phase1"]["universe"]["assets"]]
    assert tickers[-1] == "AAPL_OPTION" and set(tickers[:-1]) <= set(module.KEEP)
    risk = config["phase_v2"]["options_risk"]
    assert risk["enabled"] and config["phase_v2"]["target_weights"]["enabled"] is False and config["runtime"]["lean_window_override"] == module.WINDOW
    if scenario == "scale":
        assert risk["max_positions_per_underlying"] == 1
    else:
        assert risk["max_positions_per_underlying"] == base["phase_v2"]["options_risk"]["max_positions_per_underlying"]
    assert risk["assignment_risk_detector"]["enabled"] is (scenario == "assign" or base["phase_v2"]["options_risk"]["assignment_risk_detector"]["enabled"])


def test_main_writes_the_file(tmp_path, monkeypatch, capsys):
    module = load_script("lean_smoke/make_option_main_config")
    out = tmp_path / "option.json"
    monkeypatch.setattr(module.sys if hasattr(module, "sys") else __import__("sys"), "argv", ["x", "--out", str(out), "--scenario", "scale"])
    assert module.main() == 0
    assert json.loads(out.read_text(encoding="utf-8"))["phase_v2"]["options_risk"]["max_positions_per_underlying"] == 1 and str(out) in capsys.readouterr().out
