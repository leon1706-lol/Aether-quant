"""aq evaluate flags that read one finished Lean run, part 2 (V6.6.6, #359): paper check, audit, Lean statistics, Monte Carlo and attribution."""

from __future__ import annotations

import argparse
import json
from datetime import datetime

import numpy as np

import aq_cli
from test_aq_cli_evaluate_lean import env, ns  # noqa: F401  (the fixture and the namespace builder)


def test_paper_check_compares_a_run_with_the_reference_bands(env, monkeypatch, capsys):
    import evaluation.lean_attribution as attribution
    import evaluation.paper_protocol as protocol

    reference = env.root / "backtests" / "2025-01-01_00-00-00"
    reference.mkdir()
    verdicts = iter([{"inside": True, "outside": [], "minimum_met": True, "minimum": 6}, {"inside": False, "outside": ["fills"], "minimum_met": False, "minimum": 6}])
    monkeypatch.setattr(protocol, "paper_metrics_for_run_dir", lambda run_dir, config, root, start=None, end=None: {"metrics": {"rebalances": 6, "trading_days": 130}, "table": 1, "rebalances": 2, "slippage_by_date": {}})
    monkeypatch.setattr(protocol, "reference_bands", lambda table, rebalances, slippage: {"fills": [1, 2]})
    monkeypatch.setattr(protocol, "band_check", lambda metrics, bands: next(verdicts))
    monkeypatch.setattr(attribution, "run_config_path", lambda run_dir, root: (_ for _ in ()).throw(OSError("no snapshot")))
    args = ns(paper_check=True, backtest_dir=str(env.run), reference_dir=str(reference))
    assert aq_cli.cmd_evaluate(args) == 0 and "inside all bands: True" in capsys.readouterr().out
    assert aq_cli.cmd_evaluate(args) == 0
    text = capsys.readouterr().out
    assert "outside: fills" in text and "below the minimum of 6" in text and (env.out / "paper_check.json").exists()
    assert aq_cli.cmd_evaluate(ns(paper_check=True, backtest_dir=str(env.run), reference_dir=str(env.root / "gone"))) == 1
    snapshot = env.root / "snapshot.json"
    snapshot.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(attribution, "run_config_path", lambda run_dir, root: snapshot)
    monkeypatch.setattr(protocol, "band_check", lambda metrics, bands: {"inside": True, "outside": [], "minimum_met": True, "minimum": 6})
    assert aq_cli.cmd_evaluate(args) == 0


def _audit():
    return {
        "run_id": "123", "window": {"num_days": 40}, "lean_statistics": {"Sharpe Ratio": "0.5"}, "sharpe": {"no_risk_free": None, "with_risk_free": 0.4, "risk_free_annual_assumed": 0.04},
        "exposure": {"equity": {"mean": 0.1, "peak": 0.2}}, "entries_by_asset_class": {"equity": 3}, "pnl_by_entry_bucket": {"book": [1, 2, 3]},
        "orders": {"num_overlapping_pairs": 0, "num_overlapping_limit_pairs": 0, "max_open_sessions_threshold": 4, "num_limit_orders_open_too_long": 0},
        "holding_period_days": {"1": 2}, "pnl_and_fees": {"net": 1.0}, "book": {"num_engaged": 2, "num_rebalance_records": 3, "veto_reasons": {}}, "teardown": {"ok": True},
        "periods": [
            {"start": "2025-01-01", "end": "2025-06-30", "net_return": None, "max_drawdown": -0.05, "sharpe_no_risk_free": 0.3, "closed_trades": 4, "realized_pnl_by_class": {}},
            {"start": "2025-07-01", "end": "2025-12-31", "net_return": 0.02, "max_drawdown": -0.01, "sharpe_no_risk_free": 0.9, "closed_trades": 5, "realized_pnl_by_class": {}},
        ],
    }


