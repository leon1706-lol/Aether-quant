"""retraining/slicing.sequence_window_index against its Lean 4 model (formal/AetherFormal/WindowIndex.lean), V6.6.10: the lazy
sequence windows read no later row and no other ticker's row."""

from __future__ import annotations

import numpy as np

from aether_quant.formal import load_cases
from retraining.slicing import sequence_window_index


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("window_index")["cases"]):
        given = case["input"]
        got = sequence_window_index(np.asarray(given["tickers"]), given["window"])
        assert got.tolist() == case["expected"]["index"], index
