"""scripts/build_legacy_probability.py's `main()` (V6.6.6, #359): the legacy signal's probability for every row of a split, with and without the components file,
with one or several sequence members and with only some regime experts on disk. The model passes are stood in; the dataset, schemas and gating call are real."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from script_loader import ROOT, load_script

FEATURES = ["f_a", "f_b", "topology_correlation_strength"]


@pytest.fixture
def module(monkeypatch, tmp_path):
    script = load_script("build_legacy_probability")
    monkeypatch.setattr(script, "ROOT_DIR", tmp_path)
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    ml = tmp_path / "ml"
    (ml / "expert_models" / "bullish").mkdir(parents=True)
    (ml / "expert_models" / "bearish").mkdir(parents=True)
    for name, content in (("feature_schema.json", {"model_input_names": ["f_a", "f_b"], "feature_names": FEATURES + ["not_in_frame"]}), ("sequence_feature_schema.json", {"model_input_names": ["f_a", "f_b"]}),
                          ("model_weights.json", {"base": 1}), ("sequence_model.json", {"seq": 1})):
        (ml / name).write_text(json.dumps(content), encoding="utf-8")
    (ml / "expert_models" / "bullish" / "model_weights.json").write_text(json.dumps({"expert": "bullish"}), encoding="utf-8")
    (ml / "expert_models" / "bearish" / "model_weights.json").write_text(json.dumps({"expert": "bearish"}), encoding="utf-8")
    start = pd.Timestamp(config["phase1"]["windows"]["validation"]["start"])
    dates = pd.bdate_range(start - pd.Timedelta(days=75), periods=70)
    rows = [{"date": date.strftime("%Y-%m-%d"), "ticker": ticker, "split": "validation" if date >= start else "train", "f_a": 0.1, "f_b": 0.2, "topology_correlation_strength": 0.4}
            for date in dates for ticker in ("AAA", "BBB")]
    pd.DataFrame(rows).to_csv(tmp_path / "dataset.csv", index=False)
    return script


def _stand_ins(monkeypatch, module, *, nan_direction_at=None):
    import evaluation.model_predictions as predictions
    import inference.exported_model as exported
    import regime.market_regime as regime

    monkeypatch.setattr(exported, "convert_state_dict_arrays", lambda export: export.update(converted=True))
    monkeypatch.setattr(exported, "run_exported_model_rows", lambda export, rows: [0.5 + (0.1 if export.get("expert") == "bullish" else 0.0)] * len(rows))
    seen = {}

    def ensemble(frame, exports, names, heads, model_kind, sequence_feature_schema, configured_window_size, batched):
        seen["members"] = len(exports)
        direction = np.full(len(frame), 0.6)
        if nan_direction_at is not None:
            direction[nan_direction_at] = np.nan
        return {"direction": direction}

    monkeypatch.setattr(predictions, "predict_heads_ensemble", ensemble)
    monkeypatch.setattr(module, "legacy_probability", lambda raw, baseline, experts, seq, metrics, config: 0.55 if seq is not None else 0.45)
    monkeypatch.setattr(regime, "build_market_regime_vector", lambda raw, **kwargs: SimpleNamespace(to_dict=lambda: {"trend_regime": "up", "volatility_regime": "low", "risk_regime": "risk_on"}))
    return seen


def _argv(tmp_path, *extra):
    return ["build_legacy_probability", "--dataset", str(tmp_path / "dataset.csv"), "--ml-dir", str(tmp_path / "ml"), "--out", str(tmp_path / "out" / "legacy.csv"), *extra]


def test_every_row_of_the_split_gets_a_probability(module, monkeypatch, tmp_path, capsys):
    seen = _stand_ins(monkeypatch, module, nan_direction_at=60)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, "--splits", "validation"))
    assert module.main() == 0
    written = pd.read_csv(tmp_path / "out" / "legacy.csv")
    assert set(written.columns) == {"date", "ticker", "final_probability_up"} and len(written) > 0 and seen["members"] == 1
    assert set(written["final_probability_up"]) <= {0.55, 0.45} and "written" in capsys.readouterr().out


def test_the_components_file_holds_each_rows_gating_inputs_and_members_are_averaged(module, monkeypatch, tmp_path):
    seen = _stand_ins(monkeypatch, module)
    for index in range(2):
        folder = tmp_path / "members" / f"m{index}"
        folder.mkdir(parents=True)
        (folder / "sequence_model.json").write_text(json.dumps({"seq": index}), encoding="utf-8")
    (tmp_path / "ml" / "expert_training_metrics.json").write_text(json.dumps({"bullish": {"x": 1}}), encoding="utf-8")
    components = tmp_path / "out" / "components.csv"
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, "--splits", "validation", "--emit-components", str(components), "--sequence-members", str(tmp_path / "members" / "m0"), str(tmp_path / "members" / "m1")))
    assert module.main() == 0
    frame = pd.read_csv(components)
    assert seen["members"] == 2 and {"baseline", "bullish", "bearish", "sequence_direction", "trend_regime", "volatility_regime", "risk_regime"} <= set(frame.columns)
    assert frame["bullish"].notna().all() and frame["sideways"].isna().all() and (frame["baseline"] == 0.5).all()
