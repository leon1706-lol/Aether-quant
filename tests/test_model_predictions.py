import numpy as np
import pandas as pd

from evaluation.model_predictions import (
    build_sequence_windows,
    predict_head,
    predict_multitask_head,
    predict_sequence_head,
    select_context_date_range,
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


def _two_ticker_range_frame():
    # Ticker A: 10 consecutive trading days. Ticker B: 6 rows, missing
    # 01-02 - deliberately different calendar-date sets per ticker, so
    # select_context_date_range() must resolve each ticker's own boundary
    # independently rather than assuming a shared calendar.
    dates_a = [f"2020-01-{day:02d}" for day in range(1, 11)]
    dates_b = ["2020-01-01", "2020-01-03", "2020-01-04", "2020-01-05", "2020-01-06", "2020-01-07"]
    frame = pd.concat(
        [
            pd.DataFrame({"ticker": ["A"] * len(dates_a), "date": dates_a, "f1": range(len(dates_a))}),
            pd.DataFrame({"ticker": ["B"] * len(dates_b), "date": dates_b, "f1": range(len(dates_b))}),
        ],
        ignore_index=True,
    )
    return frame


def test_select_context_date_range_spanning_full_range_is_a_no_op_trim():
    frame = _two_ticker_range_frame()
    all_dates = sorted(frame["date"].unique().tolist())
    min_date, max_date = select_context_date_range(frame, all_dates, window_size=4)
    assert min_date == all_dates[0]
    assert max_date == all_dates[-1]


def test_select_context_date_range_keeps_lookback_and_drops_the_rest():
    frame = _two_ticker_range_frame()
    recorded_dates = ["2020-01-05", "2020-01-06", "2020-01-07"]
    min_date, max_date = select_context_date_range(frame, recorded_dates, window_size=4)
    # Ticker A: 01-05 is at ordinal index 4; lookback of 4 -> starts at index 1 (01-02).
    # Ticker B: 01-05 is at ordinal index 3; lookback of 4 -> clamps to index 0 (01-01).
    # min_date is the earliest across both tickers.
    assert min_date == "2020-01-01"
    assert max_date == "2020-01-07"


def test_select_context_date_range_clamps_when_fewer_rows_precede_than_window_size():
    frame = _two_ticker_range_frame()
    # window_size (10) far exceeds either ticker's available preceding rows
    # for this early recorded date - must clamp to each ticker's own
    # earliest row, never negative-index or raise.
    min_date, max_date = select_context_date_range(frame, ["2020-01-03"], window_size=10)
    assert min_date == "2020-01-01"
    assert max_date == "2020-01-03"


def test_select_context_date_range_raises_on_empty_recorded_dates():
    frame = _two_ticker_range_frame()
    try:
        select_context_date_range(frame, [], window_size=4)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_naive_date_filtering_corrupts_sequence_windows_but_the_trimmed_range_does_not():
    # This is the single most important test in this module: it proves WHY
    # select_context_date_range() exists. build_sequence_windows() builds
    # each window from ordinal row position, not calendar dates, so naively
    # filtering a frame down to only the recorded dates silently builds
    # windows from whatever rows happen to be ordinally adjacent after the
    # filter - wrong, with no error raised.
    dates = [f"2020-01-{day:02d}" for day in range(1, 7)]  # d1..d6
    full_frame = pd.DataFrame({"ticker": ["A"] * 6, "date": dates, "f1": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]})
    window_size = 3
    recorded_dates = ["2020-01-05", "2020-01-06"]  # d5, d6

    ground_truth = build_sequence_windows(full_frame, ["f1"], window_size)
    ground_truth_recorded = ground_truth[full_frame["date"].isin(recorded_dates).to_numpy()]

    naive_frame = full_frame[full_frame["date"].isin(recorded_dates)].reset_index(drop=True)
    naive_windows = build_sequence_windows(naive_frame, ["f1"], window_size)

    min_date, max_date = select_context_date_range(full_frame, recorded_dates, window_size=window_size)
    assert (min_date, max_date) == ("2020-01-03", "2020-01-06")
    trimmed_frame = full_frame[(full_frame["date"] >= min_date) & (full_frame["date"] <= max_date)].reset_index(
        drop=True
    )
    trimmed_windows = build_sequence_windows(trimmed_frame, ["f1"], window_size)
    trimmed_recorded = trimmed_windows[trimmed_frame["date"].isin(recorded_dates).to_numpy()]

    assert not np.allclose(naive_windows, ground_truth_recorded)
    assert np.allclose(trimmed_recorded, ground_truth_recorded)
