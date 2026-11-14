"""aq evaluate's research and audit flags (V6.6.6, #359): each runner is a stand-in; the test checks the exit code, the summary and the file written."""

from __future__ import annotations

import argparse
import json

import pandas as pd

import aq_cli
from test_aq_cli_evaluate_lean import env, ns  # noqa: F401  (the fixture and the namespace builder)


def test_the_research_flags_write_one_json_each_and_need_their_inputs(env, monkeypatch, capsys):
    from evaluation import research_runners

    monkeypatch.setattr(research_runners, "run_audit_leakage", lambda dataset: {"flag": "leakage"})
    monkeypatch.setattr(research_runners, "run_overfit_report", lambda: {"flag": "overfit"})
    monkeypatch.setattr(research_runners, "run_pbo", lambda path: {"flag": "pbo", "path": path.name})
    monkeypatch.setattr(research_runners, "run_factor_spanning", lambda path, dataset, split: {"flag": "spanning", "split": split})
    monkeypatch.setattr(research_runners, "run_sim_lean_gap", lambda path: {"flag": "gap"})
    assert aq_cli.cmd_evaluate(ns(audit_leakage=True, overfit_report=True, pbo=True, trial_returns=None)) == 0
    text = capsys.readouterr().out
    assert "audit_leakage: wrote" in text and "pbo: wrote" in text
    assert json.loads((env.out / "pbo.json").read_text(encoding="utf-8"))["path"] == "trial_returns.parquet"
    assert aq_cli.cmd_evaluate(ns(factor_spanning=True)) == 1 and "needs --signal" in capsys.readouterr().err
    assert aq_cli.cmd_evaluate(argparse.Namespace(json=True, factor_spanning=True, signal="s.csv")) == 0
    assert '"split": "backtest"' in capsys.readouterr().out
    assert aq_cli.cmd_evaluate(ns(calibrate_sim_lean=True)) == 1 and "needs --calibration-file" in capsys.readouterr().err
    assert aq_cli.cmd_evaluate(ns(calibrate_sim_lean=True, calibration_file="c.json")) == 0 and (env.out / "sim_lean_gap.json").exists()


def test_every_v580_audit_prints_its_summary_or_json(env, monkeypatch, capsys):
    from evaluation import audit_runners

    within = {"mean_ic": 0.01, "hac_t": 1.5, "num_dates": 40}
    monkeypatch.setattr(audit_runners, "run_ic_by_class", lambda config, split, dataset_path: {
        "split": split, "rows": 10, "heads": {"rank_20d": {"pooled": within, "between": within, "class_share_of_pooled": 0.4, "within": {"equity": within}}}})
    monkeypatch.setattr(audit_runners, "run_audit_gates", lambda config, split, dataset_path: {
        "split": split, "num_vetoed": 1, "num_decisions": 4, "veto_share": 0.25, "num_false_vetoes": 0, "false_veto_share_of_vetoes": 0.0, "resolved_gate_veto_share": 0.1,
        "state_vs_resolved_correlation": 0.9, "state_minus_resolved_mean_gap": 0.0, "mean_forward_ic_all": 0.02, "mean_forward_ic_vetoed": 0.0})
    monkeypatch.setattr(audit_runners, "run_audit_data", lambda config, data_root: {"data_root": str(data_root), "num_assets": 2, "flagged": ["AAA"], "assets": {"AAA": {"problems": ["gap"]}}})
    monkeypatch.setattr(audit_runners, "run_audit_heads", lambda config: {
        "num_passed": 1, "num_components": 2, "rows": [{"passed": True, "component": "a", "metric": "ic", "value": 0.1, "in_decision_path": True}, {"passed": False, "component": "b", "metric": "ic", "value": -0.1, "in_decision_path": False}],
        "failing_in_decision_path": [], "rank_signal_policy": {"demotion_fallback": True, "failed_heads": ["x"], "heads": {"a": 1}}})
    monkeypatch.setattr(audit_runners, "run_audit_features", lambda config, dataset_path, permutation: {"features": ["a"], "flags": {"ticker_id_suspects": [], "constant_for_class": {"bond": ["a"]}, "ic_sign_unstable": []}})
    flags = dict(ic_by_class=True, audit_gates=True, audit_data=True, audit_heads=True, audit_features=True)
    assert aq_cli.cmd_evaluate(ns(**flags, split="validation", data_root=str(env.root / "d"))) == 0
    text = capsys.readouterr().out
    for fragment in ("Class IC audit", "Gate audit", "Data audit", "Head audit: 1/2", "WARNING rank signal", "Feature audit", "constant for bond"):
        assert fragment in text, fragment
    assert (env.out / "class_ic_audit_validation.json").exists() and (env.out / "gate_audit.json").exists() and env.refreshed
    assert aq_cli.cmd_evaluate(argparse.Namespace(json=True, audit_heads=True)) == 0
    printed = capsys.readouterr().out
    assert '"num_passed": 1' in printed and '"rows"' not in printed


