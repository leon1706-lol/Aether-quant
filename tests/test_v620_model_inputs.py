"""V6.2.0 regularised retrain: rank-label noise in the trainers and per-model input subsets that live and offline agree on."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from evaluation.model_predictions import predict_heads
from inference.exported_model import (
    export_input_names,
    model_input_index,
    run_exported_multitask_model,
    select_model_inputs,
    select_sequence_inputs,
)


def _two_input_export(feature_names: list[str] | None) -> dict:
    export = {"export": {
        "trunk": [{"type": "linear", "weight_key": "w", "bias_key": "b"}, {"type": "relu"}],
        "heads": {"rank_20d": [{"type": "linear", "weight_key": "hw", "bias_key": "hb"}]},
        "state_dict": {"w": [[0.5, -0.25], [0.1, 0.3]], "b": [0.1, -0.1], "hw": [[0.3, -0.4]], "hb": [0.05]},
    }}
    if feature_names is not None:
        export["model"] = {"model_input_features": feature_names}
    return export


def test_the_full_vector_passes_through_untouched_and_a_subset_selects_in_the_models_order():
    full = ["a", "b", "c", "d"]
    assert model_input_index(_two_input_export(None), full) is None
    assert model_input_index(_two_input_export(full), full) is None
    assert model_input_index(_two_input_export(["d", "b"]), full) == [3, 1]
    inputs = [1.0, 2.0, 3.0, 4.0]
    assert select_model_inputs(inputs, None) is inputs
    assert select_model_inputs(inputs, [3, 1]) == [4.0, 2.0]
    sequence = [[1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0]]
    assert select_sequence_inputs(sequence, None) is sequence
    assert select_sequence_inputs(sequence, [0, 2]) == [[1.0, 3.0], [5.0, 7.0]]
    assert export_input_names({}, full) == full


def test_a_model_needing_a_feature_live_never_builds_is_refused():
    with pytest.raises(ValueError, match="not in the live feature vector"):
        model_input_index(_two_input_export(["a", "zz"]), ["a", "b"])


def test_a_subset_model_scores_the_same_offline_and_through_the_live_selection():
    full = ["f0", "f1", "f2"]
    export = _two_input_export(["f2", "f0"])
    frame = pd.DataFrame({"f0": [1.0, -0.5, 0.2], "f1": [9.0, 9.0, 9.0], "f2": [0.3, 0.9, -1.1], "ticker": ["A", "B", "C"]})
    offline = predict_heads(frame, export, full, ["rank_20d"], model_kind="multitask")
    batched = predict_heads(frame, export, full, ["rank_20d"], model_kind="multitask", batched=True)
    index = model_input_index(export, full)
    for row in range(len(frame)):
        live = run_exported_multitask_model(export, select_model_inputs(frame.loc[row, full].tolist(), index))
        assert offline["rank_20d"][row] == pytest.approx(live["rank_20d"], abs=1e-12)
        assert batched["rank_20d"][row] == pytest.approx(live["rank_20d"], abs=1e-12)


def test_rank_label_noise_is_off_by_default_seeded_and_touches_only_finite_rank_targets():
    torch = pytest.importorskip("torch")
    from train import HORIZON_HEAD_SPECS, add_rank_label_noise

    targets = {
        "rank_20d": torch.tensor([0.1, 0.5, float("nan"), 0.9]),
        "direction_5d": torch.tensor([0.0, 1.0, 1.0, 0.0]),
    }
    assert add_rank_label_noise(targets, HORIZON_HEAD_SPECS, 0.0, None) is targets
    first = add_rank_label_noise(targets, HORIZON_HEAD_SPECS, 0.5, torch.Generator().manual_seed(3))
    second = add_rank_label_noise(targets, HORIZON_HEAD_SPECS, 0.5, torch.Generator().manual_seed(3))
    np.testing.assert_array_equal(first["rank_20d"].numpy(), second["rank_20d"].numpy())
    assert torch.isnan(first["rank_20d"][2])
    finite = first["rank_20d"][[0, 1, 3]]
    assert float(finite.min()) >= 0.1 and float(finite.max()) <= 0.9
    assert not torch.equal(finite, targets["rank_20d"][[0, 1, 3]])
    assert first["direction_5d"] is targets["direction_5d"]
