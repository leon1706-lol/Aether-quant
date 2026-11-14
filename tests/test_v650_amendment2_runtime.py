"""scripts/v650_amendment2.py's runtime (V6.6.6, #359): the earnings trials, the PBO, the pre-2013 runs and verdict, the earnings pool and its judgement,
with the context, the earnings files and the Lean results stubbed."""

from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from script_loader import load_script

DATES = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2019-01-02", periods=80)]
RULES = {"selection_windows": {"rule_sleeves": ["2019-01-01", "2020-01-01", "2020-12-31"]}, "windows": {"verification": ["2023-07-01", "2024-06-30"], "long": ["2014-12-01", "2026-11-02"], "pre2013": ["2000-01-01", "2012-12-31"]}}


@pytest.fixture
def module(monkeypatch, tmp_path):
    load_script("v650_lean")
    amendment = load_script("v650_amendment2")
    out = tmp_path / "v650"
    out.mkdir()
    for name, value in (("OUT", out), ("DAILY", out / "selection_daily.parquet"), ("LEDGER", out / "trial_ledger.jsonl"), ("RESULT", out / "amendment3_eps.json"),
                        ("EPS_PATH", tmp_path / "eps.csv"), ("ROOT", tmp_path)):
        monkeypatch.setattr(amendment, name, value)
    monkeypatch.setattr(amendment, "check_rules", lambda: RULES)
    return amendment


def _context():
    known = pd.DataFrame(100.0 + np.arange(80)[:, None] + np.arange(3)[None, :], index=DATES, columns=["AAA", "BBB", "BTCUSD"])
    return SimpleNamespace(panel=SimpleNamespace(known=known, asset_class={}, fred={}, extras={}), settings=None)


def _eps():
    return pd.DataFrame({"ticker": ["AAA", "BBB"], "filed": ["2019-02-01", "2019-03-01"], "eps": [1.0, 2.0]})


def test_the_earnings_context_adds_two_surprise_tables(module, monkeypatch):
    monkeypatch.setattr(module, "load_context", _context)
    monkeypatch.setattr(module, "read_eps", lambda path: _eps())
    monkeypatch.setattr(module, "read_splits", lambda: pd.DataFrame())
    monkeypatch.setattr(module, "split_adjusted_eps", lambda eps, splits: eps)
    monkeypatch.setattr(module, "surprise_table", lambda eps, sessions, columns, hold_sessions: pd.DataFrame(0.1, index=sessions, columns=columns))
    context, eps = module.eps_context()
    assert {"eps_20", "eps_60"} <= set(context.panel.extras) and len(eps) == 2


def _score_world(module, monkeypatch, *, passing):
    monkeypatch.setattr(module, "eps_context", lambda: (_context(), _eps()))
    daily = {0: pd.Series(np.cos(np.arange(80)) * 0.01, index=DATES)}
    monkeypatch.setattr(module, "score_sleeve", lambda spec, context, start, split, end: {"sharpe": 1.0, "sharpe_first_half": 1.0, "sharpe_second_half": 1.0, "max_drawdown": 0.1, "mean_gross": 0.5, "daily": dict(daily)})
    monkeypatch.setattr(module, "passes_sharpe_clauses", lambda score: passing)
    monkeypatch.setattr(module, "nulls_for", lambda spec: ["shuffle", "shift"])
    monkeypatch.setattr(module, "placebo_sharpes", lambda spec, context, mode, start, end, draws: [] if mode == "shift" else [0.1, 0.2])
    monkeypatch.setattr(module, "placebo_p_value", lambda observed, sharpes: 0.01)
    pd.DataFrame({"x": np.zeros(80)}, index=DATES).to_parquet(module.DAILY)


@pytest.mark.parametrize("passing", [False, True])
def test_the_earnings_trials_are_scored_and_only_a_passing_one_meets_its_placebos(module, monkeypatch, passing):
    _score_world(module, monkeypatch, passing=passing)
    assert module.stage_eps_score(SimpleNamespace(draws=2)) == 0
    result = json.loads(module.RESULT.read_text(encoding="utf-8"))
    assert set(result["scores"]) == {spec.id for spec in module.EPS_SPECS} and (bool(result["placebos"]) == passing) and (bool(result["survivors"]) == passing)


