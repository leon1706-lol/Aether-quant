"""scripts/predict_sweep_bt1.py (V6.6.6): the T-bill sweep replayed over a finished run, on a tiny stand-in run.

Every reader of Lean output is a stand-in; the sweep rule's own pieces (target weight, reserve, margin) return fixed values,
so the test pins the replay itself: fills on the next session, fees, the P&L on BIL's moves and the written report."""

from __future__ import annotations

import datetime
import json
from types import SimpleNamespace

import pytest

from script_loader import load_script

D = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09"]


@pytest.fixture
def replay(tmp_path, monkeypatch):
    import evaluation.backtest_audit as audit
    import evaluation.lean_attribution as attribution
    import evaluation.lean_statistics as statistics
    import portfolio.cash_sweep as sweep

    run_dir = tmp_path / "backtests" / "run_x"
    run_dir.mkdir(parents=True)
    (run_dir / "123.json").write_text("{}", encoding="utf-8")
    (tmp_path / "config.json").write_text(json.dumps({"phase_v2": {"cash_sweep": {}}}), encoding="utf-8")
    run_config = tmp_path / "run_config.json"
    assets = [{"ticker": "AAA", "security_type": "equity"}, {"ticker": "BBB", "security_type": "equity"}, {"ticker": "EURUSD", "security_type": "forex"}]
    phase_v2 = {"legacy_sleeve": {"enabled": True, "max_gross_exposure": 0.1}, "bond_sleeve": {"enabled": True, "gross_budget": 0.2}, "portfolio_book": {"neutrality": {"gross_exposure_cap": 1.0}}}
    run_config.write_text(json.dumps({"phase1": {"universe": {"assets": assets}}, "phase_v2": phase_v2}), encoding="utf-8")
    history = tmp_path / "book.jsonl"
    history.write_text(json.dumps({"date": D[1], "allocations": {"AAA": {"target_weight": 0.3}, "BBB": {"target_weight": -0.1}}}) + "\n" + json.dumps({"date": D[3]}) + "\n", encoding="utf-8")

    monkeypatch.setattr(attribution, "run_config_path", lambda run_dir, root: run_config)
    monkeypatch.setattr(attribution, "find_book_history_for_run", lambda run_dir, folder: history)
    monkeypatch.setattr(audit, "load_backtest_run", lambda run_dir: {"order_events": [], "result": {}})
    monkeypatch.setattr(attribution, "fills_from_order_events", lambda events: [SimpleNamespace(ticker="AAA")])
    monkeypatch.setattr(audit, "daily_equity_from_chart", lambda result: [(day, 100000.0 + 100 * index) for index, day in enumerate(D)])
    closes = {"AAA": dict.fromkeys(D, 100.0), "BBB": dict.fromkeys(D, 50.0)}
    monkeypatch.setattr(attribution, "closes_for_universe", lambda config, root, tickers: closes)
    positions = {D[0]: {"AAA": {"position": 100}}, D[1]: {"BBB": {"position": -40}, "CCC": {"position": 7}, "ZERO": {"position": 0}}, D[2]: {}, D[3]: {}, D[4]: {}, D[5]: {}}
    monkeypatch.setattr(attribution, "daily_ticker_pnl", lambda fills, closes, dates, forex: positions)
    bil = {D[0]: 100.0, D[1]: 100.1, D[3]: 100.2, D[4]: 100.3, D[5]: 100.4}
    spy = {day: 400.0 for day in D[:5]}
    monkeypatch.setattr(attribution, "read_daily_closes", lambda path, scale: spy if path.name == "spy.zip" else bil)
    monkeypatch.setattr(sweep, "resolve_cash_sweep_config", lambda raw: {"data_path": "data/bil.zip", "cost_bps_per_side": 1.0, "min_trade_weight": 0.05})
    targets = iter([0.5, 0.5, 0.1, 0.1])
    monkeypatch.setattr(sweep, "cash_sweep_target_weight", lambda **kwargs: next(targets))
    monkeypatch.setattr(sweep, "strategy_reserve", lambda **kwargs: 0.0)
    monkeypatch.setattr(sweep, "margin_fraction", lambda inputs: 0.0)
    dates = [datetime.date.fromisoformat(day) for day in D]
    monkeypatch.setattr(statistics, "load_backtest_series", lambda path: {"performance": [0.0] * 6, "performance_dates": dates, "equity_dates": dates})
    monkeypatch.setattr(statistics, "with_extra_daily_returns", lambda performance, performance_dates, extra: [extra.get(day, 0.0) for day in performance_dates])
    monkeypatch.setattr(statistics, "load_interest_rate_changes", lambda path: [])
    monkeypatch.setattr(statistics, "lean_statistics", lambda performance, dates, trading_days_per_year, rate_changes: {"sharpe_ratio": sum(performance), "annual_return": 0.01, "annual_standard_deviation": 0.1})
    return run_dir


@pytest.mark.parametrize("with_old_rates", [True, False])
def test_the_sweep_is_replayed_and_reported(replay, tmp_path, monkeypatch, capsys, with_old_rates):
    module = load_script("predict_sweep_bt1")
    monkeypatch.setattr(module, "ROOT_DIR", tmp_path)
    if with_old_rates:
        (tmp_path / "ml" / "evaluation" / "v620").mkdir(parents=True)
        (tmp_path / "ml" / "evaluation" / "v620" / "interest-rate_pre_v620.csv").write_text("", encoding="utf-8")
    out = tmp_path / "prediction.json"
    monkeypatch.setattr(module.sys, "argv", ["x", "--backtest-dir", str(replay), "--out", str(out)])
    assert module.main() == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["run"] == "run_x" and report["sweep_trades"] == 2 and report["sweep_fees_usd"] > 2.0
    assert report["max_target_weight"] == 0.5 and abs(report["mean_target_weight"] - 1.1 / 3) < 1e-12  # three sessions decide: 0.5, 0.5, 0.1
    assert report["end_equity_with"] != report["end_equity_without"] and report["max_drawdown_with_sweep"] <= 0.0
    assert set(report["lean_statistics"]) == {f"{side}/{label}/{days}" for side in ("with_sweep", "without_sweep") for label in ("refreshed", "pre_v620") for days in (252, 365)}
    assert "written" in capsys.readouterr().out