def test_the_audit_prints_its_summary_or_json_and_refuses_a_bad_period(env, monkeypatch, capsys):
    import evaluation.backtest_audit as audit

    monkeypatch.setattr(audit, "load_backtest_run", lambda run_dir: {"result": {}})
    monkeypatch.setattr(audit, "load_book_history", lambda path: [])
    monkeypatch.setattr(audit, "class_by_ticker_from_config", lambda config: {})
    seen = {}
    monkeypatch.setattr(audit, "audit_backtest_run", lambda run, history, **kwargs: seen.update(kwargs) or _audit())
    args = ns(audit_backtest=True, backtest_dir=str(env.run), period=["2025-01-01..2025-06-30"])
    assert aq_cli.cmd_evaluate(args) == 0
    text = capsys.readouterr().out
    assert "Backtest audit:" in text and "period 2025-01-01..2025-06-30: net n/a" in text and "net +2.00%" in text and seen["max_open_sessions"] >= 1
    assert seen["periods"] == [("2025-01-01", "2025-06-30")] and env.refreshed and (env.out / "backtest_audit.json").exists()
    assert aq_cli.cmd_evaluate(argparse.Namespace(json=True, audit_backtest=True, backtest_dir=str(env.run), max_open_sessions=9)) == 0
    assert '"run_id": "123"' in capsys.readouterr().out and seen["max_open_sessions"] == 9
    assert aq_cli.cmd_evaluate(ns(audit_backtest=True, backtest_dir=str(env.run), period=["2025-01-01"])) == 1 and "START..END" in capsys.readouterr().err
    monkeypatch.setattr(audit, "load_backtest_run", lambda run_dir: (_ for _ in ()).throw(FileNotFoundError("no results")))
    assert aq_cli.cmd_evaluate(args) == 1 and "no results" in capsys.readouterr().err


def test_lean_stats_prints_the_replica_for_each_rate_file(env, monkeypatch, capsys):
    import evaluation.lean_statistics as lean_statistics

    (env.run / "123.json").write_text("{}", encoding="utf-8")
    (env.out / "v620").mkdir()
    (env.out / "v620" / "interest-rate_pre_v620.csv").write_text("", encoding="utf-8")
    seen = {}
    row = {"sharpe_ratio": 0.5, "sortino_ratio": 0.7, "probabilistic_sharpe_ratio": 0.6, "annual_return": 0.1, "annual_standard_deviation": 0.12, "risk_free_rate": 0.04}
    monkeypatch.setattr(lean_statistics, "statistics_table", lambda result, rate_files, day_counts: seen.update(files=list(rate_files), days=day_counts) or {"run_trading_days_per_year": 365, "lean_printed": {}, "replica": {"shipped": row}})
    assert aq_cli.cmd_evaluate(ns(lean_stats=True, backtest_dir=str(env.run))) == 0
    assert seen["files"] == ["shipped rate file", "pre-V6.2 rate file"] and seen["days"] == (252, 365) and "Wrote" in capsys.readouterr().out
    assert aq_cli.cmd_evaluate(ns(lean_stats=True, backtest_dir=str(env.run), interest_rate_file="rates.csv", trading_days="252")) == 0
    assert seen["files"] == ["--interest-rate-file"] and seen["days"] == (252,)
    (env.run / "123.json").unlink()
    assert aq_cli.cmd_evaluate(ns(lean_stats=True, backtest_dir=str(env.run))) == 1 and "no Lean result JSON" in capsys.readouterr().err


