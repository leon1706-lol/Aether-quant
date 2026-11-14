"""scripts/v661_glide.py (V6.6.6): R-GLIDE1 and R-GLIDE2 are written once, run only on their recorded hash, and write the
chosen policy into policy.json. The Monte Carlo itself is a stand-in here (evaluation.glide_calibration has its own tests)."""

from __future__ import annotations

import json
import shutil

import pytest

from script_loader import ROOT, load_script, run_script


@pytest.fixture
def glide(tmp_path, monkeypatch):
    module = load_script("v661_glide")
    out = tmp_path / "generations"
    out.mkdir()
    shutil.copyfile(ROOT / "ml" / "generations" / "policy.json", out / "policy.json")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "OUT", out)
    monkeypatch.setattr(module, "RULES", out / "rules_glide1.json")
    monkeypatch.setattr(module, "RULES2", out / "rules_glide2.json")
    results = {"fixed_252": {"median_regret": 0.2, "zero_alpha_majority_share": 0.1, "mean_holders": 1.0, "turnover_per_year": 0.5},
               "dyn_a": {"median_regret": 0.1, "zero_alpha_majority_share": 0.1, "mean_holders": 2.0, "turnover_per_year": 1.0}}
    monkeypatch.setattr(module, "evaluate_policies", lambda configs, policies, paths, seed, years, workers=1: results)
    return module, out


def _policy(out):
    return json.loads((out / "policy.json").read_text(encoding="utf-8"))


def test_glide1_is_written_once_and_run_on_its_hash(glide, monkeypatch, capsys):
    module, out = glide
    assert module.stage_rules() == 0
    with pytest.raises(SystemExit, match="written once"):
        module.stage_rules()
    payload = json.loads(module.RULES.read_text(encoding="utf-8"))
    name = next(policy["name"] for policy in payload["policies"] if "glide_sessions" in policy)
    monkeypatch.setattr(module, "pick_policy", lambda results, max_zero_alpha_share, tie: {"policy": name})
    assert module.stage_run(10) == 0
    assert _policy(out)["glide_policy"] == name and json.loads((out / "glide_policy.json").read_text(encoding="utf-8"))["paths_requested"] == 10
    monkeypatch.setattr(module, "pick_policy", lambda results, max_zero_alpha_share, tie: {"policy": "not_listed"})
    assert module.stage_run(10) == 0 and _policy(out)["glide_policy"] == "not_listed"
    assert "chosen: not_listed" in capsys.readouterr().out

    module.RULES.write_text(module.RULES.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(SystemExit, match="recorded hash"):
        module.stage_run(10)


def test_glide2_adopts_only_when_the_rule_says_so(glide, monkeypatch, capsys):
    module, out = glide
    assert module.stage_rules2() == 0
    with pytest.raises(SystemExit, match="written once"):
        module.stage_rules2()
    dynamic = next(entry for entry in json.loads(module.RULES2.read_text(encoding="utf-8"))["policies"] if "half_life_sessions" in entry)
    before = _policy(out)
    monkeypatch.setattr(module, "pick_glide2", lambda results, tie: {"policy": dynamic["name"], "adopted": False, "reason": "worse"})
    assert module.stage_run2(10, 1) == 0 and _policy(out)["glide"] == before["glide"]
    monkeypatch.setattr(module, "pick_glide2", lambda results, tie: {"policy": dynamic["name"], "adopted": True, "reason": "no worse"})
    assert module.stage_run2(10, 1) == 0
    policy = _policy(out)
    assert policy["glide"]["mode"] == "dynamic" and policy["glide_policy"] == dynamic["name"] and "adopted: True" in capsys.readouterr().out

    module.RULES2.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="recorded hash"):
        module.stage_run2(10, 1)


def test_decay_and_the_cli_dispatch(glide, monkeypatch, capsys):
    module, out = glide
    monkeypatch.setattr(module, "average_run_lengths", lambda expected_sharpe, decayed_sharpe, paths: {"from": expected_sharpe, "to": decayed_sharpe})
    monkeypatch.setattr(module.sys, "argv", ["x", "decay"])
    assert module.main() == 0
    report = json.loads((out.parent / "ml" / "evaluation" / "v661" / "decay_run_lengths.json").read_text(encoding="utf-8"))
    assert set(report) == {"1_to_0", "0.5_to_0", "0_to_-1"}
    calls = []
    monkeypatch.setattr(module, "stage_run", lambda paths: calls.append(("run", paths)) or 0)
    monkeypatch.setattr(module, "stage_run2", lambda paths, workers: calls.append(("run2", paths, workers)) or 0)
    for argv in (["run", "--paths", "7"], ["run2", "--paths", "3", "--workers", "2"]):
        monkeypatch.setattr(module.sys, "argv", ["x", *argv])
        assert module.main() == 0
    assert calls == [("run", 7), ("run2", 3, 2)]


def test_help_runs_as_a_script(monkeypatch, capsys):
    assert run_script("v661_glide", ["--help"], monkeypatch) == 0
    assert "rules2" in capsys.readouterr().out
