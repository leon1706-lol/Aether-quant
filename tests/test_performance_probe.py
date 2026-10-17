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


def test_state_write_policy_defaults_to_every_tick_and_thins_only_backtests():
    from performance_probe import resolve_state_write_policy, should_write_runtime_state, state_json_indent

    default = resolve_state_write_policy(None)
    assert all(should_write_runtime_state(default, False, tick) for tick in range(5))
    assert state_json_indent(default, False) == 2
    thinned = resolve_state_write_policy({"every_n_ticks": 20, "compact_json_in_backtest": True})
    assert [tick for tick in range(41) if should_write_runtime_state(thinned, False, tick)] == [0, 20, 40]
    assert all(should_write_runtime_state(thinned, True, tick) for tick in range(5))  # live always writes
    assert state_json_indent(thinned, False) is None and state_json_indent(thinned, True) == 2
    shutdown_only = resolve_state_write_policy({"backtest_only_at_shutdown": True, "every_n_ticks": "x"})
    assert not should_write_runtime_state(shutdown_only, False, 0) and shutdown_only["every_n_ticks"] == 1


def test_sigterm_witness_reports_the_sender_and_exits_143():
    """V5.8.0: the witness names who sent SIGTERM (Linux only)."""
    import signal
    import subprocess
    import sys
    import textwrap
    import time

    import pytest

    if not (hasattr(signal, "sigwaitinfo") and hasattr(signal, "pthread_sigmask")):
        pytest.skip("sigwaitinfo is not available on this platform")
    code = textwrap.dedent(
        """
        import logging, sys, time
        logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")
        from performance_probe import install_sigterm_witness
        assert install_sigterm_witness(logging.getLogger("t"))
        print("ready", flush=True)
        time.sleep(30)
        """
    )
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    assert child.stdout.readline().strip() == "ready"
    child.send_signal(signal.SIGTERM)
    output = child.stdout.read()
    child.wait(timeout=20)
    assert child.returncode == 143
    assert "SIGTERM received from pid" in output and "MemAvailable=" in output
    time.sleep(0)


def test_cpu_time_is_recorded_next_to_wall_time_so_a_busy_host_is_visible(monkeypatch):
    import performance_probe

    wall = iter([100.0, 100.5, 200.0, 201.0])
    cpu = iter([10.0, 10.2, 20.0, 20.1])
    monkeypatch.setattr(performance_probe.time, "perf_counter", lambda: next(wall))
    monkeypatch.setattr(performance_probe.time, "process_time", lambda: next(cpu))
    probe = TimingProbe(enabled=True)
    probe.stop("section", probe.start())
    probe.stop("section", probe.start())
    stats = probe.summary()["sections"]["section"]
    assert stats["total_ms"] == 1500.0 and abs(stats["cpu_total_ms"] - 300.0) < 1e-6  # waited, not computed
    assert "cpu_ms:300.0" in probe.format_line()
