"""evaluation/readme_research.py: the README blocks for the as-live book and the V5.8.0 research results."""

from __future__ import annotations

import json
from pathlib import Path

from evaluation import readme_research as rr


def _write(directory: Path, name: str, payload: dict) -> None:
    (directory / name).write_text(json.dumps(payload), encoding="utf-8")


def test_empty_directory_degrades_to_not_run_lines(tmp_path):
    assert "Not run yet" in rr.build_as_live_markdown(tmp_path)
    research = rr.build_research_markdown(tmp_path)
    assert research.count("Not run yet") >= 5
    assert "|" not in research.split("**Where the rank edge sits**")[0].split("minimum cap with a loss guard")[1]


def test_as_live_table_has_one_row_per_split(tmp_path):
    for split, sharpe in (("validation", 0.05), ("backtest", 1.18)):
        _write(tmp_path, f"rank_book_simulation_as_live_{split}.json", {
            "split": split, "idealized_net_sharpe": 0.5,
            "as_live": {"net_sharpe": sharpe, "net_total_return": 0.1, "net_max_drawdown": -0.05, "num_rebalances": 90, "num_vetoed_rebalances": 3},
        })
    text = rr.build_as_live_markdown(tmp_path)
    assert "| validation |" in text and "| backtest |" in text and "+1.180" in text and "+0.050" in text


def test_legacy_unsuffixed_file_is_placed_by_its_split_key(tmp_path):
    _write(tmp_path, "rank_book_simulation_as_live.json", {"split": "backtest", "as_live": {"net_sharpe": 0.7}})
    text = rr.build_as_live_markdown(tmp_path)
    assert "| backtest |" in text and "| validation | not run |" in text


def test_sleeve_rows_follow_the_branch(tmp_path):
    grid = {"carry k=2": {"validation": {"net_sharpe": 0.4}, "backtest": {"net_sharpe": -0.1}, "combined_backtest_drop": 0.09}}
    _write(tmp_path, "class_sleeve_research_forex.json", {"grid": grid, "decision": {"branch": "trade_anyway_minimum_cap", "variant": "carry k=2"}})
    _write(tmp_path, "class_sleeve_research_bond.json", {"grid": grid, "decision": {"branch": "edge_pass", "variant": "carry k=2"}})
    _write(tmp_path, "crypto_graduation_research.json", {
        "decision": {"branch": "trade_anyway_minimum_cap", "per_name_cap": 0.01, "class_gross_cap": 0.05},
        "results": {"core_only": {"backtest": {"net_sharpe": 0.7}}, "capped 0.01/0.05": {"validation": {"net_sharpe": 0.3}, "backtest": {"net_sharpe": 0.71}}},
    })
    _write(tmp_path, "rl_sizing_research.json", {
        "decision": {"branch": "trade_anyway_minimum_range", "range": [0.9, 1.1], "shadow_guard": True},
        "splits": {"validation": {"minimum_range_with_shadow_guard": {"sharpe_gain": -0.02}}, "backtest": {"minimum_range_with_shadow_guard": {"sharpe_gain": 0.03}}},
    })
    text = rr.build_research_markdown(tmp_path)
    assert "gross 0.10 (minimum cap; best effort: carry k=2)" in text
    assert "| Bond sleeve | edge_pass | carry k=2 |" in text
    assert "per-name 0.01, class gross 0.05 (minimum cap + loss guard)" in text and "-0.010" in text
    assert "range [0.9, 1.1] + shadow guard | -0.020 (gain) | +0.030 (gain)" in text


def test_a_lean_override_replaces_the_offline_branch_and_names_both(tmp_path):
    grid = {"carry k=2": {"validation": {"net_sharpe": 0.4}, "backtest": {"net_sharpe": 0.2}, "combined_backtest_drop": 0.0}}
    _write(tmp_path, "class_sleeve_research_bond.json", {"grid": grid, "decision": {"branch": "edge_pass", "variant": "carry k=2"}})
    _write(tmp_path, "lean_decision_overrides.json", {"Bond sleeve": {"branch": "lean_override_minimum_cap", "shipped": "gross 0.10 after BT1"}})
    text = rr.build_research_markdown(tmp_path)
    assert "| Bond sleeve | lean_override_minimum_cap (offline: edge_pass) | gross 0.10 after BT1 |" in text


