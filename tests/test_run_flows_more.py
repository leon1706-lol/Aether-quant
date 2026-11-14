"""Run-folder flows of evaluation/ on a synthetic Lean world (V6.6.6, #359): classification parity and the paper protocol's per-run metrics."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from evaluation import classification_parity, paper_protocol
from synthetic_lean import PROBABILITY_SOURCE, SESSIONS, build_world


@pytest.fixture
def world(tmp_path):
    return build_world(tmp_path)


def test_the_paper_metrics_of_a_run_come_with_its_table_and_slippage(world):
    result = paper_protocol.paper_metrics_for_run_dir(world.run_dir, world.config, world.root)
    assert result["table"] and result["rebalances"] and result["book_history"].endswith("20240401T000000Z.jsonl") and "metrics" in result
    assert set(result["slippage_by_date"]) <= set(SESSIONS)


def test_a_target_weights_run_without_history_counts_fill_days_as_rebalances(world):
    world.history_path.unlink()
    config = {**world.config, "phase_v2": {**world.config["phase_v2"], "target_weights": {"enabled": True}}}
    result = paper_protocol.paper_metrics_for_run_dir(world.run_dir, config, world.root, start=SESSIONS[0], end=SESSIONS[-1])
    assert result["book_history"] is None and all(item["allocations"] == {"filled": True} for item in result["rebalances"]) and result["rebalances"]
    again = paper_protocol.paper_metrics_for_run_dir(world.run_dir, world.config, world.root)
    assert again["rebalances"] == []


def _model_files(root):
    ml = root / "ml"
    (ml / "datasets").mkdir(parents=True)
    (ml / "multitask_model.json").write_text("{}", encoding="utf-8")
    (ml / "multitask_feature_schema.json").write_text(json.dumps({"model_input_names": ["x"]}), encoding="utf-8")
    rows = [{"date": day, "ticker": ticker, "x": 0.1} for day in SESSIONS for ticker in ("AAA", "BTCUSD", "ZZZ")]
    pd.DataFrame(rows).to_csv(ml / "datasets" / "full_dataset.csv", index=False)
    return ml


def test_classification_parity_names_why_it_cannot_judge(world, monkeypatch):
    unsupported = classification_parity.classification_parity_for_run_dir(world.run_dir, world.config, world.root, source="mystery")
    assert unsupported["status"] == "unsupported_source"
    lonely = world.root / "backtests" / "1999-01-01_00-00-00"
    lonely.mkdir()
    assert classification_parity.classification_parity_for_run_dir(lonely, world.config, world.root, source=PROBABILITY_SOURCE)["status"] == "no_book_history"
    records = [json.loads(line) for line in world.history_path.read_text(encoding="utf-8").splitlines()]
    for record in records:
        record.pop("member_probabilities")
    world.history_path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
    assert classification_parity.classification_parity_for_run_dir(world.run_dir, world.config, world.root)["status"] == "no_logged_probabilities"


def test_classification_parity_scores_the_head_offline_and_compares_with_the_logged_probability(world, monkeypatch):
    import evaluation.model_predictions as model_predictions

    ml = _model_files(world.root)
    monkeypatch.setattr(model_predictions, "predict_head", lambda frame, export, names, head, **kwargs: np.where(frame["ticker"].astype(str).str.upper() == "AAA", 0.6, 0.4))
    result = classification_parity.classification_parity_for_run_dir(world.run_dir, world.config, world.root, ml_dir=ml)
    assert result["status"] == "ok" and result["model"] == "multitask" and result["head"] == "direction_20d" and "within_tolerance" in result
    explicit = classification_parity.classification_parity_for_run_dir(world.run_dir, world.config, world.root, dataset_path=str(ml / "datasets" / "full_dataset.csv"), ml_dir=str(ml), source=PROBABILITY_SOURCE)
    assert explicit["status"] == "ok"


def test_a_forex_traded_name_is_converted_to_dollars(world):
    config = json.loads(json.dumps(world.config))
    config["phase1"]["universe"]["assets"][1]["asset_class"] = "forex"
    result = paper_protocol.paper_metrics_for_run_dir(world.run_dir, config, world.root)
    assert result["table"]
