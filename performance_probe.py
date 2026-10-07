"""Opt-in, in-memory timing and teardown probes for the Lean hot path.

V5.5.0 (Problems.md #129). Two jobs main.py could not do before:

1. Real per-call timing (#63): `TimingProbe` accumulates `perf_counter`
   deltas in memory (no per-bar disk I/O, no logging) and `main.py` emits
   ONE `timing-probe:` line at the end of the run. Disabled (the default)
   every method returns immediately, so the cost is one attribute check.
2. Teardown diagnostics (#104): the chronic `PythonInitializer.Shutdown()`
   timeout happens with `threading.enumerate()` empty, so the blocker is
   native/.NET-side. `collect_teardown_diagnostics()` reports what a Python
   thread listing cannot (OS thread names, GC object/freeze counts) and
   `release_symbol_containers()` is the opt-in cleanup experiment: drop the
   large per-symbol containers (which hold Lean `Symbol` keys) and unfreeze
   the GC before Lean finalizes the interpreter.

Deliberately standard-library only: main.py imports this at Lean startup,
where heavy imports (torch, pandas) once blew the 90-second Initialize()
isolator budget (Problems.md #16).
"""

from __future__ import annotations

import gc
import os
import time
from collections import defaultdict


class TimingProbe:
    """Accumulates call counts and wall time per named section."""

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = bool(enabled)
        self._total_seconds: dict[str, float] = defaultdict(float)
        self._calls: dict[str, int] = defaultdict(int)
        self._counters: dict[str, int] = defaultdict(int)

    def start(self) -> float:
        return time.perf_counter() if self.enabled else 0.0

    def stop(self, name: str, started: float) -> None:
        if not self.enabled:
            return
        self._total_seconds[name] += time.perf_counter() - started
        self._calls[name] += 1

    def count(self, name: str, amount: int = 1) -> None:
        if self.enabled:
            self._counters[name] += amount

    def summary(self) -> dict:
        sections = {
            name: {
                "calls": self._calls[name],
                "total_ms": round(self._total_seconds[name] * 1000.0, 3),
                "mean_ms": round(self._total_seconds[name] * 1000.0 / max(self._calls[name], 1), 4),
            }
            for name in sorted(self._total_seconds)
        }
        return {"sections": sections, "counters": dict(sorted(self._counters.items()))}

    def format_line(self) -> str:
        data = self.summary()
        parts = [
            f"{name}=calls:{stats['calls']}/total_ms:{stats['total_ms']}/mean_ms:{stats['mean_ms']}"
            for name, stats in data["sections"].items()
        ]
        parts.extend(f"{name}={value}" for name, value in data["counters"].items())
        return "timing-probe: " + (" ".join(parts) if parts else "no_samples")


def native_thread_names(proc_task_dir: str = "/proc/self/task") -> list[str]:
    """OS-level thread names (Linux only - the Lean container). Returns []
    anywhere else or on any error; never raises."""
    names: list[str] = []
    try:
        for thread_id in sorted(os.listdir(proc_task_dir)):
            try:
                with open(os.path.join(proc_task_dir, thread_id, "comm"), encoding="utf-8") as handle:
                    names.append(handle.read().strip())
            except OSError:
                continue
    except OSError:
        return []
    return names


def collect_teardown_diagnostics() -> dict:
    """What a Python-thread listing cannot show. All fields best-effort."""
    diagnostics: dict = {"native_threads": native_thread_names()}
    try:
        diagnostics["gc_tracked_objects"] = len(gc.get_objects())
        diagnostics["gc_frozen_objects"] = gc.get_freeze_count()
    except Exception as error:  # pragma: no cover - defensive, gc never raises today
        diagnostics["gc_error"] = repr(error)
    return diagnostics


def release_symbol_containers(containers: list) -> dict:
    """Opt-in pre-shutdown cleanup experiment (phase_v2.diagnostics.
    teardown_cleanup). Clears each dict/list/deque/set in `containers`,
    unfreezes the GC (main.py calls gc.freeze() after load, which pins every
    object alive at that point out of collection) and runs a full collection.
    Returns {"cleared": n, "collected": n, "seconds": s}. Never raises; the
    algorithm has already finished when this runs."""
    started = time.perf_counter()
    cleared = 0
    for container in containers:
        try:
            container.clear()
            cleared += 1
        except Exception:
            continue
    try:
        gc.unfreeze()
        collected = gc.collect()
    except Exception:
        collected = -1
    return {"cleared": cleared, "collected": collected, "seconds": round(time.perf_counter() - started, 4)}
