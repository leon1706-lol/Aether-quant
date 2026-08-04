"""Loads an exported model (ml/{multitask,sequence}_model.json) plus the
active dataset, and runs every row through inference/exported_model.py -
the EXACT torch-free interpreter main.py's live decision path uses - to
produce a predicted-<head> column. Deliberately its own module, not
train.py: train.py imports torch, and `aq evaluate` must stay fast to
start for commands that never need training-time code (this package's
torch-free contract - see evaluation/__init__.py's docstring).

Because this reuses inference/exported_model.py verbatim (not a
re-derived approximation), `aq evaluate --rank-book` reports the SAME
numbers a live/backtest run would produce from the same artifacts -
including any live quirk in those artifacts (e.g. Problems.md #73's
sigmoid-vs-raw mismatch), which is the point: this is meant to be an
offline mirror of live behavior, not a separate idealized model.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from inference.exported_model import (
    resolve_sequence_window_size,
    run_exported_multitask_model,
    run_exported_sequence_multitask_model,
)


def build_sequence_windows(
    dataset: pd.DataFrame,
    model_input_names: list[str],
    window_size: int,
    ticker_column: str = "ticker",
) -> np.ndarray:
    """Torch-free port of train.py::build_sequence_tensor_dataset() - same
    algorithm (each ticker's own trailing window, left-padded with zeros
    for rows with fewer than window_size preceding rows, row-order-aligned
    with `dataset`), deliberately duplicated rather than imported since
    train.py pulls in torch and this module must stay import-light.
    `dataset` must already be sorted the way build_feature_dataset() leaves
    it (each ticker's own rows in chronological order) - the same
    precondition train.py's version documents.

    float32, not float64 (V5.1 Phase 5, Problems.md #83) - halves peak
    memory for no correctness cost: every consumer (run_exported_sequence_
    multitask_model()) takes `sequence: list[list[float]]` and converts via
    .tolist() before use, so the underlying numpy dtype is invisible to it
    either way. Matches train.py::build_sequence_tensor_dataset()'s own
    dtype, which was already float32."""
    feature_matrix = dataset[model_input_names].to_numpy(dtype=np.float32)
    tickers = dataset[ticker_column].to_numpy()

    windows = np.zeros((len(dataset), window_size, len(model_input_names)), dtype=np.float32)
    positions_by_ticker: dict[object, list[int]] = {}
    for position, ticker in enumerate(tickers):
        positions_by_ticker.setdefault(ticker, []).append(position)

    for positions in positions_by_ticker.values():
        for index_within_ticker, position in enumerate(positions):
            window_start = max(0, index_within_ticker + 1 - window_size)
            window_positions = positions[window_start : index_within_ticker + 1]
            window_values = feature_matrix[window_positions]
            windows[position, -len(window_values) :, :] = window_values

    return windows


def predict_multitask_head(
    dataset: pd.DataFrame, model_export: dict, feature_names: list[str], head: str
) -> np.ndarray:
    """One run_exported_multitask_model() call per row - the flat-MLP
    trunk needs no windowing, unlike the sequence model below."""
    predictions = np.full(len(dataset), np.nan, dtype=np.float64)
    feature_matrix = dataset[feature_names].to_numpy(dtype=np.float64)
    for row_index in range(len(dataset)):
        outputs = run_exported_multitask_model(model_export, feature_matrix[row_index].tolist())
        predictions[row_index] = outputs.get(head, np.nan)
    return predictions


def predict_sequence_head(
    dataset: pd.DataFrame,
    model_export: dict,
    feature_names: list[str],
    head: str,
    *,
    sequence_feature_schema: dict | None = None,
    configured_window_size: int = 30,
    ticker_column: str = "ticker",
) -> np.ndarray:
    """Builds each row's trailing window via build_sequence_windows() then
    runs run_exported_sequence_multitask_model() per row. window_size comes
    from resolve_sequence_window_size() - the trained model's OWN schema
    wins over any configured default, the same shape-mismatch-avoidance
    contract main.py's live sequence-model path already follows."""
    window_size = resolve_sequence_window_size(sequence_feature_schema, configured_window_size)
    windows = build_sequence_windows(dataset, feature_names, window_size, ticker_column)
    predictions = np.full(len(dataset), np.nan, dtype=np.float64)
    for row_index in range(len(dataset)):
        outputs = run_exported_sequence_multitask_model(model_export, windows[row_index].tolist())
        predictions[row_index] = outputs.get(head, np.nan)
    return predictions


def predict_head(
    dataset: pd.DataFrame,
    model_export: dict,
    feature_names: list[str],
    head: str,
    *,
    model_kind: str,
    sequence_feature_schema: dict | None = None,
    configured_window_size: int = 30,
    ticker_column: str = "ticker",
) -> np.ndarray:
    """Single dispatch point for `aq evaluate` - model_kind in
    {"multitask", "sequence"} picks the right predictor above. Any other
    value raises ValueError (a genuinely programmer-facing error, not a
    runtime degradation case - unlike every other function in this
    package, this one is not on main.py's live path)."""
    if model_kind == "multitask":
        return predict_multitask_head(dataset, model_export, feature_names, head)
    if model_kind == "sequence":
        return predict_sequence_head(
            dataset, model_export, feature_names, head,
            sequence_feature_schema=sequence_feature_schema,
            configured_window_size=configured_window_size,
            ticker_column=ticker_column,
        )
    raise ValueError(f"unknown model_kind {model_kind!r} - expected 'multitask' or 'sequence'")
