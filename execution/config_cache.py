"""Mtime-gated read cache for config.json, shared by the per-bar/per-poll
config readers (risk/manual_override.py, execution/paper_readiness_io.py,
execution/runtime_config_io.py) that are all called far more often than
config.json actually changes - once per bar in a Lean backtest, once per
poll-loop iteration in retraining/worker.py.

The check-cadence in those callers is correct by design (see
main.py::_refresh_risk_state()'s own comments) - this module only removes
the redundant open()+json.load() cost of reading a file that, in practice,
almost never changes between calls.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")

# Keyed by (config_path, loader), not just config_path - multiple distinct
# readers (read_manual_trade_lock_override, read_paper_trading_config,
# read_runtime_mode) all read the same config.json path with different
# loaders. Keying by path alone would let one reader's cached value leak
# into another reader's result whenever both are called in the same bar
# with the file's mtime unchanged in between - caught via a real Lean
# backtest run, not a unit test (each reader's tests use their own
# isolated tmp_path with only one loader ever touching it).
_cache: dict[tuple[Path, Callable], tuple[float, object]] = {}


def read_cached(config_path: Path, loader: Callable[[Path], T]) -> T:
    """Returns loader(config_path)'s cached result if config_path's mtime
    hasn't changed since the last call for this exact (path, loader) pair;
    otherwise calls loader fresh and updates the cache. Falls back to
    calling loader directly (bypassing the cache) if the file doesn't
    exist, preserving loader's own missing-file handling."""
    if not config_path.exists():
        return loader(config_path)

    mtime = config_path.stat().st_mtime
    cache_key = (config_path, loader)
    cached = _cache.get(cache_key)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    value = loader(config_path)
    _cache[cache_key] = (mtime, value)
    return value
