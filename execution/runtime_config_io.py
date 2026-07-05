"""IO layer for reading phase_v2.runtime.mode fresh from config.json.

Mirrors risk/manual_override.py::read_manual_trade_lock_override()'s
pattern exactly. Used by retraining/worker.py's auto-promote-in-live safety
net (Phase V2-22) - a process outside main.py (which has its own copy of
this same read, see main.py's runtime_mode resolution in initialize()/
_refresh_risk_state()) needs its own fresh read since it never shares
main.py's in-memory state.
"""

from __future__ import annotations

import json
from pathlib import Path

from execution.order_gate import resolve_runtime_mode

_PHASE_V2_KEY = "phase_v2"
_RUNTIME_KEY = "runtime"


def read_runtime_mode(config_path: Path) -> str:
    """Fresh read of phase_v2.runtime.mode, normalized via
    resolve_runtime_mode() (fails safe to 'observation' if the file is
    missing or the value is absent/unknown) - never raises."""
    if not config_path.exists():
        return resolve_runtime_mode(None)
    with config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)
    raw_mode = config.get(_PHASE_V2_KEY, {}).get(_RUNTIME_KEY, {}).get("mode")
    return resolve_runtime_mode(raw_mode)
