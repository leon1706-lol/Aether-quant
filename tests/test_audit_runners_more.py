"""evaluation/audit_runners.py (V6.6.6, #359): the aq evaluate audit flags' orchestration, with the analysis modules and the as-live harness stubbed.
The test checks what is loaded, what is passed on and what is returned."""

from __future__ import annotations

import json
import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pandas as pd

from evaluation import audit_runners as runners


def _harness(frame=None):
    frame = frame if frame is not None else pd.DataFrame({
        "date": ["2025-01-02", "2025-01-03"] * 2, "ticker": ["AAA", "AAA", "BBB", "BBB"], "live_rank_score": [0.1, 0.2, 0.3, 0.4],
        "target_return_20d": [0.01, 0.02, 0.0, 0.01], "target_return_5d": [0.0, 0.01, 0.01, 0.0]})
    return SimpleNamespace(frame=frame, lagged_frame=frame, asset_class_by_ticker={"AAA": "equity", "BBB": "bond"}, rank_groups={},
                           ic_config={"horizon_days": 20, "rolling_window_days": 40, "min_names_per_date": 1}, _states={"a": "state"},
                           gate_for=lambda data: "gate")


def test_the_harness_comes_from_the_scripts_folder(monkeypatch):
    module = ModuleType("as_live_levers")
    module.AsLiveHarness = lambda split, dataset_path: ("harness", split, dataset_path)
    monkeypatch.setitem(sys.modules, "as_live_levers", module)
    monkeypatch.setattr(sys, "path", [item for item in sys.path if not item.endswith("scripts")])
    assert runners._harness("backtest", "d.csv") == ("harness", "backtest", "d.csv")
    assert any(item.endswith("scripts") for item in sys.path)
    assert runners._harness("validation", None)[1] == "validation"


def test_the_ic_by_class_report_covers_each_available_target(monkeypatch):
    import evaluation.class_ic_audit as class_ic_audit

    seen = []
    monkeypatch.setattr(runners, "_harness", lambda split, dataset_path: _harness())
    monkeypatch.setattr(class_ic_audit, "class_ic_decomposition", lambda frame, prediction, target, horizon, min_names_per_class: seen.append((target, horizon, list(frame["asset_class"].unique()))) or {"ok": target})
    report = runners.run_ic_by_class({}, split="backtest")
    assert report["rows"] == 4 and set(report["heads"]) == {"target_return_20d", "target_return_5d"} and seen[0][2] == ["equity", "bond"]
    thin = _harness(pd.DataFrame({"ticker": ["AAA"], "live_rank_score": [0.1], "target_return_20d": [0.1]}))
    monkeypatch.setattr(runners, "_harness", lambda split, dataset_path: thin)
    assert set(runners.run_ic_by_class({}, split="backtest")["heads"]) == {"target_return_20d"}


def test_the_gate_audit_scores_the_main_pool_against_the_resolved_ic(monkeypatch):
    import evaluation.gate_audit as gate_audit
    import evaluation.live_parity as live_parity

    captured = {}
    monkeypatch.setattr(runners, "_harness", lambda split, dataset_path: _harness())
    monkeypatch.setattr(live_parity, "main_group_tickers", lambda groups, tickers: {"AAA"})
    monkeypatch.setattr(gate_audit, "daily_rank_ic", lambda scored, score_column, target_column, min_names_per_date: captured.update(tickers=set(scored["ticker"]), target=target_column) or "daily")
    monkeypatch.setattr(gate_audit, "audit_rolling_ic_gate", lambda **kwargs: captured.update(kwargs) or {"audited": True})
    report = runners.run_audit_gates({}, split="backtest")
    assert captured["tickers"] == {"AAA"} and report["grouped_main_pool_only"] is True and report["target"] == "target_return_20d" and captured["decision_dates"] == ["2025-01-02", "2025-01-03"]
    no_pool = _harness(pd.DataFrame({"date": ["2025-01-02"], "ticker": ["AAA"], "live_rank_score": [0.1], "target_rank_20d": [0.5]}))
    monkeypatch.setattr(runners, "_harness", lambda split, dataset_path: no_pool)
    monkeypatch.setattr(live_parity, "main_group_tickers", lambda groups, tickers: None)
    again = runners.run_audit_gates({}, split="backtest")
    assert again["grouped_main_pool_only"] is False and again["target"] == "target_rank_20d"


