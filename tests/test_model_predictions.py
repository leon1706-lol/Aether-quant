import numpy as np
import pandas as pd

from evaluation.model_predictions import (
    build_sequence_windows,
    predict_head,
    predict_multitask_head,
    predict_sequence_head,
)


def _synthetic_multitask_model_export() -> dict:
    """Same shared linear->relu trunk fixture tests/test_exported_model.py
    uses, plus a 3rd head (rank_20d, NO activation - V5.1 Phase 1's Finding-1
    fix: rank heads switch from sigmoid to raw) so this module's dispatch
    onto an arbitrary `head` name is exercised, not just the always-present
    direction/magnitude/volatility trio."""
    return {
        "export": {
            "trunk": [
                {"type": "linear", "weight_key": "trunk.0.weight", "bias_key": "trunk.0.bias"},
                {"type": "relu"},
            ],
            "heads": {
                "magnitude": [
                    {"type": "linear", "weight_key": "head_magnitude.weight", "bias_key": "head_magnitude.bias"},
                ],
                "rank_20d": [
                    {"type": "linear", "weight_key": "head_rank_20d.weight", "bias_key": "head_rank_20d.bias"},
                ],
            },
            "state_dict": {
                "trunk.0.weight": [[0.5, -0.25], [0.1, 0.3]],
                "trunk.0.bias": [0.1, -0.1],
                "head_magnitude.weight": [[0.2, 0.1]],
                "head_magnitude.bias": [-0.02],
                "head_rank_20d.weight": [[0.3, -0.1]],
                "head_rank_20d.bias": [0.4],
            },
        }
    }


def _synthetic_sequence_model_export() -> dict:
    return {
        "export": {
            "trunk": [
                {"type": "conv1d_causal", "weight_key": "conv.weight", "bias_key": "conv.bias", "dilation": 1},
                {"type": "relu"},
            ],
            "heads": {
                "rank_5d": [
                    {"type": "linear", "weight_key": "head_rank_5d.weight", "bias_key": "head_rank_5d.bias"},
                ],
            },
            "state_dict": {
                "conv.weight": [[[0.5, -0.5], [0.2, 0.1]]],
                "conv.bias": [0.05],
                "head_rank_5d.weight": [[0.3]],
                "head_rank_5d.bias": [0.1],
            },
        }
    }


def _multitask_frame(num_rows=6):
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {"f1": rng.normal(size=num_rows), "f2": rng.normal(size=num_rows), "ticker": ["T0"] * num_rows}
    )


def test_predict_multitask_head_matches_direct_interpreter_call():
    from inference.exported_model import run_exported_multitask_model

    frame = _multitask_frame(num_rows=4)
    model_export = _synthetic_multitask_model_export()

    predictions = predict_multitask_head(frame, model_export, ["f1", "f2"], "rank_20d")

    for row_index in range(len(frame)):
        expected = run_exported_multitask_model(model_export, frame[["f1", "f2"]].iloc[row_index].tolist())
        assert predictions[row_index] == expected["rank_20d"]


def test_predict_multitask_head_unknown_head_returns_nan():
    frame = _multitask_frame(num_rows=2)
    model_export = _synthetic_multitask_model_export()
    predictions = predict_multitask_head(frame, model_export, ["f1", "f2"], "does_not_exist")
    assert np.isnan(predictions).all()


def test_build_sequence_windows_matches_train_py_implementation():
    import train

    rng = np.random.default_rng(1)
    frame = pd.DataFrame(
        {
            "ticker": ["A"] * 8 + ["B"] * 5,
            "f1": rng.normal(size=13),
            "f2": rng.normal(size=13),
        }
    )

    mirrored = build_sequence_windows(frame, ["f1", "f2"], window_size=4)
    reference = train.build_sequence_tensor_dataset(frame, ["f1", "f2"], window_size=4)

    assert mirrored.shape == reference.shape
    assert np.allclose(mirrored, reference.astype(np.float64), atol=1e-6)


def test_build_sequence_windows_left_pads_short_histories_with_zeros():
    frame = pd.DataFrame({"ticker": ["A", "A"], "f1": [1.0, 2.0]})
    windows = build_sequence_windows(frame, ["f1"], window_size=5)
    # Row 0 (first bar ever seen for A) has only itself - 4 leading zeros.
    assert list(windows[0, :, 0]) == [0.0, 0.0, 0.0, 0.0, 1.0]
    assert list(windows[1, :, 0]) == [0.0, 0.0, 0.0, 1.0, 2.0]


def test_predict_sequence_head_matches_direct_interpreter_call():
    from inference.exported_model import run_exported_sequence_multitask_model

    frame = pd.DataFrame({"ticker": ["A"] * 3, "f1": [0.5, -0.2, 0.1], "f2": [0.1, 0.2, -0.3]})
    model_export = _synthetic_sequence_model_export()

    predictions = predict_sequence_head(
        frame, model_export, ["f1", "f2"], "rank_5d",
        sequence_feature_schema={"window_size": 2}, configured_window_size=2,
    )

    windows = build_sequence_windows(frame, ["f1", "f2"], window_size=2)
    expected_last_row = run_exported_sequence_multitask_model(model_export, windows[-1].tolist())
    assert predictions[-1] == expected_last_row["rank_5d"]


def test_predict_sequence_head_window_size_comes_from_the_models_own_schema():
    # resolve_sequence_window_size() prefers the trained model's OWN
    # window_size over the configured default - a mismatch there used to
    # silently disable the sequence signal (see that function's docstring).
    frame = pd.DataFrame({"ticker": ["A"] * 3, "f1": [0.5, -0.2, 0.1], "f2": [0.1, 0.2, -0.3]})
    model_export = _synthetic_sequence_model_export()

    # configured_window_size deliberately wrong (10); schema's window_size (2) must win.
    predictions = predict_sequence_head(
        frame, model_export, ["f1", "f2"], "rank_5d",
        sequence_feature_schema={"window_size": 2}, configured_window_size=10,
    )
    assert not np.isnan(predictions).any()


def test_predict_head_dispatches_on_model_kind():
    multitask_frame = _multitask_frame(num_rows=3)
    multitask_export = _synthetic_multitask_model_export()
    via_dispatch = predict_head(multitask_frame, multitask_export, ["f1", "f2"], "rank_20d", model_kind="multitask")
    direct = predict_multitask_head(multitask_frame, multitask_export, ["f1", "f2"], "rank_20d")
    assert np.array_equal(via_dispatch, direct, equal_nan=True)


def test_predict_head_unknown_model_kind_raises_value_error():
    frame = _multitask_frame(num_rows=1)
    model_export = _synthetic_multitask_model_export()
    try:
        predict_head(frame, model_export, ["f1", "f2"], "rank_20d", model_kind="not_a_real_kind")
        assert False, "expected ValueError"
    except ValueError:
        pass