def test_lean_vs_offline_table_puts_the_engine_run_next_to_the_offline_books_and_benchmarks(tmp_path):
    assert "Not run yet" in rr.build_lean_vs_offline_markdown(tmp_path)
    _write(tmp_path, "backtest_audit.json", {"run_id": "R1", "periods": [
        {"start": "2023-07-01", "end": "2025-06-30", "sharpe_no_risk_free": 0.137, "net_return": 0.0104, "max_drawdown": -0.0359},
        {"start": "2025-07-01", "end": "2026-09-30", "sharpe_no_risk_free": -0.397, "net_return": -0.0161, "max_drawdown": -0.0385},
    ]})
    _write(tmp_path, "rank_book_simulation_as_live_backtest.json", {
        "idealized_net_sharpe": -0.72, "idealized_net_total_return": -0.0753,
        "as_live": {"net_sharpe": 0.62, "net_total_return": 0.0595, "net_max_drawdown": -0.0443},
    })
    _write(tmp_path, "benchmark_comparison.json", {"baselines": [
        {"strategy": "sp500", "net_sharpe": 0.882, "total_return_pct": 23.52},
        {"strategy": "60_40", "net_sharpe": 0.895, "total_return_pct": 18.06},
    ]})
    _write(tmp_path, "holdout_report.json", {
        "first_date": "2025-07-01",
        "as_live_book": {"net_sharpe": -0.59, "net_total_return": -0.024, "net_max_drawdown": -0.043},
        "idealized_book": {"net_sharpe": -0.81, "net_total_return": -0.061, "net_max_drawdown": -0.129},
    })
    text = rr.build_lean_vs_offline_markdown(tmp_path)
    backtest_block, holdout_block = text.split("**Holdout")
    assert "Lean run `R1`" in backtest_block and "+0.137" in backtest_block and "+1.04%" in backtest_block
    assert "Offline as-live book | +0.620" in backtest_block and "S&P 500 buy and hold | +0.882 | +23.52%" in backtest_block
    assert "Lean run `R1`" in holdout_block and "-0.397" in holdout_block and "-0.590" in holdout_block
    assert "S&P" not in holdout_block  # no benchmark was computed for the holdout


def test_audit_blocks_render_numbers(tmp_path):
    _write(tmp_path, "class_ic_audit_backtest.json", {"split": "backtest", "heads": {"target_return_20d": {
        "pooled": {"mean_ic": 0.06, "hac_t": 2.3}, "between": {"mean_ic": 0.04},
        "within": {"equity": {"mean_ic": 0.062, "hac_t": 1.7}}}}})
    _write(tmp_path, "gate_audit_backtest.json", {"split": "backtest", "num_decisions": 499, "veto_share": 0.25,
                                                  "false_veto_share_of_vetoes": 0.82, "mean_forward_ic_vetoed": 0.156, "mean_forward_ic_all": 0.095})
    _write(tmp_path, "head_audit.json", {"num_passed": 18, "num_components": 27, "failing_in_decision_path": ["gating"]})
    _write(tmp_path, "holdout_report.json", {"first_date": "2025-07-01", "last_date": "2026-09-30", "tickers": 104,
                                             "as_live_book": {"net_sharpe": 0.4, "net_total_return": 0.05, "net_max_drawdown": -0.03,
                                                              "num_rebalances": 300, "num_vetoed_rebalances": 20},
                                             "idealized_book": {"net_sharpe": 0.5}})
    text = rr.build_research_markdown(tmp_path)
    assert "equity +0.062 (t 1.70)" in text and "+0.060 (t 2.30)" in text
    assert "| backtest | 499 | 25% | 82% | +0.156 | +0.095 |" in text
    assert "**18/27**" in text and "`gating`" in text
    assert "2025-07-01 .. 2026-09-30" in text and "20/300" in text


