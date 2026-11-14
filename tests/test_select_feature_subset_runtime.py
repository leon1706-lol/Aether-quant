"""scripts/select_feature_subset.py's `main()` (V6.6.6, #359): the train-split-only subset choice, with the audit's permutation and quality functions and the model pass
stood in. The train-only reading, the halves, the report and the subset schema are the script's own."""

from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd
import pytest

from script_loader import load_script


@pytest.fixture
def module(monkeypatch, tmp_path):
    script = load_script("select_feature_subset")
    monkeypatch.setattr(script, "ROOT_DIR", tmp_path)
    ml = tmp_path / "ml"
    ml.mkdir()
    (ml / "multitask_feature_schema.json").write_text(json.dumps({"model_input_names": ["f_a", "f_b", "f_c"], "other": 1}), encoding="utf-8")
    (ml / "multitask_model.json").write_text("{}", encoding="utf-8")
    (tmp_path / "config.json").write_text(json.dumps({"phase1": {"universe": {"assets": [{"ticker": "AAA", "asset_class": "equity"}, {"ticker": "BTCUSD", "security_type": "crypto"}]}}}), encoding="utf-8")
    dates = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2017-01-02", "2021-12-30", freq="7D")]
    rng = np.random.default_rng(1)
    rows = [{"date": date, "ticker": ticker, "split": "train", "training_eligible": True, "target_rank_20d": rng.random(), "f_a": rng.random(), "f_b": rng.random(), "f_c": rng.random(), "unused": 1}
            for date in dates for ticker in ("AAA", "BTCUSD")]
    rows.append({"date": "2022-01-03", "ticker": "AAA", "split": "validation", "training_eligible": True, "target_rank_20d": 0.1, "f_a": 0.1, "f_b": 0.1, "f_c": 0.1, "unused": 1})
    rows.append({"date": "2018-01-03", "ticker": "AAA", "split": "train", "training_eligible": False, "target_rank_20d": 0.1, "f_a": 0.1, "f_b": 0.1, "f_c": 0.1, "unused": 1})
    pd.DataFrame(rows).to_csv(tmp_path / "dataset.csv", index=False)
    return script


def test_the_subset_is_chosen_on_the_train_split_and_written_with_its_schema(module, monkeypatch, tmp_path, capsys):
    import evaluation.feature_quality_audit as audit
    import evaluation.model_predictions as predictions

    seen = {}
    monkeypatch.setattr(audit, "feature_quality", lambda train, features, target: seen.update(splits=len(train)) or {"flags": {"ticker_id_suspects": ["f_c"]}})
    monkeypatch.setattr(audit, "_daily_ic", lambda frame, column, target, date_column, min_names: float(frame[column].mean() - 0.5))
    monkeypatch.setattr(predictions, "predict_heads", lambda data, model, features, heads, model_kind, batched: {"rank_20d": np.zeros(len(data))})
    monkeypatch.setattr(audit, "permutation_ic_drop", lambda window, features, predict, target: seen.update(window=len(window), predicted=len(predict(window))) or {"f_a": 0.01, "f_b": -0.01, "f_c": 0.02})
    monkeypatch.setattr(audit, "select_feature_subset", lambda features, permutation_drop, early_ic, late_ic, ticker_id_suspects: {"kept": ["f_a"], "dropped": {"f_b": "no drop", "f_c": "ticker id"}})
    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["select_feature_subset", "--dataset", str(tmp_path / "dataset.csv"), "--out-dir", str(out_dir)])
    assert module.main() == 0
    report = json.loads((out_dir / "feature_subset.json").read_text(encoding="utf-8"))
    schema = json.loads((out_dir / "feature_schema_subset.json").read_text(encoding="utf-8"))
    assert report["kept"] == ["f_a"] and report["n_features"] == 3 and report["n_kept"] == 1 and report["ticker_id_suspects"] == ["f_c"] and set(report["early_ic"]) == {"f_a", "f_b", "f_c"}
    assert schema["model_input_names"] == ["f_a"] and schema["other"] == 1 and seen["window"] > 0 and seen["predicted"] == seen["window"] and "kept 1 of 3 features" in capsys.readouterr().out
    assert seen["splits"] == len(pd.read_csv(tmp_path / "dataset.csv").query("split == 'train' and training_eligible"))
