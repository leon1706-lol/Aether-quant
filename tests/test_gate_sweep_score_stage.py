"""scripts/gate_sweep_score_stage.py (V6.6.6): blended raw scores from 2019 on, cached to CSV, with stand-in predictions."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from script_loader import Stop, load_script, run_script, stop_at_first_read


def _ml(tmp_path, *, with_sequence_metrics):
    ml = tmp_path / "ml"
    (ml / "datasets").mkdir(parents=True)
    pd.DataFrame({"date": ["2018-12-31", "2019-01-02", "2019-01-03"], "ticker": ["A", "A", "B"]}).to_csv(ml / "datasets" / "full_dataset.csv", index=False)
    (ml / "multitask_training_metrics.json").write_text("{}", encoding="utf-8")
    if with_sequence_metrics:
        (ml / "sequence_training_metrics.json").write_text("{}", encoding="utf-8")
    for name in ("mt", "seq"):
        (ml / f"{name}_model.json").write_text("{}", encoding="utf-8")
        (ml / f"{name}_schema.json").write_text(json.dumps({"model_input_names": ["x"]}), encoding="utf-8")
    (tmp_path / "config.json").write_text(json.dumps({"phase_v2": {"sequence_model": {"window_size": 7}}}), encoding="utf-8")
    return ml


@pytest.mark.parametrize("priority", [["sequence", "multitask"], ["sequence"]])
def test_scores_are_blended_and_cached(tmp_path, monkeypatch, capsys, priority):
    module = load_script("gate_sweep_score_stage")
    ml = _ml(tmp_path, with_sequence_metrics=priority == ["sequence"])
    monkeypatch.setattr(module, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(module, "ML_DIR", ml)
    import aq_cli
    import evaluation
    import portfolio.rank_signal as rank_signal

    monkeypatch.setattr(aq_cli, "_EVALUATE_MODEL_ARTIFACTS", {"multitask": ("mt_model.json", "mt_schema.json"), "sequence": ("seq_model.json", "seq_schema.json")})
    monkeypatch.setattr(rank_signal, "resolve_rank_signal_policy", lambda metrics, config: {"model_priority": list(priority), "heads": {"rank": 1.0, "off": 0.0}})
    calls = []

    def predict_head(dataset, export, names, head, *, model_kind, sequence_feature_schema, configured_window_size):
        calls.append((model_kind, head, sequence_feature_schema is not None, configured_window_size))
        return [0.1] * len(dataset)

    monkeypatch.setattr(evaluation, "predict_head", predict_head)
    monkeypatch.setattr(evaluation, "compute_blended_raw_scores", lambda dataset, predictions, policy: [float(len(predictions))] * len(dataset))
    assert module.main() == 0
    scored = pd.read_csv(ml / "evaluation" / "gate_sweep_scored.csv")
    assert list(scored["date"]) == ["2019-01-02", "2019-01-03"] and list(scored.columns) == ["date", "ticker", "raw_blended_score"]
    expected = [("multitask", "rank", False, 7)] if "multitask" in priority else [("sequence", "rank", True, 7)]
    assert calls == expected and "rows in scope: 2" in capsys.readouterr().out


def test_run_as_a_script_it_stops_at_its_first_read(monkeypatch):
    stop_at_first_read(monkeypatch)
    with pytest.raises(Stop, match="config.json"):
        run_script("gate_sweep_score_stage", [], monkeypatch)