def test_nan_and_garbage_values_render_as_na(tmp_path):
    _write(tmp_path, "head_audit.json", {"num_passed": None, "num_components": "x"})
    assert "n/a" in rr._num(float("nan")) and rr._pct(None) == "n/a"
    assert "head_audit" not in rr.build_research_markdown(tmp_path)  # renders, never raises


def test_markers_exist_in_the_readme_exactly_once():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    for marker in (rr.AS_LIVE_MARKER_START, rr.AS_LIVE_MARKER_END, rr.RESEARCH_MARKER_START, rr.RESEARCH_MARKER_END,
                   rr.LEAN_COMPARE_MARKER_START, rr.LEAN_COMPARE_MARKER_END,
                   "<!-- AQ:BACKTEST_HISTORY_START -->", "<!-- AQ:BACKTEST_HISTORY_END -->"):
        assert readme.count(marker) == 1, marker


def test_generator_fills_the_new_blocks_in_a_scratch_readme(tmp_path, monkeypatch):
    import generate_evaluation_report as ger

    _write(tmp_path, "head_audit.json", {"num_passed": 5, "num_components": 6, "failing_in_decision_path": []})
    monkeypatch.setattr(ger, "EVALUATION_DIR", tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text(f"{rr.AS_LIVE_MARKER_START}\nx\n{rr.AS_LIVE_MARKER_END}\n{rr.RESEARCH_MARKER_START}\nx\n{rr.RESEARCH_MARKER_END}\n", encoding="utf-8")
    assert ger.update_readme_evaluation_sections(readme) is True
    text = readme.read_text(encoding="utf-8")
    assert "**5/6**" in text and "Not run yet" in text and "\nx\n" not in text


def test_topology_row_reports_the_branch_and_the_on_minus_off_sharpe(tmp_path):
    _write(tmp_path, "topology_sizing_research.json", {
        "decision": {"branch": "keep_on", "topology_learning_enabled": True},
        "results": {"on_mid": {"validation": {"net_sharpe": 0.30}, "backtest": {"net_sharpe": 1.10}},
                    "off": {"validation": {"net_sharpe": 0.25}, "backtest": {"net_sharpe": 1.20}}},
    })
    text = rr.build_research_markdown(tmp_path)
    assert "| Learned topology | keep_on | learned topology ON (shrink-only 0.5..1.0) | +0.050 (ON mid vs OFF) | -0.100 (ON mid vs OFF) |" in text


def _write_json(path, payload):
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_v6_rows_show_the_shipped_config_not_text_typed_in_the_builder(tmp_path):
    from evaluation.readme_research import build_research_markdown

    evaluation = tmp_path / "ml" / "evaluation"
    _write_json(tmp_path / "config.json", {"phase_v2": {
        "forex_risk": {"enabled": False},
        "class_weight_caps": {"crypto": {"per_name_cap": 0.004, "class_gross_cap": 0.02}},
        "limit_orders": {"exit_asset_classes": ["crypto"]},
    }})
    _write_json(evaluation / "v600" / "forex_research.json", {
        "grid": {"carry k=2": {"validation": {"net_sharpe": 0.45}, "backtest": {"net_sharpe": -0.17}}},
        "decision": {"branch": "drop", "best_validation_variant": "carry k=2"},
    })
    _write_json(evaluation / "v600" / "crypto_research.json", {
        "results": {"C5": {"validation": {"total_sharpe": -0.7}, "backtest": {"total_sharpe": -0.36}}},
        "decision": {"winner": "C5"},
    })
    markdown = build_research_markdown(evaluation)
    assert "| Forex sleeve | R-FX6: drop | off (`forex_risk.enabled` false" in markdown
    assert "per-name 0.004, class gross 0.02; limit exits for crypto" in markdown
    assert "0.10" not in markdown.split("Forex sleeve")[1].split("\n")[0]


def test_the_calibration_and_rule_chain_blocks_render_what_the_scripts_wrote(tmp_path):
    from evaluation.readme_research import build_research_markdown

    evaluation = tmp_path / "ml" / "evaluation"
    assert "Not run yet" in build_research_markdown(evaluation)
    _write_json(evaluation / "v610" / "calibration.json", {
        "verdict": {"variant": "v610", "branch": "B", "calibrated": False, "per_window": {"w1": False},
                    "thresholds": {"min_correlation": 0.5, "max_annual_gap": 0.02, "min_decision_agreement": 0.8}},
        "windows": {"w1": {"variants": {"v610": {"daily_correlation": 0.61, "annual_return_gap": -0.012, "decision_agreement": 0.7}}}},
    })
    _write_json(evaluation / "v610" / "research.json", {
        "book": {"variants": {"K1": {"verdict": {"ungated": {"backtest_gain": -0.2}}}}, "adopted": None},
        "gate": {"skipped": "R-CAL2 branch B: the gates stay frozen as safety controls"},
    })
    markdown = build_research_markdown(evaluation)
    assert "**branch B**" in markdown and "| w1 | 0.61 | -1.2% | 70% | fail |" in markdown
    assert "| book | none (incumbent stays) | K1 -0.200 |" in markdown
    assert "| gate | skipped | R-CAL2 branch B" in markdown


def test_the_v620_rule_chain_lists_each_rule_and_why_a_variant_failed(tmp_path):
    assert "Not run yet" in rr._rule_chain_v620_lines(tmp_path)[0]
    (tmp_path / "v620").mkdir()
    (tmp_path / "v620" / "research.json").write_text(json.dumps({
        "dedupe": {"adopted": False, "verdict": {"backtest_gain": -0.09, "validation_change": 0.575}},
        "stagger": {"adopted": None, "variants": {"S2": {"verdict": {
            "backtest_gain": 0.516, "validation_change": 0.259, "checks": {"backtest_gain_ge_0.10": True},
            "extra_checks": {"validation_phase_range_cut_ge_25pct": False}}}}},
        "model": {"adopted": None, "variants": {"v9_reg": {"skipped": "IC clauses failed"}}},
    }), encoding="utf-8")
    lines = "\n".join(rr._rule_chain_v620_lines(tmp_path))
    assert "none (double count stays)" in lines and "-0.090" in lines
    assert "S2: backtest +0.516" in lines and "fails validation_phase_range_cut_ge_25pct" in lines
    assert "1 candidates fail the IC clauses" in lines


def test_v630_rule_chain_names_branches_and_failed_clauses(tmp_path):
    import json as _json

    from evaluation.readme_research import _calibration_line, _rule_chain_v630_lines

    (tmp_path / "v630").mkdir()
    (tmp_path / "v630" / "research.json").write_text(_json.dumps({
        "kill": {"branch": "C", "adopted": None, "base": {"backtest": {"stability_jaccard_median": 0.62}},
                 "variants": {"KS2": {"verdict": {"backtest_gain": 0.03, "validation_change": -0.01,
                                                  "checks": {"backtest_gain_ge_0.10": False}},
                                      "extra_checks": {"stability_jaccard_ge_0.80": True}, "stability": 0.91}}},
        "stagger": {"adopted": False, "verdict": {"backtest_gain": 0.5, "validation_change": 0.2, "checks": {}},
                    "extra_checks": {"validation_iqr_widening_le_25pct": False}},
        "gates": {"skipped": "R-CAL3 branch B: the gates stay frozen as safety controls"},
    }), encoding="utf-8")
    text = "\n".join(_rule_chain_v630_lines(tmp_path))
    assert "branch C: none (KS0 stays)" in text and "KS0 lock stability 0.62" in text
    assert "KS2: backtest +0.030" in text and "fails backtest_gain_ge_0.10" in text
    assert "fails validation_iqr_widening_le_25pct" in text
    assert "| R-GATE3 (rolling-IC floor / window) | skipped |" in text
    (tmp_path / "v630" / "calibration.json").write_text(_json.dumps({
        "verdict": {"variant": "v610", "branch": "B", "calibrated": False, "per_window": {"w": False}, "thresholds": {}},
        "windows": {"w": {"variants": {"v610": {"daily_correlation": 0.7}}}},
    }), encoding="utf-8")
    assert _calibration_line(tmp_path).startswith("Rule R-CAL3")
