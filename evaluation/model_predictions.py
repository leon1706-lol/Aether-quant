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


def select_context_date_range(
    dataset: pd.DataFrame,
    recorded_dates: list[str],
    *,
    window_size: int,
    ticker_column: str = "ticker",
    date_column: str = "date",
) -> tuple[str, str]:
    """V5.2.2 (development/Problems.md) - computes the inclusive
    `(min_date, max_date)` date-string bounds a caller must keep every
    row for (per ticker, in `dataset`'s own row order) before restricting
    the dataset to a specific set of `recorded_dates` and still getting
    CORRECT `build_sequence_windows()` output for those dates.

    GUARDRAIL: `build_sequence_windows()` builds each ticker's trailing
    window from ORDINAL ROW POSITION within whatever frame it's given,
    not from calendar dates - it has no way to know rows were dropped.
    Naively filtering `dataset` down to only `recorded_dates` before
    calling it does not raise; it silently builds each window from
    whichever OTHER kept rows happen to be ordinally adjacent (e.g. 10
    calendar days apart instead of 1), producing wrong predictions with
    no error. This function exists so a caller can safely narrow a large
    dataset to just the date range a reconciliation actually needs
    (`aq evaluate --reconcile-book-history`'s whole reason for existing)
    without corrupting sequence-model context: keep every row inside
    `[min(recorded_dates), max(recorded_dates)]` UNCHANGED, plus enough
    additional rows per ticker immediately preceding that span (by row
    position, not calendar-day subtraction, since non-trading days never
    appear in `dataset` to begin with) to fully support a `window_size`
    trailing window for the earliest recorded date. Only rows entirely
    outside the returned bounds may be safely dropped.

    Per ticker: finds the first row at/after `min(recorded_dates)`, then
    walks back `window_size` positions (mirroring `build_sequence_windows()`'s
    own `max(0, index_within_ticker + 1 - window_size)` formula exactly)
    to find that ticker's own earliest-needed date. The overall
    `min_date` returned is the EARLIEST such date across all tickers, so
    every ticker's window is fully supported, not just the first one
    encountered. A ticker with no rows at/after `min(recorded_dates)` at
    all is skipped (nothing to support for it).

    Raises `ValueError` if `recorded_dates` is empty - there is no
    context range to compute without at least one target date."""
    if not recorded_dates:
        raise ValueError("select_context_date_range() requires at least one recorded date")

    target_min = min(recorded_dates)
    target_max = max(recorded_dates)

    earliest_needed_dates: list[str] = []
    for _ticker, ticker_frame in dataset.groupby(ticker_column, sort=False):
        ticker_dates = ticker_frame[date_column].tolist()
        boundary_index = next((i for i, d in enumerate(ticker_dates) if d >= target_min), None)
        if boundary_index is None:
            continue
        lookback_start = max(0, boundary_index + 1 - window_size)
        earliest_needed_dates.append(ticker_dates[lookback_start])

    min_date = min(earliest_needed_dates) if earliest_needed_dates else target_min
    return min_date, target_max


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
