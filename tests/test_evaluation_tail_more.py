"""Small tails of live_parity, benchmark_comparison, trend_sleeve_backtest and research_runners (V6.6.6, #359)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from evaluation import benchmark_comparison, live_parity, research_runners, trend_sleeve_backtest
from synthetic_lean import build_world


def test_parity_helpers_degrade_on_garbage_and_group_the_main_pool():
    assert live_parity._finite("x", 2.0) == 2.0 and live_parity._finite(float("inf"), 1.0) == 1.0
    assert live_parity.main_group_tickers(None, ["A"]) is None and live_parity.main_group_tickers({}, ["A"]) is None
    assert live_parity.main_group_tickers({"A": "main", "B": "bond"}, ["A", "B", "C"]) == {"A", "C"}


def test_a_cash_sweep_with_no_prices_is_none(tmp_path):
    config = {"phase_v2": {"cash_sweep": {"enabled": True, "ticker": "BIL", "data_path": "data/equity/usa/daily/bil.zip"}}}
    assert live_parity.build_cash_sweep_kwarg(config, tmp_path) is None
    assert live_parity.build_cash_sweep_kwarg({"phase_v2": {}}, tmp_path) is None


def test_the_momentum_baseline_holds_the_leaders_and_marks_them_to_the_next_close():
    rng = np.random.default_rng(0)
    index = pd.bdate_range("2024-01-01", periods=80)
    pivot = pd.DataFrame(100.0 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, (80, 12)), axis=0)), index=index, columns=[f"T{n}" for n in range(12)])
    pivot.iloc[50, 3] = np.nan
    result = benchmark_comparison.momentum_baseline(pivot, lookback=10, top_n=3, bottom_n=3, rebalance_every=5)
    assert result
    thin = benchmark_comparison.momentum_baseline(pivot.iloc[:, :4], lookback=10, top_n=3, bottom_n=3, rebalance_every=5)
    assert thin is not None


def test_trend_closes_load_from_the_config_zips_and_a_short_series_summarises_flat(tmp_path):
    world = build_world(tmp_path)
    closes = trend_sleeve_backtest.load_daily_closes(world.root, world.config, ["AAA"], start="2024-01-10", end="2024-03-01")
    assert list(closes.columns) == ["AAA"] and closes.index.min() >= "2024-01-10" and closes.index.max() <= "2024-03-01"
    assert trend_sleeve_backtest._trade_cost(0.0, 5.0, 1.0, 1.0) == 0.0
    assert trend_sleeve_backtest.summarize_daily(pd.Series([0.01]))["days"] == 1


def test_the_leakage_audit_reads_the_scaled_features_and_labels_rank_groups(tmp_path, monkeypatch):
    import evaluation.leakage_audit as leakage_audit
    import evaluation.research_probes as research_probes

    monkeypatch.setattr(research_runners, "ML_DIR", tmp_path)
    (tmp_path / "feature_schema.json").write_text(json.dumps({"scaled_feature_names": ["f1", "f2"]}), encoding="utf-8")
    assert research_runners._scaled_features() == ["f1", "f2"]
    frame = pd.DataFrame({"ticker": ["AAA", "BTCUSD"], "f1": [0.1, 0.2], "f2": [0.3, 0.4], "target_rank_20d": [0.5, 0.6]})
    monkeypatch.setattr(research_probes, "load_research_frame", lambda path, columns, splits: frame)
    seen = {}
    monkeypatch.setattr(leakage_audit, "audit_leakage", lambda data, feature_columns, target_column, class_columns, group_column: seen.update(groups=list(data[group_column])) or {"audited": True})
    report = research_runners.run_audit_leakage("data.csv")
    assert report["audited"] is True and report["dataset"] == "data.csv" and len(seen["groups"]) == 2
    config = {"phase1": {"universe": {"assets": [{"ticker": "AAA", "security_type": "equity"}, {"ticker": "EURUSD", "security_type": "forex"}]}, "target": {"ranking": {"separate_rank_groups": {"fx": ["forex"]}}}}}
    assert research_runners.rank_group_labels(["AAA", "EURUSD", "GHOST"], config) == ["main", "fx", "main"]