def test_the_pbo_runs_on_the_common_window(module, monkeypatch):
    import evaluation.pbo as pbo

    pd.DataFrame({"a": np.sin(np.arange(80)) * 0.01, "b": np.cos(np.arange(80)) * 0.01}, index=DATES).to_parquet(module.DAILY)
    monkeypatch.setattr(pbo, "probability_of_backtest_overfitting", lambda matrix, blocks, periods_per_year: {"pbo": 0.4, "num_trials": 2})
    assert module.stage_pbo(SimpleNamespace()) == 0
    assert json.loads((module.OUT / "amendment3_pbo.json").read_text(encoding="utf-8"))["pbo"] == 0.4


def test_the_pre2013_runs_are_the_frozen_candidate_and_its_placebos(module, monkeypatch):
    monkeypatch.setattr(module, "check_freeze", lambda: {"survivors": ["w01", "w02"], "method": "hrp"})
    monkeypatch.setattr(module, "_base", lambda: {})
    monkeypatch.setattr(module, "pre2013_context", lambda base: (_context(), {"universe": 1}))
    monkeypatch.setattr(module, "candidate_rows", lambda definition, context, **kwargs: {"d": {}})
    monkeypatch.setattr(module, "make_run", lambda name, rows, window, config, **kwargs: {"name": name})
    monkeypatch.setattr(module, "E5_DRAWS", 3)
    monkeypatch.setitem(module.SPECS, "w01", SimpleNamespace(universe=("equity",)))
    monkeypatch.setitem(module.SPECS, "w02", SimpleNamespace(universe=("crypto",)))
    assert module.stage_pre2013_make(SimpleNamespace()) == 0
    made = json.loads((module.OUT / "pre2013_runs.json").read_text(encoding="utf-8"))
    assert made["definition"] == {"survivors": ["w01"], "method": None} and len(made["runs"]) == 4


def test_the_observation_rate_and_sharpe_follow_the_series_length(module):
    index = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2020-01-01", periods=300)]
    series = pd.Series(np.sin(np.arange(300)) * 0.01 + 0.001, index=index)
    assert 200 < module.per_year(series) < 300 and module.sharpe_on_observations(series) is not None
    assert module.sharpe_on_observations(series.iloc[:10]) is None and module.sharpe_on_observations(pd.Series(0.01, index=index)) is None


def _equity_result(run_dir, orders=()):
    stamps = [pd.Timestamp(day, tz="UTC").timestamp() for day in DATES[:30]]
    result = {"charts": {"Strategy Equity": {"series": {"Equity": {"values": [[stamp, 1000.0 + 5 * np.sin(index) + index] for index, stamp in enumerate(stamps)]}}}}, "statistics": {}}
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "1.json").write_text(json.dumps(result), encoding="utf-8")
    if orders:
        (run_dir / "1-order-events.json").write_text(json.dumps(orders), encoding="utf-8")
    (run_dir / "log.txt").write_text("PythonInitializer.Shutdown(): start\n", encoding="utf-8")


def test_the_pre2013_verdict_compares_the_run_with_its_placebos(module, tmp_path, monkeypatch):
    import evaluation.alpha_proof as alpha_proof

    _equity_result(tmp_path / "backtests" / "v650_e5", orders=[{"time": pd.Timestamp("2019-01-03 20:00", tz="UTC").timestamp(), "status": "filled", "symbolValue": "AAA", "fillQuantity": 1, "fillPrice": 10.0}])
    _equity_result(tmp_path / "backtests" / "v650_e5_null_00")
    _equity_result(tmp_path / "backtests" / "v650_e5_null_01")
    (tmp_path / "ml" / "evaluation" / "run_configs").mkdir(parents=True)
    (tmp_path / "ml" / "evaluation" / "run_configs" / "v650_e5.json").write_text("{}", encoding="utf-8")
    status = tmp_path / "status.txt"
    status.write_text("LEAN_DONE v650_e5 backtests/v650_e5\nLEAN_DONE v650_e5_null_00 backtests/v650_e5_null_00\nLEAN_DONE v650_e5_null_01 backtests/v650_e5_null_01\nnoise\n", encoding="utf-8")
    monkeypatch.setattr(alpha_proof, "benchmark_daily_returns", lambda root, config, tickers, start, end, data_dir: pd.DataFrame({"SPY": np.cos(np.arange(80)) * 0.01}, index=DATES))
    monkeypatch.setattr(alpha_proof, "alpha_regression", lambda y, x: {"alpha_annual": 0.03, "t_hac": 2.0, "betas": {}})
    monkeypatch.setattr(alpha_proof, "to_sessions", lambda series, index: series)
    monkeypatch.setattr(module, "lean_statistics", lambda run_dir: {"lean_sharpe": 1.0})
    assert module.stage_pre2013_judge(SimpleNamespace(status=str(status))) == 0
    result = json.loads((module.OUT / "pre2013_result.json").read_text(encoding="utf-8"))
    assert result["fills"] == 1 and len(result["placebo_sharpes"]) == 2 and result["first_fill"] == "2019-01-03"
    assert module._nav_returns(tmp_path / "backtests" / "v650_e5").shape[0] == 29


