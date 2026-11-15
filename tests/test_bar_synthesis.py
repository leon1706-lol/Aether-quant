"""data_pipeline/bar_synthesis.py (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

from data_pipeline.bar_synthesis import pad_sequence_history


def test_a_short_history_is_left_padded_with_zero_rows_and_a_full_one_is_kept():
    assert pad_sequence_history([[1.0, 2.0]], 3) == [[0.0, 0.0], [0.0, 0.0], [1.0, 2.0]]
    full = [[1.0], [2.0], [3.0], [4.0]]
    assert pad_sequence_history(full, 2) == full
