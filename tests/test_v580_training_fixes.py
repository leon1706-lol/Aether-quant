"""V5.8.0 round file: training-pipeline changes (vectorised split assignment, ...)."""

from __future__ import annotations

import pandas as pd

import train

WINDOWS = {
    "training": {"start": "2014-12-01", "end": "2021-12-31"},
    "validation": {"start": "2022-01-01", "end": "2023-06-30"},
    "backtest": {"start": "2023-07-01", "end": "2025-06-30"},
}


def test_vectorised_split_assignment_equals_the_row_function_on_every_boundary():
    dates = pd.Series(pd.date_range("2014-11-20", "2025-07-10"))
    expected = dates.apply(lambda value: train.assign_split(value, WINDOWS))
    actual = train.assign_split_series(dates, WINDOWS)
    assert (expected.fillna("none") == actual.fillna("none")).all()
    assert actual.iloc[0] is None and actual.iloc[-1] is None


def test_compact_dataset_for_training_halves_floats_and_leaves_other_columns_alone():
    import numpy as np

    frame = pd.DataFrame({"ticker": ["A", "B"], "date": ["2024-01-02", "2024-01-03"], "x": [1.5, 2.5], "flag": [True, False],
                          "n": [1, 2]})
    compact = train.compact_dataset_for_training(frame.copy())
    assert compact["x"].dtype == np.float32 and list(compact["x"]) == [1.5, 2.5]
    assert compact["flag"].dtype == bool and compact["n"].dtype == frame["n"].dtype and list(compact["ticker"]) == ["A", "B"]


def test_resident_memory_reader_is_safe_on_any_platform():
    memory = train.resident_memory_mb()
    assert memory is None or (memory[0] > 0 and memory[1] >= memory[0] - 1)


def test_forward_in_batches_equals_the_single_pass_and_keeps_row_order():
    import torch

    import train_sequence

    class _TinyHeads(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.layer = torch.nn.Linear(3, 2)

        def forward(self, x):
            out = self.layer(x)
            return {"direction": out[:, 0], "magnitude": out[:, 1]}

    torch.manual_seed(0)
    model = _TinyHeads().eval()
    features = torch.randn(1000, 3)
    with torch.no_grad():
        expected = model(features)
    for batch_rows in (7, 256, 5000):
        actual = train_sequence.forward_in_batches(model, features, batch_rows=batch_rows)
        assert set(actual) == {"direction", "magnitude"}
        for head in expected:
            assert torch.allclose(actual[head], expected[head], atol=1e-6) and actual[head].shape == expected[head].shape