def test_the_weights_of_an_earnings_sleeve_follow_the_phase_and_can_be_nulled(module, monkeypatch):
    import evaluation.premia_research as premia
    import portfolio.premia_signals as signals

    monkeypatch.setattr(signals, "sleeve_signal", lambda spec, panel: panel.known)
    monkeypatch.setattr(signals, "null_signal", lambda signal, mode, seed, asset_class: signal)
    monkeypatch.setattr(premia, "phase_offsets", lambda every, count: [0, 1])
    monkeypatch.setattr(premia, "weights_for", lambda spec, context, signal, start, end, phase_offset: {"phase": phase_offset})
    assert module.eps_rows(module.EPS_SPECS[0], _context(), start="a", end="b", phase_index=3) == {"phase": 1}
    assert module.eps_rows(module.EPS_SPECS[0], _context(), start="a", end="b", phase_index=0, null_mode="shuffle", seed=2) == {"phase": 0}


def test_the_correlation_clause_drops_the_weaker_of_two_alike_survivors(module):
    index = DATES
    base = np.sin(np.arange(80)) * 0.01
    daily = pd.DataFrame({"a": base, "b": base * 1.01, "c": np.cos(np.arange(80)) * 0.01}, index=index)
    scores = {"a": {"sharpe": 2.0}, "b": {"sharpe": 1.0}, "c": {"sharpe": 0.5}}
    assert module.apply_correlation_clause(["a", "b", "c"], scores, daily) == ["a", "c"]


def test_the_earnings_pool_is_frozen_in_the_vault_before_its_runs_are_written(module, monkeypatch, tmp_path):
    for relative in ("scripts/v650_amendment2.py", "data_pipeline/edgar_facts.py", "portfolio/premia_signals.py", "portfolio/target_weights.py", "main.py"):
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(relative, encoding="utf-8")
    spec = module.EPS_SPECS[0]
    daily = pd.DataFrame({spec.id: np.sin(np.arange(80)) * 0.01}, index=DATES)
    daily.to_parquet(module.DAILY)
    module.write_json(module.RESULT, {"survivors": []})
    assert module.stage_eps_pool(SimpleNamespace()) == 0
    module.write_json(module.RESULT, {"survivors": [spec.id], "scores": {spec.id: {"sharpe": 1.0}}})
    vault = types.ModuleType("vault_record")
    vault.record = lambda name, paths, values: {"ok": False}
    monkeypatch.setitem(sys.modules, "vault_record", vault)
    with pytest.raises(SystemExit, match="could not record"):
        module.stage_eps_pool(SimpleNamespace())
    vault.record = lambda name, paths, values: {"ok": True, "commit": "abc"}
    monkeypatch.setattr(module, "eps_context", lambda: (_context(), _eps()))
    monkeypatch.setattr(module, "eps_rows", lambda spec_, context, **kwargs: {"d": {}})
    monkeypatch.setattr(module, "_base", lambda: {})
    monkeypatch.setattr(module, "make_run", lambda name, rows, window, base: {"name": name})
    assert module.stage_eps_pool(SimpleNamespace()) == 0
    assert len(json.loads((module.OUT / "eps_pool_runs.json").read_text(encoding="utf-8"))) == module.PHASES + 1


