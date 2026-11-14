"""evaluation/readme_research.py and lean_verdict.py (V6.6.6, #359): the rule-chain tables from stored research JSON, and the verdict command."""

from __future__ import annotations

import json
import sys

import pytest

from evaluation import lean_verdict, readme_research


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_an_older_as_live_report_stands_in_for_an_unrecorded_split(tmp_path):
    _write(tmp_path / "rank_book_simulation_as_live.json", {"windows": []})
    text = readme_research.build_as_live_markdown(tmp_path)
    assert "older run, split not recorded" in text or "Not run yet" not in text


def test_the_v610_chain_names_skipped_variants_and_an_empty_chain(tmp_path):
    _write(tmp_path / "v610" / "research.json", {"model": {"variants": {"a": {"skipped": "no data"}, "b": {"verdict": {"ungated": {"backtest_gain": 0.1}}}}, "adopted": None}})
    lines = readme_research._rule_chain_lines(tmp_path)
    assert any("a skipped (no data)" in line for line in lines)
    _write(tmp_path / "v610" / "research.json", {"unrelated": 1})
    assert readme_research._rule_chain_lines(tmp_path) == ["_Rule chain has no stage results yet._"]


def test_the_v620_and_v630_chains_have_an_empty_state_and_a_gate_row(tmp_path):
    _write(tmp_path / "v620" / "research.json", {})
    assert readme_research._rule_chain_v620_lines(tmp_path) == ["_V6.2.0 rule chain has no stage results yet._"]
    _write(tmp_path / "v630" / "research.json", {})
    assert readme_research._rule_chain_v630_lines(tmp_path) == ["_V6.3.0 rule chain has no stage results yet._"]
    _write(tmp_path / "v630" / "research.json", {"gates": {"variants": {"g1": {"verdict": {"backtest_gain": 0.2}}}, "adopted": "g1"}})
    assert any("R-GATE3" in line and "g1" in line for line in readme_research._rule_chain_v630_lines(tmp_path))


def test_the_v640_chain_lists_the_third_lead_and_the_lean_rows(tmp_path):
    _write(tmp_path / "v640" / "research.json", {})
    assert readme_research._rule_chain_v640_lines(tmp_path) == ["_V6.4.0 rule chain has no stage results yet._"]
    report = {"l3": {"budgets": {"x": {"verdict": {"backtest_gain": 0.1}}}, "budget_adopted": None, "model": {"checks": {"c1": False}, "adopted": False}}}
    _write(tmp_path / "v640" / "research.json", report)
    lines = readme_research._rule_chain_v640_lines(tmp_path)
    assert any("L3a legacy budget" in line for line in lines) and any("L3b" in line and "fails c1" in line for line in lines)
    report["l3"]["model"] = {"reason": "why", "adopted": True}
    _write(tmp_path / "v640" / "research.json", report)
    assert any("v640_leg" in line and "why" in line for line in readme_research._rule_chain_v640_lines(tmp_path))
    _write(tmp_path / "v642" / "r_lean14_bt1.json", {"values": {"candidate_strategy_sharpe": 1.0}, "checks": {"a": True}, "keep": True, "candidate": "c", "baseline": "b"})
    _write(tmp_path / "v642" / "r_lean14_bt2.json", {"values": "not a mapping"})
    rows = readme_research._r_lean14_rows(tmp_path)
    assert len(rows) == 1 and "BT1" in rows[0]


def test_the_calibration_table_lists_each_head_and_its_best_method(tmp_path):
    _write(tmp_path / "v640" / "research.json", {"l2": {"chosen_head": "multitask", "heads": {"multitask": {"validation": {"ece": 0.04, "log_loss": 0.7, "cross_fitted_log_loss": {"raw": 0.7, "temperature": 0.65, "isotonic": None}},
                                                                                                    "backtest_raw_log_loss": 0.71, "backtest_calibrated_log_loss": 0.69, "backtest_balanced_accuracy": 0.52},
                                                                       "sequence": {}}}})
    lines = readme_research._l2_lines(tmp_path)
    assert any("multitask (used)" in line and "temperature" in line for line in lines) and any(line.startswith("| sequence") for line in lines)


def test_a_refresh_never_raises(monkeypatch, capsys):
    import generate_evaluation_report

    monkeypatch.setattr(generate_evaluation_report, "update_readme_evaluation_sections", lambda: True)
    assert readme_research.refresh_readme_best_effort() is True
    monkeypatch.setattr(generate_evaluation_report, "update_readme_evaluation_sections", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert readme_research.refresh_readme_best_effort() is False and "README refresh failed: boom" in capsys.readouterr().out


def test_the_verdict_loads_both_runs_and_judges_by_the_chosen_rule(tmp_path, monkeypatch):
    import evaluation.backtest_statistics as backtest_statistics

    (tmp_path / "candidate").mkdir()
    (tmp_path / "candidate" / "log.txt").write_text("teardown ok", encoding="utf-8")
    (tmp_path / "baseline").mkdir()
    monkeypatch.setattr(backtest_statistics, "compute_for_run_dir", lambda run_dir, config, root: {"run": str(run_dir)})
    monkeypatch.setattr(lean_verdict, "run_config", lambda run_dir, root, config: config)
    seen = []
    monkeypatch.setitem(lean_verdict.RULES, "non_inferiority", ("R-LEAN13", lambda baseline, candidate, log: seen.append(log) or {"keep": True}))
    monkeypatch.setitem(lean_verdict.RULES, "superiority", ("R-LEAN14", lambda baseline, candidate, log, margin: seen.append(margin) or {"keep": False}))
    kept = lean_verdict.verdict_for_run_dirs(tmp_path / "baseline", tmp_path / "candidate", {}, tmp_path, "non_inferiority", 0.1)
    assert kept["rule"] == "R-LEAN13" and kept["baseline"] == "baseline" and seen[0] == "teardown ok"
    lean_verdict.verdict_for_run_dirs(tmp_path / "candidate", tmp_path / "baseline", {}, tmp_path, "superiority", 0.1)
    assert seen[1] == 0.1


@pytest.mark.parametrize("keep,code", [(True, 0), (False, 1)])
def test_the_verdict_command_writes_and_exits_on_the_decision(tmp_path, monkeypatch, capsys, keep, code):
    monkeypatch.setattr(lean_verdict, "verdict_for_run_dirs", lambda *args: {"keep": keep})
    monkeypatch.setattr(sys, "argv", ["verdict"])
    assert lean_verdict.main(["--baseline", "backtests/a", "--candidate", "backtests/b", "--out", "ml/evaluation/test_verdict_tmp/out.json", "--rule", "superiority"]) == code
    out = lean_verdict.Path(lean_verdict.__file__).resolve().parents[1] / "ml" / "evaluation" / "test_verdict_tmp"
    assert json.loads((out / "out.json").read_text(encoding="utf-8")) == {"keep": keep} and '"keep"' in capsys.readouterr().out
    (out / "out.json").unlink()
    out.rmdir()
