"""Best-effort optional Lean CLI backtest wrapper (Phase V2-17).

"If Lean is available" per the user's spec: find_lean_binary() returning
None is the actual gate - run_lean_backtest() never attempts subprocess.run
in that case. Same catch-everything-never-raise shape as
retraining/vault_client.py's run_av_command(), since neither the `lean` nor
`av` binaries are guaranteed to be on PATH in every environment this runs in,
and a missing optional tool must never crash the retraining pipeline.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def find_lean_binary(config: dict) -> str | None:
    """shutil.which('lean') or an explicit config override; None if unavailable."""
    configured = config.get("lean_binary", "lean")
    return shutil.which(configured)


def run_lean_backtest(version_dir: Path, config: dict) -> dict:
    """Runs `lean backtest <version_dir>` if Lean is available, best-effort.

    Returns {"ran": bool, "ok": bool | None, "output_path": str | None, "error": str | None}.
    ran=False means no subprocess was ever attempted (Lean missing, or
    run_lean_backtest disabled via config["run_lean_backtest"]=False).
    """
    if not config.get("run_lean_backtest", True):
        return {"ran": False, "ok": None, "output_path": None, "error": "lean_backtest_disabled"}

    lean_binary = find_lean_binary(config)
    if lean_binary is None:
        return {"ran": False, "ok": None, "output_path": None, "error": "lean_not_available"}

    timeout_seconds = int(config.get("lean_timeout_seconds", 1800))
    try:
        result = subprocess.run(
            [lean_binary, "backtest", str(version_dir)],
            cwd=str(version_dir),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError:
        return {"ran": False, "ok": None, "output_path": None, "error": "lean_binary_not_found"}
    except subprocess.TimeoutExpired:
        return {"ran": True, "ok": False, "output_path": None, "error": "lean_backtest_timed_out"}
    except Exception as exc:  # never let an optional Lean run crash the pipeline
        logger.error("run_lean_backtest: unexpected error - %s", exc)
        return {"ran": True, "ok": False, "output_path": None, "error": str(exc)}

    ok = result.returncode == 0
    return {
        "ran": True,
        "ok": ok,
        "output_path": str(version_dir) if ok else None,
        "error": None if ok else (result.stderr or result.stdout or "lean_backtest_failed"),
    }