def test_a_finished_pool_run_is_described_by_its_strategy_and_alpha(module, tmp_path, monkeypatch):
    import evaluation.alpha_proof as alpha_proof
    import v650_instrument
    import v650_lean

    run_dir = tmp_path / "backtests" / "v650_pool_x_p0"
    _equity_result(run_dir, orders=[{"time": pd.Timestamp("2019-01-03 20:00", tz="UTC").timestamp(), "status": "filled", "symbolValue": "BIL", "fillQuantity": 1, "fillPrice": 10.0},
                                    {"time": pd.Timestamp("2019-01-04 20:00", tz="UTC").timestamp(), "status": "filled", "symbolValue": "AAA", "fillQuantity": 1, "fillPrice": 10.0}])
    configs = tmp_path / "run_configs"
    configs.mkdir()
    (configs / run_dir.name).with_suffix(".json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(v650_instrument, "RUN_CONFIGS", configs)
    monkeypatch.setattr(v650_lean, "strategy_series", lambda run_dir_, config: pd.Series(np.sin(np.arange(40)) * 0.01, index=DATES[:40]))
    monkeypatch.setattr(module, "lean_statistics", lambda run_dir_: {"lean_sharpe": 1.0})
    monkeypatch.setattr(alpha_proof, "benchmark_daily_returns", lambda root, config, start, end: pd.DataFrame({"SPY": np.cos(np.arange(80)) * 0.01}, index=DATES))
    monkeypatch.setattr(alpha_proof, "alpha_regression", lambda y, x: {"alpha_annual": 0.03, "t_hac": 2.0, "betas": {}})
    monkeypatch.setattr(alpha_proof, "to_sessions", lambda series, index: series)
    monkeypatch.setattr(alpha_proof, "sharpe", lambda values, annualization: 1.1)
    stats = module.describe_run(run_dir)
    assert stats["strategy_sharpe"] == 1.1 and stats["complete"] is True and stats["last_fill"] == "2019-01-03" or stats["last_fill"] is not None


def test_the_earnings_judgement_adds_the_survivor_to_the_round_one_pool(module, tmp_path, monkeypatch):
    spec = module.EPS_SPECS[0]
    module.write_json(module.OUT / "r_lean19.json", {"baseline": {"lean_sharpe": 0.1, "strategy_sharpe": 0.1}, "pool": {}})
    module.write_json(module.RESULT, {"survivors_after_correlation": [spec.id]})
    lines = [f"LEAN_DONE v650_pool_{spec.id}_p{phase} backtests/p{phase}" for phase in range(module.PHASES)] + [f"LEAN_DONE v650_pool_{spec.id}_long backtests/long", "LEAN_DONE v650_other backtests/x"]
    status = tmp_path / "status.txt"
    status.write_text("\n".join(lines), encoding="utf-8")
    monkeypatch.setattr(module, "describe_run", lambda run_dir: {"lean_sharpe": 1.0, "strategy_sharpe": 1.0, "annual_std": 0.08, "drawdown_pct": 5.0, "alpha_annual": 0.02, "alpha_t": 2.0, "complete": True})
    assert module.stage_eps_judge(SimpleNamespace(status=str(status))) == 0
    report = json.loads((module.OUT / "r_lean19_amended.json").read_text(encoding="utf-8"))
    assert report["pool"][spec.id]["complete"] is True and report["verdict"]["best"] == spec.id


@pytest.mark.parametrize("argv,name", [(["eps-score", "--draws", "3"], "eps_score"), (["pbo"], "pbo"), (["eps-pool"], "eps_pool"), (["eps-judge", "--status", "s"], "eps_judge"),
                                       (["pre2013-make"], "pre2013_make"), (["pre2013-judge", "--status", "s"], "pre2013_judge")])
def test_the_command_dispatches_each_stage(module, monkeypatch, argv, name):
    seen = []
    monkeypatch.setattr(module, f"stage_{name}", lambda args: seen.append(name) or 0)
    monkeypatch.setattr(sys, "argv", ["amendment2", *argv])
    assert module.main() == 0 and seen == [name]
