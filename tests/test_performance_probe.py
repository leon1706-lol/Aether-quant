"""Tests for performance_probe.py (V5.5.0, Problems.md #129): the opt-in timing
accumulator and the teardown diagnostics/cleanup experiment. Conventions
match the rest of this repo: no test classes, module-level helpers."""

import gc
from collections import deque

from performance_probe import (
    TimingProbe,
    collect_teardown_diagnostics,
    native_thread_names,
    release_symbol_containers,
)


def test_disabled_probe_records_nothing_and_costs_nothing():
    probe = TimingProbe(enabled=False)
    started = probe.start()
    assert started == 0.0
    probe.stop("section", started)
    probe.count("hits")
    assert probe.summary() == {"sections": {}, "counters": {}}
    assert probe.format_line() == "timing-probe: no_samples"


def test_enabled_probe_accumulates_calls_and_counters():
    probe = TimingProbe(enabled=True)
    for _ in range(3):
        probe.stop("inference", probe.start())
    probe.count("topology_cache_hit", 2)
    probe.count("topology_cache_hit")
    summary = probe.summary()
    assert summary["sections"]["inference"]["calls"] == 3
    assert summary["sections"]["inference"]["total_ms"] >= 0.0
    assert summary["counters"] == {"topology_cache_hit": 3}
    line = probe.format_line()
    assert line.startswith("timing-probe: ")
    assert "inference=calls:3" in line
    assert "topology_cache_hit=3" in line


def test_native_thread_names_reads_comm_files(tmp_path):
    for thread_id, name in (("101", "python"), ("102", "dotnet-worker")):
        (tmp_path / thread_id).mkdir()
        (tmp_path / thread_id / "comm").write_text(name + "\n", encoding="utf-8")
    (tmp_path / "103").mkdir()  # no comm file: skipped, not fatal
    assert native_thread_names(str(tmp_path)) == ["python", "dotnet-worker"]


def test_native_thread_names_degrades_to_empty_off_linux(tmp_path):
    assert native_thread_names(str(tmp_path / "missing")) == []


def test_collect_teardown_diagnostics_reports_gc_counts():
    diagnostics = collect_teardown_diagnostics()
    assert isinstance(diagnostics["native_threads"], list)
    assert diagnostics["gc_tracked_objects"] > 0
    assert diagnostics["gc_frozen_objects"] >= 0


def test_release_symbol_containers_clears_unfreezes_and_never_raises():
    symbol_windows = {"AAPL": deque([1, 2, 3])}
    history = [1, 2, 3]
    members = {"a"}

    class Unclearable:
        def clear(self):
            raise RuntimeError("boom")

    gc.freeze()  # main.py freezes after load; the cleanup must undo it
    assert gc.get_freeze_count() > 0
    result = release_symbol_containers([symbol_windows, history, members, Unclearable(), object()])
    assert symbol_windows == {} and history == [] and members == set()
    assert result["cleared"] == 3  # the two un-clearable entries are skipped
    assert result["collected"] >= 0
    assert result["seconds"] >= 0.0
    assert gc.get_freeze_count() == 0
