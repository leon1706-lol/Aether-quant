"""aq evaluate's flags that read one finished Lean run (V6.6.6, #359): each flow with the evaluation function it calls stubbed,
checking what the command does with the answer: the exit code, what it prints and which file it writes."""

from __future__ import annotations

import argparse
import json
import shutil
from types import SimpleNamespace

import pytest

import aq_cli
from script_loader import ROOT


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A scratch root: config.json copied in, ml/evaluation and one run folder, with the README refresh turned off."""
    shutil.copyfile(ROOT / "config.json", tmp_path / "config.json")
    (tmp_path / "ml" / "evaluation").mkdir(parents=True)
    run = tmp_path / "backtests" / "2026-01-01_00-00-00"
    run.mkdir(parents=True)
    monkeypatch.setattr(aq_cli, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(aq_cli, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(aq_cli, "ML_DIR", tmp_path / "ml")
    refreshed = []
    monkeypatch.setattr(aq_cli, "_refresh_readme_evaluation_sections", lambda: refreshed.append(True))
    return SimpleNamespace(root=tmp_path, run=run, refreshed=refreshed, out=tmp_path / "ml" / "evaluation")


def ns(**flags) -> argparse.Namespace:
    return argparse.Namespace(json=False, **flags)


def test_an_unknown_preset_and_a_missing_run_are_clear_errors(env, capsys):
    assert aq_cli.cmd_evaluate(ns(preset="nope")) == 1 and "unknown preset" in capsys.readouterr().err
    for flag in ("lean_report", "alpha_proof", "backtest_stats", "classification_parity", "lean_monte_carlo", "attribute_lean", "audit_backtest"):
        assert aq_cli.cmd_evaluate(ns(**{flag: True, "backtest_dir": str(env.root / "backtests" / "missing")})) == 1, flag
        assert "no backtest folder found" in capsys.readouterr().err


def test_a_named_account_is_applied_to_the_config_first(env, monkeypatch):
    import execution.accounts_io as accounts_io

    seen = {}
    monkeypatch.setattr(accounts_io, "load_account_config", lambda config, account, root: seen.update(account=account) or config)
    assert aq_cli.cmd_evaluate(ns(account="desk", preset="nope")) == 1 and seen == {"account": "desk"}


def test_the_forward_ledger_is_judged_and_its_chain_decides_the_exit(env, monkeypatch, capsys):
    import evaluation.forward_ledger as forward

    rows = [{"payload": {"session": "2026-11-02"}}]
    monkeypatch.setattr(aq_cli, "_forward_ledger_rows", lambda args: rows)
    monkeypatch.setattr(forward, "judge_ledger", lambda rows, today_sessions: {"chain_valid": True, "missing": len(today_sessions) >= 0})
    assert aq_cli.cmd_evaluate(ns(forward_ledger=True)) == 0 and '"chain_valid": true' in capsys.readouterr().out
    monkeypatch.setattr(aq_cli, "_forward_ledger_rows", lambda args: [])
    monkeypatch.setattr(forward, "judge_ledger", lambda rows, today_sessions: {"chain_valid": False})
    assert aq_cli.cmd_evaluate(ns(forward_ledger=True)) == 1


def test_the_lean_report_runs_every_step_and_names_the_failures(env, monkeypatch, capsys):
    import evaluation.lean_report as lean_report
    import generate_backtest_report as report

    monkeypatch.setattr(lean_report, "lean_report_steps", lambda config: [("good", {"lean_report": False, "backtest_stats": True}), ("bad", {"lean_report": False, "alpha_proof": True}), ("broken", {"lean_report": False, "audit_backtest": True})])
    monkeypatch.setattr(report, "update_readme_from_latest_backtest", lambda backtest_dir: (_ for _ in ()).throw(RuntimeError("no readme")))
    real = aq_cli.cmd_evaluate
    outcomes = {"backtest_stats": 0, "alpha_proof": 1, "audit_backtest": RuntimeError("boom")}

    def step(args):
        flag = next(name for name in outcomes if getattr(args, name, False))
        if isinstance(outcomes[flag], BaseException):
            raise outcomes[flag]
        return outcomes[flag]

    first = {"lean_report": True, "backtest_dir": str(env.run)}
    monkeypatch.setattr(aq_cli, "cmd_evaluate", lambda args: real(args) if getattr(args, "lean_report", False) else step(args))
    assert real(ns(**first)) == 1
    captured = capsys.readouterr()
    assert "2 step(s) failed: bad, broken" in captured.out and "Lean headline refresh failed" in captured.err and "broken failed: boom" in captured.err


def test_alpha_proof_writes_its_report_in_json_or_text(env, monkeypatch, capsys):
    import evaluation.alpha_proof as alpha_proof
    import evaluation.backtest_statistics as statistics

    report = {"periods": {"full": {"n": 100, "sharpe": 0.5, "sharpe_ci95": [0.1, 0.9], "alpha": {"alpha_annual": 0.02, "t_hac": 1.1}, "dsr": 0.3}}, "r_alpha1": {"verdict": "not demonstrated", "failed": ["t"]}}
    monkeypatch.setattr(alpha_proof, "alpha_proof_report", lambda *args, **kwargs: dict(report))
    monkeypatch.setattr(statistics, "load_trial_sharpes", lambda path: {})
    monkeypatch.setattr(aq_cli, "_phase_deflation_inputs", lambda: None)
    assert aq_cli.cmd_evaluate(ns(alpha_proof=True, backtest_dir=str(env.run))) == 0
    text = capsys.readouterr().out
    assert "R-ALPHA1: not demonstrated" in text and (env.out / "alpha_proof.json").exists() and (env.out / f"alpha_proof_{env.run.name}.json").exists()
    assert aq_cli.cmd_evaluate(argparse.Namespace(json=True, alpha_proof=True, backtest_dir=str(env.run))) == 0
    assert json.loads(capsys.readouterr().out)["r_alpha1"]["verdict"] == "not demonstrated"


def test_backtest_stats_reports_sections_or_a_missing_file(env, monkeypatch, capsys):
    import evaluation.backtest_statistics as statistics

    monkeypatch.setattr(statistics, "compute_for_run_dir", lambda run_dir, config, root: {"status": "ok", "sections": {"General": [{"metric": "Sharpe", "portfolio": 0.6}], "Empty": [], "Text": "x"}})
    assert aq_cli.cmd_evaluate(ns(backtest_stats=True, backtest_dir=str(env.run))) == 0
    assert "General: 1 rows (e.g. Sharpe: 0.6)" in capsys.readouterr().out and env.refreshed
    assert aq_cli.cmd_evaluate(argparse.Namespace(json=True, backtest_stats=True, backtest_dir=str(env.run))) == 0
    assert '"status": "ok"' in capsys.readouterr().out
    monkeypatch.setattr(statistics, "compute_for_run_dir", lambda run_dir, config, root: (_ for _ in ()).throw(FileNotFoundError("no result json")))
    assert aq_cli.cmd_evaluate(ns(backtest_stats=True, backtest_dir=str(env.run))) == 1 and "no result json" in capsys.readouterr().err


def test_classification_parity_exit_follows_the_tolerance(env, monkeypatch, capsys):
    import evaluation.classification_parity as parity

    ok = {"status": "ok", "model": "multitask", "head": "up", "n_matched": 9, "n_calls": 10, "within_tolerance": True,
          "deltas": {"accuracy": 0.01, "neg_log_loss": -0.02, "median_abs_probability_gap": 0.001}}
    results = iter([ok, {**ok, "within_tolerance": False}, {**ok, "within_tolerance": None}, {"status": "no_calls", "reason": "no book calls"}])
    monkeypatch.setattr(parity, "classification_parity_for_run_dir", lambda run_dir, config, root, dataset_path: dict(next(results)))
    args = ns(classification_parity=True, backtest_dir=str(env.run))
    assert aq_cli.cmd_evaluate(args) == 0 and "matched 9 of 10 calls" in capsys.readouterr().out
    assert aq_cli.cmd_evaluate(args) == 1 and aq_cli.cmd_evaluate(args) == 0 and aq_cli.cmd_evaluate(args) == 0
    assert "no book calls" in capsys.readouterr().out