def test_the_data_audit_writes_its_manifest_when_asked(tmp_path, monkeypatch):
    import data_pipeline.data_audit as data_audit

    monkeypatch.setattr(data_audit, "audit_universe", lambda config, root, start, end: {"assets": {}})
    monkeypatch.setattr(data_audit, "audit_non_daily_files", lambda config, root: {"num_files": 0})
    monkeypatch.setattr(data_audit, "build_data_manifest", lambda root: {"a.zip": {"size": 1, "sha256": "x"}})
    report = runners.run_audit_data({}, data_root=tmp_path, write_manifest=False)
    assert "manifest" not in report and report["non_daily_files"] == {"num_files": 0}
    written = runners.run_audit_data({}, data_root=tmp_path, start="2024-01-01", end="2024-12-31")
    assert written["manifest"]["num_files"] == 1 and json.loads((tmp_path / "manifest_v580.json").read_text(encoding="utf-8")) == {"a.zip": {"sha256": "x", "size": 1}}


def test_the_consumers_follow_the_config_switches():
    plain = runners.live_consumers({})
    assert "multitask.rank_20d" in plain and "gating" not in plain and "rl_sizing" not in plain
    switched = runners.live_consumers({"phase_v2": {"gating_network": {"learned_model_enabled": True}, "dynamic_risk": {"rl_sizing_enabled": True}, "forex_sleeve": {"rl_sizing_enabled": True}}})
    assert {"gating", "rl_sizing", "rl_sizing_forex"} <= switched


def test_the_head_audit_reads_the_metrics_it_can_and_ignores_a_torn_file(tmp_path, monkeypatch):
    import evaluation.head_audit as head_audit
    import portfolio.rank_signal as rank_signal

    (tmp_path / "sequence_training_metrics.json").write_text("{torn", encoding="utf-8")
    (tmp_path / "multitask_training_metrics.json").write_text(json.dumps({"ok": 1}), encoding="utf-8")
    monkeypatch.setattr(head_audit, "load_head_metrics", lambda folder: {})
    monkeypatch.setattr(head_audit, "audit_heads", lambda metrics, consumers: {"heads": {}})
    seen = {}
    monkeypatch.setattr(rank_signal, "resolve_rank_signal_policy", lambda metrics, config: seen.update(metrics=metrics) or {"policy": 1})
    report = runners.run_audit_heads({}, ml_dir=tmp_path)
    assert seen["metrics"] == {"sequence": None, "multitask": {"ok": 1}} and report["rank_signal_policy"] == {"policy": 1} and report["consumers"]


def test_the_feature_audit_reads_the_schema_columns_and_optionally_the_permutation_drop(tmp_path, monkeypatch):
    import evaluation.feature_quality_audit as quality
    import evaluation.model_predictions as predictions

    monkeypatch.setattr(runners, "ML_DIR", tmp_path)
    (tmp_path / "multitask_feature_schema.json").write_text(json.dumps({"model_input_names": ["f1", "f2"]}), encoding="utf-8")
    (tmp_path / "multitask_model.json").write_text("{}", encoding="utf-8")
    dataset = tmp_path / "full.csv"
    pd.DataFrame({"date": ["2025-01-02"] * 4, "ticker": ["AAA", "BBB", "AAA", "BBB"], "split": ["train", "train", "validation", "validation"], "f1": [1.0, 2.0, 3.0, 4.0], "f2": 0.5,
                  "target_rank_20d": [0.1, 0.2, 0.3, 0.4], "training_eligible": True, "unrelated": 9}).to_csv(dataset, index=False)
    config = {"phase1": {"universe": {"assets": [{"ticker": "AAA", "security_type": "equity"}, {"ticker": "BBB", "asset_class": "bond"}]}}}
    seen = {}
    monkeypatch.setattr(quality, "feature_quality", lambda frame, features: seen.update(columns=set(frame.columns), classes=list(frame["asset_class"])) or {"quality": 1})
    drops = {}

    def drop(validation, features, predict):
        drops["scores"] = predict(validation)
        return {"f1": 0.0}

    monkeypatch.setattr(quality, "permutation_ic_drop", drop)
    monkeypatch.setattr(predictions, "predict_multitask_head", lambda data, model, features, head: np.arange(len(data), dtype=float))
    plain = runners.run_audit_features(config, dataset_path=str(dataset))
    assert plain == {"quality": 1} and "unrelated" not in seen["columns"] and seen["classes"] == ["equity", "bond", "equity", "bond"]
    full = runners.run_audit_features(config, dataset_path=str(dataset), permutation=True)
    assert full["permutation_ic_drop"] == {"f1": 0.0} and list(drops["scores"]) == [0.0, 1.0]
    (tmp_path / "datasets").mkdir()
    pd.read_csv(dataset).to_csv(tmp_path / "datasets" / "full_dataset.csv", index=False)
    assert runners.run_audit_features(config) == {"quality": 1}
