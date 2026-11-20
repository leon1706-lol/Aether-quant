"""retraining/slicing.py (V6.6.10): lazy sequence windows are the dense ones exactly, profiles, estimates and the memory probe."""

from __future__ import annotations

import ctypes
import io
import json
import types

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import train
from retraining import slicing


def _frame(tickers, features=3, seed=0):
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({"ticker": tickers})
    names = [f"f{i}" for i in range(features)]
    for name in names:
        frame[name] = rng.normal(size=len(tickers)).astype(np.float32)
    return frame, names


@pytest.mark.parametrize("window", [1, 3, 5])
def test_lazy_windows_equal_the_dense_builder(window):
    tickers = ["A", "B", "A", "C", "A", "B", "A", "A", "C", "B"]
    frame, names = _frame(tickers)
    matrix = frame[names].to_numpy(dtype=np.float32)
    dense = train.build_sequence_tensor_dataset(frame, names, window)
    assert np.array_equal(slicing.gather_windows(matrix, slicing.sequence_window_index(frame["ticker"], window)), dense)
    mask = np.array([i % 3 == 0 for i in range(len(tickers))])
    dense_masked = train.build_sequence_tensor_dataset(frame, names, window, row_mask=mask)
    assert np.array_equal(slicing.gather_windows(matrix, slicing.sequence_window_index(frame["ticker"], window, row_mask=mask)), dense_masked)


@settings(max_examples=40, deadline=None)
@given(st.lists(st.sampled_from(["A", "B", "C", "D"]), min_size=1, max_size=40), st.integers(min_value=1, max_value=8))
def test_lazy_windows_property(tickers, window):
    frame, names = _frame(tickers, features=2, seed=len(tickers))
    index = slicing.sequence_window_index(np.asarray(tickers, dtype=object), window)
    assert index.dtype == np.int32 and index.shape == (len(tickers), window)
    assert np.all(index[:, -1] == np.arange(len(tickers))), "a window ends at its own row"
    assert np.all((index < 0) | (index <= np.arange(len(tickers))[:, None])), "a window never reaches a later row"
    assert np.array_equal(slicing.gather_windows(frame[names].to_numpy(), index), train.build_sequence_tensor_dataset(frame, names, window))


def test_window_index_edges():
    assert slicing.sequence_window_index([], 4).shape == (0, 4)
    with pytest.raises(ValueError, match="at least 1"):
        slicing.sequence_window_index(["A"], 0)


def test_window_index_refuses_more_rows_than_int32(monkeypatch):
    monkeypatch.setattr(slicing.np, "iinfo", lambda dtype: types.SimpleNamespace(max=2))
    with pytest.raises(ValueError, match="int32"):
        slicing.sequence_window_index(["A", "B"], 2)


def test_profiles_and_estimates():
    assert slicing.memory_profile("low").lazy_windows and not slicing.memory_profile("standard").lazy_windows
    assert slicing.memory_profile("standard").timeout_factor == 1.0 < slicing.memory_profile("low").timeout_factor, "#408: a slower profile waits longer"
    with pytest.raises(ValueError, match="unknown memory profile"):
        slicing.memory_profile("tiny")
    low = slicing.estimate_peak_gb(280_000, 254, 66, window=30, profile="low")
    standard = slicing.estimate_peak_gb(280_000, 254, 66, window=30, profile="standard")
    assert low < 1.3 < standard, (low, standard)
    assert slicing.profile_summary("low")["min_total_gb"] == 3.5


def test_process_memory_on_linux_reads_proc(monkeypatch):
    monkeypatch.setattr(slicing.sys, "platform", "linux")
    monkeypatch.setattr(slicing, "open", lambda *a, **k: io.StringIO("Name:\tpy\nVmRSS:\t2048 kB\nVmHWM:\t4096 kB\n"), raising=False)
    assert slicing.process_memory_mb() == (2.0, 4.0)
    monkeypatch.setattr(slicing, "open", lambda *a, **k: io.StringIO("Name:\tpy\n"), raising=False)
    assert slicing.process_memory_mb() is None


def _fake_ctypes(ok):
    def memory_info(process, ref, size):
        ref._obj.working_set, ref._obj.peak_working_set = 3 * 1024 ** 2, 5 * 1024 ** 2
        return ok

    windll = types.SimpleNamespace(kernel32=types.SimpleNamespace(GetCurrentProcess=lambda: 7), psapi=types.SimpleNamespace(GetProcessMemoryInfo=memory_info))
    return types.SimpleNamespace(**{name: getattr(ctypes, name) for name in ("Structure", "c_ulong", "c_size_t", "c_void_p", "sizeof", "byref")}, windll=windll)


def test_process_memory_on_windows(monkeypatch):
    monkeypatch.setattr(slicing.sys, "platform", "win32")
    monkeypatch.setattr(slicing, "ctypes", _fake_ctypes(1))
    assert slicing.process_memory_mb() == (3.0, 5.0)
    monkeypatch.setattr(slicing, "ctypes", _fake_ctypes(0))
    assert slicing.process_memory_mb() is None
    monkeypatch.setattr(slicing, "ctypes", types.SimpleNamespace(**{name: getattr(ctypes, name) for name in ("Structure", "c_ulong", "c_size_t", "c_void_p", "sizeof", "byref")}))
    assert slicing.process_memory_mb() is None, "no windll: not Windows after all"


def test_log_peak_appends_rows(tmp_path):
    path = tmp_path / "peaks" / "memory_peaks.jsonl"
    assert slicing.log_peak(path, "sequence", profile="low", memory=(100.0, 2048.0))["peak_gb"] == 2.0
    slicing.log_peak(path, "gating", profile="low")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["stage"] for row in rows] == ["sequence", "gating"]


def test_log_peak_without_a_reading(tmp_path, monkeypatch):
    monkeypatch.setattr(slicing, "process_memory_mb", lambda: None)
    assert slicing.log_peak(tmp_path / "m.jsonl", "x", profile="low")["peak_gb"] is None


def test_read_csv_float32_is_a_plain_read_in_float32(tmp_path):
    path = tmp_path / "d.csv"
    frame = pd.DataFrame({"date": ["2020-01-01", "2020-01-02", "2020-01-03"], "ticker": ["A", "B", "A"], "x": [0.5, 1.25, -2.0], "flag": [True, False, True], "n": [1, 2, 3]})
    frame.to_csv(path, index=False)
    got = slicing.read_csv_float32(path, chunk_rows=2)
    assert got["x"].dtype == np.float32 and got["flag"].dtype == bool and got["n"].dtype == np.int64
    pd.testing.assert_frame_equal(got, frame.astype({"x": np.float32}))
    empty = tmp_path / "e.csv"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(pd.errors.EmptyDataError):
        slicing.read_csv_float32(empty)
    header = tmp_path / "h.csv"
    header.write_text("date,x\n", encoding="utf-8")
    assert slicing.read_csv_float32(header).empty
