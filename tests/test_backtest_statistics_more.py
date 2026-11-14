"""evaluation/backtest_statistics.py's remaining branches (V6.6.6, #359): degenerate inputs, the assembly's odd cases on the synthetic run, and the
run-folder wrapper with its collaborators stubbed."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

from evaluation import backtest_statistics as stats_module
from test_backtest_statistics import DATES, _rows, synthetic  # noqa: F401  (the fixture)


def test_helpers_degrade_on_bad_or_flat_input(monkeypatch):
    assert stats_module._finite("x") is None and stats_module._finite(float("nan")) is None and stats_module._finite("2.5") == 2.5
    assert stats_module.drawdown_episodes(["2024-01-01"], [1.0]) == []
    assert stats_module._skew_kurtosis(stats_module.np.array([1.0, 1.0, 1.0])) == (0.0, 3.0)
    assert stats_module._duration_days("1.xx:00:00") is None
    monkeypatch.setattr(stats_module, "_skew_kurtosis", lambda values: (10.0, 3.0))
    assert stats_module.probabilistic_sharpe_ratio([0.01, 0.02, 0.0, 0.03, 0.01] * 10) is None


def test_trials_with_identical_sharpes_have_no_deflation():
    returns = [0.004, -0.002, 0.003, -0.001] * 100
    result = stats_module.deflated_sharpe_ratio(returns, [0.5, 0.5, 0.5])
    assert result["value"] is None and result["reason"] == "trial Sharpe ratios have no variance"


def test_book_calls_skip_unheld_roles_and_unknown_tickers_and_offline_models_get_rows():
    closes = {"AAA": {f"2024-01-{day:02d}": 100.0 + day for day in range(1, 29)}}
    sorted_closes = {"AAA": sorted(closes["AAA"])}
    history = [{"date": "2024-01-01", "allocations": {"AAA": {"role": "long"}, "BBB": {"role": "long"}, "CCC": {"role": "hold"}}}]
    calls = stats_module.lean_book_calls(history, closes, sorted_closes, horizon=5)
    assert calls["tickers"] == ["AAA"]
    rows = stats_module._classification_section(history, closes, sorted_closes, {"multitask": {"n": 10, "accuracy": 0.6, "threshold": 0.55}}, horizon=5)
    assert len(rows) == 2 and rows[1]["source"].startswith("Offline multitask") and rows[1]["accuracy"] == 0.6


def test_classification_reasons_say_how_many_calls_carry_a_probability():
    closes = {"AAA": {f"2024-01-{day:02d}": 100.0 + day for day in range(1, 29)}}
    sorted_closes = {"AAA": sorted(closes["AAA"])}
    source = stats_module.LEAN_PROBABILITY_SOURCE
    one = {"date": "2024-01-01", "allocations": {"AAA": {"role": "long"}}, "member_probabilities": {"AAA": {source: 0.7}}}
    two = {"date": "2024-01-02", "allocations": {"AAA": {"role": "long"}}}
    partial = stats_module._classification_section([one, two], closes, sorted_closes, None, horizon=5)[0]
    assert "1 of 2 calls" in partial["reason"]
    full = stats_module._classification_section([one], closes, sorted_closes, None, horizon=5)[0]
    assert full["reason"] is None and full["neg_log_loss"] is not None


def test_attribution_components_with_activity_are_listed():
    nav = [1000.0, 1010.0, 1020.0]
    components = {"main_book": {"fills": 2, "pnl": 5.0, "net": 4.0, "fee": 1.0}, "legacy": {"fills": 0, "pnl": 0.0}}
    section = stats_module._attribution_section({}, ["2024-01-01", "2024-01-02", "2024-01-03"], nav, {}, 1.0, 1000.0, 365, {"components": components})
    assert section["components"] == [{"component": "main_book", "net_pnl": 4.0, "fees": 1.0, "fills": 2}]


def test_the_trial_registry_is_optional(tmp_path):
    assert stats_module.load_trial_sharpes(tmp_path / "none.json") == []
    (tmp_path / "torn.json").write_text("{torn", encoding="utf-8")
    assert stats_module.load_trial_sharpes(tmp_path / "torn.json") == []
    (tmp_path / "ok.json").write_text(json.dumps({"trials": [{"median_sharpe": 0.4}, {"median_sharpe": None}]}), encoding="utf-8")
    assert stats_module.load_trial_sharpes(tmp_path / "ok.json") == [0.4]


def test_the_assembly_handles_odd_trades_benchmarks_fills_and_a_lean_formula_row(synthetic):  # noqa: F811
    run, config, root, history = synthetic
    sweep_trade = {"symbols": [{"value": "BIL"}], "entryTime": "2024-01-01T20:00:00Z", "entryPrice": 50.0, "quantity": 5.0, "direction": 0, "profitLoss": 1.0, "totalFees": 1.0, "duration": "1.00:00:00"}
    run["result"]["totalPerformance"]["closedTrades"].append(sweep_trade)
    benchmark = run["result"]["charts"]["Benchmark"]["series"]["Benchmark"]["values"]
    run["result"]["charts"]["Benchmark"]["series"]["Benchmark"]["values"] = [[point[0], 400.0] for point in benchmark]
    stamp = datetime.fromisoformat(DATES[1]).replace(hour=20, tzinfo=timezone.utc).timestamp()
    run["order_events"].append({"orderId": 9, "orderEventId": 9, "symbolValue": "AAA", "status": "filled", "time": stamp + 86400 * 400, "fillQuantity": 1.0, "fillPrice": 100.0, "orderFeeAmount": 0.0, "direction": "buy"})
    lean_basis = {"replica": {"shipped rate file": {"sharpe_ratio": 0.4}}}
    result = stats_module.compute_backtest_statistics(run, config, root, run_name="odd", book_history=history, lean_basis=lean_basis)
    assert result["status"] == "OK"
    assert _rows(result, "general")["Correlation to underlying (SPY, daily)"]["portfolio"] is None
    assert any(row["metric"] == "Sharpe, Lean formula (shipped rate file)" for row in result["sections"]["efficiency"])


def test_the_benchmark_section_needs_three_points_and_some_benchmarks(monkeypatch):
    import evaluation.alpha_proof as alpha_proof
    import evaluation.lean_benchmarks as lean_benchmarks

    config = {"phase1": {"universe": {"assets": [{"ticker": "BTCUSD", "security_type": "crypto"}, {"ticker": "ETHUSD", "security_type": "crypto"}]}}}
    points = [[datetime(2024, 1, day, tzinfo=timezone.utc).timestamp(), 1000.0 + day] for day in (1, 2, 3, 4)]
    fill = {"time": datetime(2024, 1, 2, 20, tzinfo=timezone.utc).timestamp(), "status": "filled", "symbolValue": "ETHUSD", "fillQuantity": 1, "fillPrice": 10.0}
    run = {"result": {"charts": {"Strategy Equity": {"series": {"Equity": {"values": points}}}}}, "order_events": [fill]}
    short = {"result": {"charts": {"Strategy Equity": {"series": {"Equity": {"values": points[:2]}}}}}}
    assert stats_module._benchmark_section(short, config, None) == []
    index = ["2024-01-02", "2024-01-03", "2024-01-04"]
    monkeypatch.setattr(alpha_proof, "benchmark_daily_returns", lambda *a, **k: pd.DataFrame())
    assert stats_module._benchmark_section(run, config, None) == []
    monkeypatch.setattr(alpha_proof, "benchmark_daily_returns", lambda *a, **k: pd.DataFrame({"SPY": [0.0, 0.01, 0.02]}, index=index))
    monkeypatch.setattr(alpha_proof, "strategy_daily_returns", lambda *a, **k: pd.Series([0.0, 0.01, 0.0], index=index))
    monkeypatch.setattr(lean_benchmarks, "benchmark_rows", lambda portfolio, strategy, benchmarks, crypto: [{"benchmark": "SPY", "crypto": crypto}])
    rows = stats_module._benchmark_section(run, config, None)
    assert rows[0]["benchmark"] == "SPY" and rows[0]["crypto"] == ["ETHUSD"]


def test_the_run_folder_wrapper_loads_the_companions(synthetic, monkeypatch):  # noqa: F811
    import evaluation.lean_statistics as lean_statistics

    run, config, root, history = synthetic
    run_dir = root / "backtests" / "2026-01-01_00-00-00"
    run_dir.mkdir(parents=True)
    (run_dir / "1.json").write_text(json.dumps(run["result"]), encoding="utf-8")
    (run_dir / "1-order-events.json").write_text(json.dumps(run["order_events"]), encoding="utf-8")
    evaluation_dir = root / "ml" / "evaluation"
    (evaluation_dir / "run_configs").mkdir(parents=True)
    (evaluation_dir / "classification_scores_multitask.json").write_text(json.dumps({"n": 5, "accuracy": 0.5}), encoding="utf-8")
    (evaluation_dir / "classification_scores_sequence.json").write_text("{torn", encoding="utf-8")
    (evaluation_dir / "run_configs" / f"{run_dir.name}.json").write_text(json.dumps(config), encoding="utf-8")
    history_dir = root / "visualization" / "book_history"
    history_dir.mkdir(parents=True)
    (history_dir / "20260101T000100Z.jsonl").write_text(json.dumps(history[0]) + "\n\n", encoding="utf-8")
    rate = root / "data" / "alternative" / "interest-rate" / "usa" / "interest-rate.csv"
    rate.parent.mkdir(parents=True)
    rate.write_text("date,rate\n", encoding="utf-8")
    monkeypatch.setattr(stats_module, "_benchmark_section", lambda run, config, root: [])
    monkeypatch.setattr(lean_statistics, "statistics_table", lambda *a, **k: {"replica": {}})
    result = stats_module.compute_for_run_dir(run_dir, {}, root)
    assert result["book_history"].endswith("20260101T000100Z.jsonl") and result["config"].endswith(f"{run_dir.name}.json") and result["sections"]["benchmarks"] == []
    monkeypatch.setattr(lean_statistics, "statistics_table", lambda *a, **k: (_ for _ in ()).throw(KeyError("x")))
    assert stats_module.compute_for_run_dir(run_dir, {}, root)["status"] == "OK"
    for path in history_dir.glob("*.jsonl"):
        path.unlink()
    (evaluation_dir / "run_configs" / f"{run_dir.name}.json").unlink()
    bare = stats_module.compute_for_run_dir(run_dir, config, root)
    assert bare["book_history"] is None and bare["config"] == "config.json"
