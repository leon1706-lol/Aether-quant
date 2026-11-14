"""scripts/gate_sweep.py's runtime (V6.6.6, #359): the blended raw scores from the exported models and the whole gate and kill-switch sweep, with the model
heads, the replays and the simulator replaced by small stand-ins."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from script_loader import load_script

DATES = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2019-02-01", periods=80)]
TICKERS = [f"T{n:02d}" for n in range(24)]


@pytest.fixture
def module(monkeypatch, tmp_path):
    sweep = load_script("gate_sweep")
    monkeypatch.setattr(sweep, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(sweep, "ML_DIR", tmp_path / "ml")
    (tmp_path / "ml" / "evaluation").mkdir(parents=True)
    (tmp_path / "ml" / "datasets").mkdir()
    (tmp_path / "config.json").write_text(json.dumps({"phase_v2": {"sequence_model": {"window_size": 5}, "portfolio_book": {"rebalance_every_bars": 10}}}), encoding="utf-8")
    return sweep


def _dataset():
    rows = [{"date": date, "ticker": ticker, "target_return_1d": 0.001 * ((index + number) % 5 - 2)} for index, date in enumerate(DATES) for number, ticker in enumerate(TICKERS)]
    return pd.DataFrame(rows)


def _model_files(sweep, *, kinds):
    from aq_cli import _EVALUATE_MODEL_ARTIFACTS

    for kind in kinds:
        model_name, schema_name = _EVALUATE_MODEL_ARTIFACTS[kind]
        (sweep.ML_DIR / model_name).write_text(json.dumps({"kind": kind}), encoding="utf-8")
        (sweep.ML_DIR / schema_name).write_text(json.dumps({"model_input_names": ["a", "b"]}), encoding="utf-8")


def _scoring_world(module, monkeypatch, priority):
    import portfolio.rank_signal as rank_signal

    seen = {}
    monkeypatch.setattr(rank_signal, "resolve_rank_signal_policy", lambda metrics, config: {"model_priority": list(priority), "heads": {"direction": 1.0, "volatility": 0.0}})
    monkeypatch.setattr(module, "select_context_date_range", lambda dataset, dates, window_size: (dates[0], dates[-1]))
    monkeypatch.setattr(module, "predict_head", lambda context, export, names, head, model_kind, sequence_feature_schema, configured_window_size: seen.setdefault(model_kind, []).append(head) or np.zeros(len(context)))
    monkeypatch.setattr(module, "compute_blended_raw_scores", lambda context, predictions, policy: pd.Series(np.arange(len(context), dtype=float), index=context.index))
    return seen


def test_scores_use_the_multitask_model_alone_when_it_is_available(module, monkeypatch):
    (module.ML_DIR / "multitask_training_metrics.json").write_text("{}", encoding="utf-8")
    _model_files(module, kinds=("multitask", "sequence"))
    seen = _scoring_world(module, monkeypatch, ["sequence", "multitask"])
    context = module.compute_raw_scores(_dataset(), {"phase_v2": {"sequence_model": {"window_size": 5}}})
    assert seen == {"multitask": ["direction"]} and "raw_blended_score" in context.columns and len(context) > 0


def test_a_sequence_only_priority_keeps_the_sequence_schema_and_missing_models_are_skipped(module, monkeypatch):
    _model_files(module, kinds=("sequence",))
    seen = _scoring_world(module, monkeypatch, ["sequence"])
    captured = []
    original = module.predict_head
    monkeypatch.setattr(module, "predict_head", lambda *args, **kwargs: captured.append(kwargs["sequence_feature_schema"]) or original(*args, **kwargs))
    module.compute_raw_scores(_dataset(), {})
    assert seen == {"sequence": ["direction"]} and captured[0] == {"model_input_names": ["a", "b"]}
    for path in module.ML_DIR.glob("*.json"):
        path.unlink()
    seen.clear()
    module.compute_raw_scores(_dataset(), {})
    assert seen == {}


def _sweep_world(module, monkeypatch):
    import evaluation.rank_book_simulator as simulator
    import features

    dataset = _dataset()
    dataset.to_csv(module.ML_DIR / "datasets" / "full_dataset.csv", index=False)
    dataset[["date", "ticker"]].assign(raw_blended_score=np.random.default_rng(1).normal(size=len(dataset))).to_csv(module.ML_DIR / "evaluation" / "gate_sweep_scored.csv", index=False)
    monkeypatch.setattr(module, "replay_rolling_ic_gate_over_dataset", lambda scored, raw_score_column, rebalance_dates, horizon_days, rolling_window_days, gate_config: [{"date": date, "engaged": index % 2 == 0} for index, date in enumerate(rebalance_dates)] + [{"date": "2018-01-01", "engaged": False}])
    monkeypatch.setattr(module, "summarize_rolling_ic_gate_replay", lambda records: {"overall": {"n": len(records)}, "records": records})
    monkeypatch.setattr(features, "load_sector_mapping", lambda config: {ticker: "tech" for ticker in TICKERS})
    result = SimpleNamespace(per_date=DATES[:30], per_date_net_return=[0.001] * 30, net_sharpe=1.2, gross_sharpe=1.5, turnover=0.4)
    monkeypatch.setattr(simulator, "simulate_rank_book", lambda scored, **kwargs: result)
    return result


@pytest.mark.parametrize("locked_attribute", ["locked", "trade_locked"])
def test_the_sweep_writes_its_gate_spread_and_kill_switch_grids(module, monkeypatch, capsys, locked_attribute):
    _sweep_world(module, monkeypatch)
    monkeypatch.setattr(module, "replay_kill_switch_over_dataset", lambda dates, returns, config, max_daily_drawdown_pct, max_total_drawdown_pct: [SimpleNamespace(**{locked_attribute: index % 2 == 0}) for index in range(len(dates))])
    monkeypatch.setattr(module, "summarize_kill_switch_replay", lambda records: {"total_trips": 2})
    assert module.main() == 0
    payload = json.loads((module.ML_DIR / "evaluation" / "gate_sweep_results.json").read_text(encoding="utf-8"))
    assert set(payload["rolling_ic_gate_grid"]) == {"w40_zero", "w40_p25_calibrated", "w40_aggressive"} and set(payload["spread_percentile_variants"]) == {"p50", "p75", "p90"}
    assert len(payload["kill_switch_grid"]) == 9 and payload["kill_switch_grid"]["sharpe0.15_bars40"]["trips"] == 2 and payload["base_simulator"]["net_sharpe"] == 1.2
    assert "IC grid" in capsys.readouterr().out


def test_a_summary_without_total_trips_falls_back_to_the_other_key(module, monkeypatch):
    _sweep_world(module, monkeypatch)
    monkeypatch.setattr(module, "replay_kill_switch_over_dataset", lambda *args, **kwargs: [])
    monkeypatch.setattr(module, "summarize_kill_switch_replay", lambda records: {"num_trips": 5})
    assert module.main() == 0
    assert json.loads((module.ML_DIR / "evaluation" / "gate_sweep_results.json").read_text(encoding="utf-8"))["kill_switch_grid"]["sharpe0.3_bars60"] == {"trips": 5, "days_locked_fraction": 0.0}


def test_the_config_is_read_from_the_repo_root(module):
    assert module.load_config()["phase_v2"]["portfolio_book"]["rebalance_every_bars"] == 10 and sys is not None


def test_gate_sweep_runs_as_a_script_and_reaches_its_entry_point(monkeypatch):
    import pytest as _pytest

    from script_loader import Stop, run_script, stop_at_first_read

    stop_at_first_read(monkeypatch)
    with _pytest.raises(Stop):
        run_script("gate_sweep", [], monkeypatch)
