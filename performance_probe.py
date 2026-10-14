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


def resolve_state_write_policy(raw: dict | None) -> dict:
    """`phase_v2.diagnostics.state_write` -> {"every_n_ticks", "backtest_only_at_shutdown", "compact_json_in_backtest"}.
    Absent = write every tick with indented JSON (the pre-V5.8.0 behaviour)."""
    raw = raw or {}
    try:
        every = max(1, int(raw.get("every_n_ticks", 1)))
    except (TypeError, ValueError):
        every = 1
    return {
        "every_n_ticks": every,
        "backtest_only_at_shutdown": bool(raw.get("backtest_only_at_shutdown", False)),
        "compact_json_in_backtest": bool(raw.get("compact_json_in_backtest", False)),
    }


def should_write_runtime_state(policy: dict | None, live_mode: bool, tick_index: int) -> bool:
    """V5.8.0: the dashboard state (6 JSON files + a CSV, ~1.1 MB) was rewritten on every tick - about 2 GB of disk
    writes per backtest. Live/paper always write every tick (the dashboard reads them); a backtest may thin them out
    or write only at shutdown. The initialize/shutdown writes never pass through here."""
    if live_mode or not policy:
        return True
    if policy.get("backtest_only_at_shutdown"):
        return False
    every = int(policy.get("every_n_ticks", 1))
    return every <= 1 or int(tick_index) % every == 0


def state_json_indent(policy: dict | None, live_mode: bool) -> int | None:
    """2 (human-readable) unless a backtest asked for compact JSON."""
    if not live_mode and policy and policy.get("compact_json_in_backtest"):
        return None
    return 2


def install_sigterm_witness(log) -> bool:
    """Linux only: record WHO sends SIGTERM to this process (V5.8.0). The Codespace kills trainers with no OOM event in the
    cgroup and no kernel line; without the sender's pid and command line the kill stays a mystery. SIGTERM is blocked in
    the calling thread (so every thread started afterwards inherits the mask) and a daemon thread waits for it with
    `sigwaitinfo`, logs si_pid, that process's command line and the machine's memory, then exits 143 like the default
    action would. Call it once, first thing in `main()`. Returns False where the facility does not exist."""
    import os
    import signal
    import threading

    if not (hasattr(signal, "sigwaitinfo") and hasattr(signal, "pthread_sigmask")):
        return False

    def _memory_line() -> str:
        try:
            with open("/proc/meminfo", encoding="ascii") as handle:
                fields = {line.split(":")[0]: line.split()[1] for line in handle if line.startswith(("MemAvailable", "MemFree"))}
            return f"MemAvailable={int(fields['MemAvailable']) // 1024} MB MemFree={int(fields['MemFree']) // 1024} MB"
        except (OSError, KeyError, ValueError):
            return "meminfo unavailable"

    def _command_of(pid: int) -> str:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as handle:
                return handle.read().replace(b"\0", b" ").decode("utf-8", "replace")[:200] or "?"
        except OSError:
            return "?"

    def _wait() -> None:
        info = signal.sigwaitinfo({signal.SIGTERM})
        sender = getattr(info, "si_pid", 0)
        log.error("SIGTERM received from pid %s (%s), parent of sender %s; %s", sender, _command_of(sender),
                  _command_of(_parent_of(sender)), _memory_line())
        for handler in getattr(log, "handlers", []) or []:
            try:
                handler.flush()
            except Exception:  # noqa: BLE001 - dying anyway
                pass
        os._exit(143)

    def _parent_of(pid: int) -> int:
        try:
            with open(f"/proc/{pid}/stat", encoding="ascii") as handle:
                return int(handle.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            return 0

    signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
    threading.Thread(target=_wait, name="sigterm-witness", daemon=True).start()
    return True
