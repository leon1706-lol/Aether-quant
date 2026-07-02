"""Aether-Vault (`av`) subprocess execution wrapper (Phase V2-17).

Never raises and never crashes the retraining pipeline: `av` may not be
installed/on PATH in a given environment, and a missing/failing vault commit
must fail the retraining_event gracefully (status="failed") rather than
taking down the orchestrator/worker process. Uses
retraining/vault_commands.py's pure argv builders - this module only knows
how to run a command and interpret its result.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from retraining.vault_commands import build_commit_plan

logger = logging.getLogger(__name__)

_COMMIT_HASH_PATTERN = re.compile(r"\b[0-9a-f]{7,40}\b", re.IGNORECASE)


def run_av_command(argv: list[str], cwd: Path | None = None, timeout: int = 120) -> dict:
    """Runs one `av` subprocess call, never raising.

    Returns {"ok": bool, "returncode": int | None, "stdout": str, "stderr": str, "error": str | None}.
    """
    try:
        result = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        logger.warning("run_av_command: '%s' not found on PATH.", argv[0] if argv else "av")
        return {"ok": False, "returncode": None, "stdout": "", "stderr": "", "error": "av_binary_not_found"}
    except subprocess.TimeoutExpired:
        logger.error("run_av_command: %s timed out after %ds.", argv, timeout)
        return {"ok": False, "returncode": None, "stdout": "", "stderr": "", "error": "av_command_timed_out"}
    except Exception as exc:  # never let a vault call crash the pipeline
        logger.error("run_av_command: unexpected error running %s - %s", argv, exc)
        return {"ok": False, "returncode": None, "stdout": "", "stderr": "", "error": str(exc)}

    ok = result.returncode == 0
    return {
        "ok": ok,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "error": None if ok else (result.stderr or result.stdout or "av_command_failed"),
    }


def parse_vault_commit_hash(stdout: str) -> str | None:
    """Defensive regex extraction of a hex commit/hash token from `av commit` output.

    av's exact output format is out of scope (this repo never reads av's
    source) - this is best-effort only. Returns None if no plausible hash
    token is found; the caller still marks the commit "ok" and records a
    note that no hash could be parsed.
    """
    match = _COMMIT_HASH_PATTERN.search(stdout or "")
    return match.group(0) if match else None


def commit_candidate_to_vault(
    version_id: str,
    add_paths: list[str],
    metrics: dict[str, float],
    config: dict,
    cwd: Path | None = None,
) -> dict:
    """Runs add -> commit -> push sequentially, stopping at the first failing stage.

    Returns {"ok": bool, "stage": "add"|"commit"|"push"|"done", "vault_commit": str | None, "steps": {...}}.
    On ok=False the caller (retraining/orchestrator.py) sets
    retraining_events.status="failed" and appends `steps` to notes - the
    pipeline never proceeds to promotion on a vault failure.
    """
    plan = build_commit_plan(version_id, add_paths, metrics, config)
    timeout = int(config.get("timeout_seconds", 120))
    steps: dict[str, dict] = {}

    add_result = run_av_command(plan["add"], cwd=cwd, timeout=timeout)
    steps["add"] = add_result
    if not add_result["ok"]:
        return {"ok": False, "stage": "add", "vault_commit": None, "steps": steps}

    commit_result = run_av_command(plan["commit"], cwd=cwd, timeout=timeout)
    steps["commit"] = commit_result
    if not commit_result["ok"]:
        return {"ok": False, "stage": "commit", "vault_commit": None, "steps": steps}

    vault_commit = parse_vault_commit_hash(commit_result["stdout"])

    if plan["push"] is None:
        return {"ok": True, "stage": "done", "vault_commit": vault_commit, "steps": steps}

    push_result = run_av_command(plan["push"], cwd=cwd, timeout=timeout)
    steps["push"] = push_result
    if not push_result["ok"]:
        return {"ok": False, "stage": "push", "vault_commit": vault_commit, "steps": steps}

    return {"ok": True, "stage": "done", "vault_commit": vault_commit, "steps": steps}