def test_lean_monte_carlo_saves_the_curves_and_the_summary(env, monkeypatch, capsys):
    import evaluation.alpha_proof as alpha_proof
    import evaluation.backtest_audit as audit
    import evaluation.monte_carlo as monte_carlo

    equity = [("2025-01-01", 100.0), ("2025-01-02", 101.0), ("2025-01-03", 0.0), ("2025-01-04", 103.0)]
    monkeypatch.setattr(audit, "load_backtest_run", lambda run_dir: {"result": {}})
    monkeypatch.setattr(audit, "daily_equity_from_chart", lambda result: equity)
    windows = iter([(datetime(2025, 1, 1), datetime(2025, 1, 4)), (None, None), (None, None)])
    monkeypatch.setattr(audit, "configured_run_window", lambda result: next(windows))
    monkeypatch.setattr(alpha_proof, "measured_annualization", lambda days, fallback: 365.0)
    summary = {"status": "OK", "runs_curves": np.ones((2, 3)), "final_return_pct": {"p5": -1, "p50": 2, "p95": 5}, "sharpe": {"p50": 0.5}, "prob_negative_return": 0.2}
    monkeypatch.setattr(monte_carlo, "run_monte_carlo", lambda returns, **kwargs: dict(summary))
    assert aq_cli.cmd_evaluate(ns(lean_monte_carlo=True, backtest_dir=str(env.run))) == 0
    assert "final return p5/p50/p95 -1% / 2% / 5%" in capsys.readouterr().out and (env.out / "monte_carlo_lean_curves.npz").exists()
    payload = json.loads((env.out / "monte_carlo_lean.json").read_text(encoding="utf-8"))
    assert payload["first_date"] == "2025-01-01" and payload["num_daily_returns"] == 2 and "runs_curves" not in payload
    monkeypatch.setattr(monte_carlo, "run_monte_carlo", lambda returns, **kwargs: {"status": "TOO_SHORT"})
    assert aq_cli.cmd_evaluate(ns(lean_monte_carlo=True, backtest_dir=str(env.run))) == 0
    assert json.loads((env.out / "monte_carlo_lean.json").read_text(encoding="utf-8"))["first_date"] == "2025-01-01"
    monkeypatch.setattr(audit, "daily_equity_from_chart", lambda result: [])
    assert aq_cli.cmd_evaluate(ns(lean_monte_carlo=True, backtest_dir=str(env.run))) == 0


def test_attribution_prints_each_period_and_refuses_a_bad_one(env, monkeypatch, capsys):
    import evaluation.backtest_audit as audit
    import evaluation.lean_attribution as attribution

    history = env.root / "book.jsonl"
    history.write_text(json.dumps({"date": "2025-01-02"}) + "\n\n", encoding="utf-8")
    report = {
        "reconciliation": {"rebuilt_net_usd": 10.0, "lean_net_usd": 9.5, "daily_change_correlation": 0.99},
        "components": {"main_book": {"fills": 3, "pnl": 11.0, "fee": 1.0, "net": 10.0}, "idle": {"fills": 0, "pnl": 0, "fee": 0, "net": 0}},
    }
    monkeypatch.setattr(audit, "load_backtest_run", lambda run_dir: {})
    monkeypatch.setattr(attribution, "attribute_run", lambda run, history, config, root, period: report)
    monkeypatch.setattr(attribution, "find_book_history_for_run", lambda run_dir, folder: None)
    monkeypatch.setattr(attribution, "run_config_path", lambda run_dir, root: None)
    assert aq_cli.cmd_evaluate(ns(attribute_lean=True, backtest_dir=str(env.run))) == 1 and "no per-run book history" in capsys.readouterr().err
    args = ns(attribute_lean=True, backtest_dir=str(env.run), book_history_file=str(history), period=["2025-01-01..2025-03-31"])
    assert aq_cli.cmd_evaluate(args) == 0
    text = capsys.readouterr().out
    assert "whole_run: rebuilt net +10.00 vs Lean +9.50" in text and "2025-01-01..2025-03-31" in text and "main_book" in text and "idle" not in text
    snapshot = env.root / "run_config.json"
    snapshot.write_text(json.dumps({"phase1": {}}), encoding="utf-8")
    monkeypatch.setattr(attribution, "run_config_path", lambda run_dir, root: snapshot)
    assert aq_cli.cmd_evaluate(args) == 0
    assert aq_cli.cmd_evaluate(ns(attribute_lean=True, backtest_dir=str(env.run), book_history_file=str(history), period=["bad"])) == 1
