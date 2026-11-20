"""Training on a small machine (V6.6.10): memory profiles, lazy sequence windows and the process's memory, numpy and stdlib only.

The sequence trainer used to build a dense (rows, window, features) float32 array per split, about 2 GB for the 2014-2021 train
window. Under the `low` profile it keeps one (rows, features) matrix and an index of each row's window instead, and gathers a
batch's windows when the batch is drawn: `gather_windows(matrix, sequence_window_index(...))` is exactly
`train.build_sequence_tensor_dataset(...)`, so training on either is the same computation.
"""

from __future__ import annotations

import ctypes
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    import pandas as pd

GIB = 1024.0 ** 3


@dataclass(frozen=True)
class MemoryProfile:
    """How a trainer holds its data. `min_total_gb` is the RAM `ram_preflight` asks of a local host under this profile; `timeout_factor`
    scales the walk-forward's per-trainer timeouts (a low-profile trainer is slower: at 1x the later windows' trainers were killed, #408)."""
    name: str
    lazy_windows: bool
    read_chunk_rows: int
    checkpoint_every: int
    min_total_gb: float
    timeout_factor: float = 1.0


PROFILES = {
    "standard": MemoryProfile("standard", lazy_windows=False, read_chunk_rows=40_000, checkpoint_every=0, min_total_gb=14.0),
    "low": MemoryProfile("low", lazy_windows=True, read_chunk_rows=10_000, checkpoint_every=1, min_total_gb=3.5, timeout_factor=4.0),
}


def memory_profile(name: str) -> MemoryProfile:
    """The named profile; an unknown name is an error, never a silent default."""
    if name not in PROFILES:
        raise ValueError(f"unknown memory profile {name!r}; expected one of {sorted(PROFILES)}")
    return PROFILES[name]


def estimate_peak_gb(rows: int, columns: int, features: int, *, window: int, profile: str, train_fraction: float = 0.62) -> float:
    """A conservative estimate of the sequence trainer's peak resident memory, in GB.

    The frame (float32, plus pandas' parse buffers of one chunk in float64), the sequence windows (dense per split, or the row matrix
    and an int32 index), and a fixed 0.6 GB for the interpreter, torch and the model. The sequence stage is the largest of the stack's
    stages; the others hold the frame and a flat copy of it."""
    chosen = memory_profile(profile)
    frame = rows * columns * 4 + chosen.read_chunk_rows * columns * 8
    if chosen.lazy_windows:
        windows = rows * features * 4 + rows * window * 4
    else:
        windows = rows * window * features * 4 * max(train_fraction, 1.0 - train_fraction)
    return round((frame + windows) / GIB + 0.6, 2)


def sequence_window_index(tickers: Sequence[Any] | np.ndarray, window_size: int, row_mask: np.ndarray | None = None) -> np.ndarray:
    """(rows, window_size) int32 positions into the frame: row i's window is its ticker's last `window_size` rows up to and including i,
    in frame order, left-padded with -1 where the ticker has fewer rows. With `row_mask`, only the masked rows, in frame order (a window
    still reaches back into rows the mask leaves out, exactly as `build_sequence_tensor_dataset` does)."""
    if window_size < 1:
        raise ValueError("window_size must be at least 1")
    tickers = np.asarray(tickers)
    rows = len(tickers)
    if rows >= np.iinfo(np.int32).max:
        raise ValueError("too many rows for an int32 index")
    index = np.full((rows, window_size), -1, dtype=np.int32)
    if rows:
        _, codes = np.unique(tickers, return_inverse=True)
        order = np.argsort(codes, kind="stable")
        bounds = np.flatnonzero(np.diff(codes[order])) + 1
        for positions in np.split(order.astype(np.int32), bounds):
            padded = np.concatenate([np.full(window_size - 1, -1, dtype=np.int32), positions])
            index[positions] = np.lib.stride_tricks.sliding_window_view(padded, window_size)
    if row_mask is not None:
        index = index[np.asarray(row_mask, dtype=bool)]
    return index


def gather_windows(matrix: np.ndarray, index: np.ndarray) -> np.ndarray:
    """The (len(index), window, features) float32 windows: `matrix[index]` with every -1 position as a row of zeros."""
    out = np.asarray(matrix, dtype=np.float32)[np.maximum(index, 0)]
    out[index < 0] = 0.0
    return out


def read_csv_float32(path: Path | str, chunk_rows: int = 40_000) -> pd.DataFrame:
    """`pd.read_csv(path)` with every float64 column as float32, parsed in chunks: the whole file is never held in float64. Dates,
    tickers and boolean flags keep their types."""
    import pandas as pd

    parts = []
    for chunk in pd.read_csv(path, chunksize=max(1, int(chunk_rows))):
        parts.append(chunk.astype(dict.fromkeys(chunk.columns[chunk.dtypes == np.float64], np.float32)))
    return pd.concat(parts, ignore_index=True)  # a header-only file still yields one (empty) chunk


def process_memory_mb() -> tuple[float, float] | None:
    """(current, peak) resident memory of this process in MB: /proc on Linux, GetProcessMemoryInfo on Windows; None elsewhere."""
    if sys.platform == "win32":
        return _windows_memory_mb()
    try:
        values = {}
        with open("/proc/self/status", encoding="ascii") as handle:
            for line in handle:
                if line.startswith(("VmRSS:", "VmHWM:")):
                    values[line.split(":")[0]] = float(line.split()[1]) / 1024.0
        return values["VmRSS"], values["VmHWM"]
    except (OSError, KeyError, ValueError):
        return None


def _windows_memory_mb() -> tuple[float, float] | None:
    class _Counters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong), ("page_fault_count", ctypes.c_ulong), ("peak_working_set", ctypes.c_size_t), ("working_set", ctypes.c_size_t),
            ("quota_peak_paged_pool", ctypes.c_size_t), ("quota_paged_pool", ctypes.c_size_t), ("quota_peak_non_paged_pool", ctypes.c_size_t),
            ("quota_non_paged_pool", ctypes.c_size_t), ("pagefile_usage", ctypes.c_size_t), ("peak_pagefile_usage", ctypes.c_size_t),
        ]

    try:
        counters = _Counters()
        counters.cb = ctypes.sizeof(_Counters)
        # the pseudo-handle is -1: as a default c_int argument it would reach a 64-bit API truncated to 0xFFFFFFFF, an invalid handle
        process = ctypes.c_void_p(ctypes.windll.kernel32.GetCurrentProcess())
        if not ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
            return None
        return counters.working_set / 1024.0 ** 2, counters.peak_working_set / 1024.0 ** 2
    except (AttributeError, OSError):
        return None


def log_peak(path: Path, stage: str, *, profile: str, memory: tuple[float, float] | None = None) -> dict[str, Any]:
    """Appends this process's peak memory for `stage` to the JSONL at `path` and returns the row (peak None where it can't be read)."""
    memory = process_memory_mb() if memory is None else memory
    row = {"stage": stage, "profile": profile, "peak_gb": None if memory is None else round(memory[1] / 1024.0, 3)}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row) + "\n")
    return row


def profile_summary(name: str) -> dict[str, Any]:
    """The profile as a plain dict, for `aq cycle retrain --estimate` and the metrics a trainer writes."""
    return asdict(memory_profile(name))
