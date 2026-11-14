"""train_topology.py's command and dataset path (V6.6.6, #359): argument parsing, the dataset events, the Postgres events, and the artifacts written
or skipped. The multitask head and Postgres are stubbed."""

from __future__ import annotations

import json
import sys
from types import ModuleType
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

import train_topology as topology


def test_arguments_default_to_postgres_and_accept_a_dataset(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["train_topology", "--version-id", "v1"])
    args = topology.parse_args()
    assert args.version_id == "v1" and args.source == "postgres" and args.max_rows == 60_000
    monkeypatch.setattr(sys, "argv", ["train_topology", "--version-id", "v1", "--source", "dataset", "--dataset-path", "d.csv", "--max-rows", "10"])
    assert topology.parse_args().max_rows == 10


def test_a_non_numeric_regime_flag_is_false_and_the_label_needs_a_trend_and_a_volatility():
    assert topology.primary_regime_label({"regime_trend_bullish": "x", "regime_volatility_high": 1}) == "unknown"
    row = {"regime_trend_bullish": 1.0, "regime_volatility_high": 1.0}
    assert topology.primary_regime_label(row) == "bullish_high_volatility" and topology.primary_regime_label({**row, "regime_risk_off": 1.0}) == "bullish_risk_off"


def test_the_dataset_events_are_scored_by_the_multitask_head(tmp_path, monkeypatch):
    import evaluation.model_predictions as model_predictions

    monkeypatch.setattr(topology, "ML_DIR", tmp_path)
    (tmp_path / "multitask_feature_schema.json").write_text(json.dumps({"model_input_names": ["x"]}), encoding="utf-8")
    (tmp_path / "multitask_model.json").write_text("{}", encoding="utf-8")
    rows = 30
    frame = pd.DataFrame({"x": np.linspace(0, 1, rows), "rolling_volatility_20d": 0.02, "close": 10.0, "volume": 1000.0, "target_return_20d": np.linspace(-0.05, 0.05, rows),
                          "topology_correlation_strength": 0.3, "liquidity_spread_proxy": 0.001, "regime_signal_risk_score": 0.2, "regime_trend_bullish": 1.0, "regime_volatility_normal": 1.0,
                          "training_eligible": [True] * (rows - 2) + [False, False], "date": "2024-01-02"})
    frame.loc[3, "target_return_20d"] = np.nan
    dataset = tmp_path / "train.csv"
    frame.to_csv(dataset, index=False)
    monkeypatch.setattr(model_predictions, "predict_multitask_head", lambda data, model, names, head: np.full(len(data), 0.6))
    vectors, outcomes, regimes = topology.load_dataset_events(dataset, max_rows=10)
    assert len(vectors) == 10 and set(outcomes) <= {"win", "loss"} and set(regimes) == {"bullish_normal_volatility"}
    everything = topology.load_dataset_events(dataset, max_rows=100)
    assert len(everything[0]) == rows - 3


def test_the_training_block_comes_from_the_config(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"phase_v2": {"topology_learning": {"training": {"num_prototypes": 3}}}}), encoding="utf-8")
    assert topology.load_topology_learning_config(config) == {"num_prototypes": 3}


def test_outcomes_skip_tickerless_events_and_label_a_realisation_with_no_open_trade():
    events = [{"ticker": None}, {"ticker": "A", "portfolio": {"last_realized_pnl": 5.0}}, {"ticker": "A", "action": "trade", "signal": "buy"}, {"ticker": "B"}, {"ticker": "A", "portfolio": {"last_realized_pnl": -1.0}}]
    assert topology.derive_realized_outcomes(events) == [None, "win", "loss", None, "loss"]


def _event(index):
    return {"ticker": "A", "topology": {"volatility_pressure": 0.1 * (index % 5), "correlation_strength": 0.2}, "probability_up": 0.5 + 0.01 * (index % 7), "regime": {"primary_regime": "bullish"},
            "liquidity": {}, "portfolio": {"last_realized_pnl": 1.0 if index % 2 else -1.0}, "action": "trade", "signal": "buy"}


def _args(tmp_path, source="postgres", version="v1"):
    return type("Args", (), {"config_path": str(tmp_path / "config.json"), "source": source, "dataset_path": "d.csv", "max_rows": 10, "version_id": version, "postgres_dsn": ""})()


def _config(tmp_path, minimum=3):
    (tmp_path / "config.json").write_text(json.dumps({"phase_v2": {"topology_learning": {"training": {"min_training_events": minimum, "num_prototypes": 2}}}}), encoding="utf-8")


def test_the_postgres_run_writes_the_three_artifacts_or_skips_when_events_are_few(tmp_path, monkeypatch):
    _config(tmp_path, minimum=3)
    monkeypatch.setattr(topology, "ML_DIR", tmp_path / "ml")
    monkeypatch.setattr(topology, "parse_args", lambda: _args(tmp_path))
    stand_in = ModuleType("psycopg")
    conn = MagicMock()
    stand_in.connect = lambda dsn, autocommit: conn
    monkeypatch.setitem(sys.modules, "psycopg", stand_in)
    monkeypatch.setattr(topology, "secret_env", lambda name, default="": "dsn")
    events = [_event(index) for index in range(12)] + [{"ticker": "A", "topology": None}]
    monkeypatch.setattr(topology, "fetch_recent_events", lambda connection, limit, since: events)
    assert topology.main() == 0 and conn.close.called
    for name in ("topology_model.json", "topology_feature_schema.json", "topology_training_metrics.json"):
        assert (tmp_path / "ml" / "versions" / "v1" / name).exists()
    _config(tmp_path, minimum=500)
    assert topology.main() == 0
    assert not (tmp_path / "ml" / "versions" / "v1" / "never.json").exists()


def test_the_dataset_run_uses_the_dataset_events_and_a_failure_is_reported(tmp_path, monkeypatch):
    _config(tmp_path, minimum=3)
    monkeypatch.setattr(topology, "ML_DIR", tmp_path / "ml")
    monkeypatch.setattr(topology, "parse_args", lambda: _args(tmp_path, source="dataset", version="v2"))
    vectors = [{"volatility": 0.1 * index, "momentum": 0.01, "correlation_strength": 0.2, "liquidity_score": 0.9, "regime_risk_score": 0.1} for index in range(8)]
    monkeypatch.setattr(topology, "load_dataset_events", lambda path, max_rows: (vectors, ["win", "loss"] * 4, ["bullish"] * 8))
    assert topology.main() == 0 and (tmp_path / "ml" / "versions" / "v2" / "topology_model.json").exists()
    monkeypatch.setattr(topology, "load_dataset_events", lambda path, max_rows: (_ for _ in ()).throw(RuntimeError("bad dataset")))
    assert topology.main() == 1


def test_the_module_runs_as_a_script(monkeypatch):
    import runpy

    monkeypatch.setattr(sys, "argv", ["train_topology", "--help"])
    monkeypatch.delitem(sys.modules, "train_topology", raising=False)
    with pytest.raises(SystemExit):
        runpy.run_module("train_topology", run_name="__main__")