def test_the_fill_price_audit_compares_every_fill_with_two_opens(env, monkeypatch, capsys):
    import evaluation.backtest_audit as audit
    import evaluation.fill_price_audit as fills

    dataset = env.root / "full.csv"
    pd.DataFrame({"ticker": ["AAA", "BBB"], "date": ["2025-01-02 00:00", "2025-01-03"], "open": [10.0, 20.0]}).to_csv(dataset, index=False)
    seen = {}
    result = {"num_fills": 2, "fill_vs_dataset_open": {"fills_without_reference": 0, "groups": {"equity": {"mean_bps": 1}}},
              "fill_vs_zip_open": {"fills_without_reference": 1, "groups": {}}, "dataset_open_vs_zip_open_on_traded_dates": {"max_gap_bps": 0}}
    monkeypatch.setattr(audit, "load_backtest_run", lambda run_dir: {})
    monkeypatch.setattr(fills, "audit_fills", lambda run, opens, data: seen.update(opens=opens) or dict(result))
    args = ns(audit_fills=True, backtest_dir=str(env.run), dataset=str(dataset))
    assert aq_cli.cmd_evaluate(args) == 0
    assert seen["opens"] == {("AAA", "2025-01-02"): 10.0, ("BBB", "2025-01-03"): 20.0} and "Fill price audit" in capsys.readouterr().out and env.refreshed
    assert aq_cli.cmd_evaluate(argparse.Namespace(json=True, audit_fills=True, backtest_dir=str(env.run), dataset=str(dataset))) == 0
    assert '"num_fills": 2' in capsys.readouterr().out
    monkeypatch.setattr(audit, "load_backtest_run", lambda run_dir: (_ for _ in ()).throw(FileNotFoundError("no results")))
    assert aq_cli.cmd_evaluate(args) == 1
    assert aq_cli.cmd_evaluate(ns(audit_fills=True, backtest_dir=str(env.root / "none"))) == 1


def test_the_walk_forward_summary_is_read_by_id_or_newest(env, monkeypatch, capsys):
    versions = env.root / "ml" / "versions"
    assert aq_cli.cmd_evaluate(ns(walk_forward_summary=True)) == 1 and "no walk-forward summary" in capsys.readouterr().err
    for name, windows in (("walk-forward-old", 1), ("walk-forward-new", 3)):
        folder = versions / name
        folder.mkdir(parents=True)
        (folder / "walk_forward_summary.json").write_text(json.dumps({
            "num_windows": windows, "summary_by_metric": {"ic": {"cross_window_bootstrap": {"mean_ic": 0.03, "lower_bound": 0.0, "upper_bound": 0.06}}},
            "stability_by_metric": {"ic": {"stable": False, "sign_flip_fraction": 0.5, "num_windows": windows}}, "net_performance_by_window": [{"w": 1}]}), encoding="utf-8")
    import os

    os.utime(versions / "walk-forward-old" / "walk_forward_summary.json", (1, 1))
    assert aq_cli.cmd_evaluate(ns(walk_forward_summary=True)) == 0
    text = capsys.readouterr().out
    assert "walk-forward-new" in text and "UNSTABLE" in text and "1 window(s) with a simulated book" in text
    assert aq_cli.cmd_evaluate(argparse.Namespace(json=True, walk_forward_summary=True, run_id="walk-forward-old")) == 0
    assert json.loads(capsys.readouterr().out)["num_windows"] == 1
    assert aq_cli.cmd_evaluate(ns(walk_forward_summary=True, run_id="missing")) == 1
    assert env.refreshed, "a summary that was read refreshes the README blocks"
