"""V6.1.0 seed ensembles: one averaging rule for live (per-symbol dicts) and offline (dataset arrays)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from evaluation.model_predictions import predict_heads, predict_heads_ensemble
from inference.exported_model import (
    average_head_outputs,
    load_ensemble_member_exports,
    resolve_model_ensemble_config,
    run_exported_multitask_model,
)


def _variant_multitask_model_export(scale: float) -> dict:
    """A shared linear->relu trunk with direction / magnitude heads; `scale` makes each ensemble member different."""
    state = {
        "trunk.0.weight": [[0.5, -0.25], [0.1, 0.3]], "trunk.0.bias": [0.1, -0.1],
        "head_direction.weight": [[0.3, -0.4]], "head_direction.bias": [0.05],
        "head_magnitude.weight": [[0.2, 0.1]], "head_magnitude.bias": [-0.02],
    }
    scaled = {
        key: [[value * scale for value in row] for row in array] if isinstance(array[0], list) else [value * scale for value in array]
        for key, array in state.items()
    }
    return {"export": {
        "trunk": [{"type": "linear", "weight_key": "trunk.0.weight", "bias_key": "trunk.0.bias"}, {"type": "relu"}],
        "heads": {
            "direction": [{"type": "linear", "weight_key": "head_direction.weight", "bias_key": "head_direction.bias"}, {"type": "sigmoid"}],
            "magnitude": [{"type": "linear", "weight_key": "head_magnitude.weight", "bias_key": "head_magnitude.bias"}],
        },
        "state_dict": scaled,
    }}


def test_heads_are_averaged_and_a_missing_member_value_drops_the_head():
    averaged = average_head_outputs([{"rank_20d": 0.2, "rank_5d": 1.0}, {"rank_20d": 0.4, "rank_5d": None}])
    assert averaged == {"rank_20d": pytest.approx(0.3), "rank_5d": None}
    assert average_head_outputs([None, {}]) is None
    assert average_head_outputs([{"rank_20d": 0.7}]) == {"rank_20d": 0.7}


def test_the_offline_ensemble_equals_the_live_average_row_by_row():
    members = [_variant_multitask_model_export(scale) for scale in (1.0, 0.7, 1.4)]
    frame = pd.DataFrame({"f0": [1.0, -0.5, 0.2], "f1": [0.3, 0.9, -1.1], "ticker": ["A", "B", "C"]})
    heads = ["direction", "magnitude"]
    offline = predict_heads_ensemble(frame, members, ["f0", "f1"], heads, model_kind="multitask")
    for row in range(len(frame)):
        inputs = frame.loc[row, ["f0", "f1"]].tolist()
        live = average_head_outputs([run_exported_multitask_model(member, inputs) for member in members])
        for head in heads:
            assert offline[head][row] == pytest.approx(live[head], abs=1e-12)
    single = predict_heads(frame, members[0], ["f0", "f1"], heads, model_kind="multitask")
    one = predict_heads_ensemble(frame, members[:1], ["f0", "f1"], heads, model_kind="multitask")
    for head in heads:
        np.testing.assert_allclose(one[head], single[head], rtol=0, atol=0)


def test_members_load_sorted_and_the_switch_defaults_off(tmp_path):
    (tmp_path / "b.json").write_text(json.dumps({"id": "b"}), encoding="utf-8")
    (tmp_path / "a.json").write_text(json.dumps({"id": "a"}), encoding="utf-8")
    assert [member["id"] for member in load_ensemble_member_exports(tmp_path)] == ["a", "b"]
    assert load_ensemble_member_exports(tmp_path / "missing") == []
    assert resolve_model_ensemble_config({})["enabled"] is False
    assert resolve_model_ensemble_config({})["multitask_dir"] == "multitask_ensemble"
