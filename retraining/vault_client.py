"""Aether-Vault (`av`) subprocess execution wrapper (Phase V2-17).

Never raises and never crashes the retraining pipeline: `av` may not be
installed/on PATH in a given environment, and a missing/failing vault commit
must fail the retraining_event gracefully (status="failed") rather than
taking down the orchestrator/worker process. Uses
retraining/vault_commands.py's pure argv builders - this module only knows
how to run a command and interpret its result.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

from retraining.vault_commands import (
    build_av_head_command,
    build_av_restore_command,
    build_av_status_command,
    build_commit_plan,
)

logger = logging.getLogger(__name__)

_COMMIT_HASH_PATTERN = re.compile(r"\b[0-9a-f]{7,64}\b", re.IGNORECASE)
_VERSION_PATTERN = re.compile(r"(\d+(?:\.\d+)*)")


def run_av_command(argv: list[str], cwd: Path | None = None, timeout: int = 120) -> dict:
    """Runs one `av` subprocess call, never raising.

    Returns {"ok": bool, "returncode": int | None, "stdout": str, "stderr": str, "error": str | None}.
    """
    try:
        # Explicit UTF-8: av prints box-drawing characters, and Windows' default codepage
        # makes the reader thread die on them, leaving stdout None.
        result = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
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


def parse_av_envelope(stdout: str | None) -> dict | None:
    """The JSON envelope from `av --output json ...`, or None. The envelope is the last JSON
    object printed, since progress lines may precede it."""
    for line in reversed((stdout or "").strip().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict) and "ok" in parsed:
            return parsed
    return None


def parse_vault_commit_hash(stdout: str | None) -> str | None:
    """The commit's full hash from the JSON envelope, falling back to the first hex token in
    human output (`[abc1234] message`) for an `av` that printed no envelope."""
    envelope = parse_av_envelope(stdout)
    if envelope is not None:
        value = (envelope.get("data") or {}).get("hash")
        return str(value) if value else None
    match = _COMMIT_HASH_PATTERN.search(stdout or "")
    return match.group(0) if match else None


def parse_push_state(stdout: str | None) -> str:
    """"drained" when nothing is left to send, "queued" when commits wait in av's offline queue.

    A queued push is a safe outcome for av (exit 0, nothing lost), so it is told apart here."""
    envelope = parse_av_envelope(stdout)
    if envelope is None:
        return "unknown"
    return "queued" if int((envelope.get("data") or {}).get("still_queued") or 0) > 0 else "drained"


def _version_tuple(text: str | None) -> tuple[int, ...] | None:
    match = _VERSION_PATTERN.search(text or "")
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def vault_preflight(config: dict, cwd: Path | None = None) -> dict:
    """Can a candidate be committed from here? Run before training, so a worker without `av`
    fails in seconds instead of after a whole training run.

    Returns {"ok": bool, "reason": str, "av_version": str | None}.
    """
    if not config.get("enabled", True):
        return {"ok": True, "reason": "vault_disabled", "av_version": None}
    timeout = int(config.get("timeout_seconds", 120))
    result = run_av_command([config.get("av_binary", "av"), "--version"], cwd=cwd, timeout=timeout)
    if not result["ok"]:
        return {"ok": False, "reason": str(result["error"]), "av_version": None}
    version = (result["stdout"] or "").strip() or None
    minimum = config.get("min_version")
    if minimum:
        have, need = _version_tuple(version), _version_tuple(str(minimum))
        if have is None or need is None or have < need:
            return {"ok": False, "reason": f"av_version_below_minimum: {version} < {minimum}", "av_version": version}
    repo_root = Path(cwd) if cwd else Path.cwd()
    if not (repo_root / ".av").is_dir():
        return {"ok": False, "reason": f"not_an_av_repo: {repo_root} (run `av init`)", "av_version": version}
    return {"ok": True, "reason": "ready", "av_version": version}


def staged_leftovers(av_binary: str = "av", cwd: Path | None = None, timeout: int = 120) -> list[str] | None:
    """What is already staged, which `av commit` would sweep into the next commit; None when `av status` can't answer."""
    envelope = parse_av_envelope(run_av_command(build_av_status_command(av_binary), cwd=cwd, timeout=timeout)["stdout"])
    if not envelope or not envelope.get("ok"):
        return None
    data = envelope.get("data") or {}
    return sorted(set(data.get("staged") or []) | set(data.get("removed") or []))


def current_head_hash(av_binary: str = "av", cwd: Path | None = None, timeout: int = 120) -> str | None:
    envelope = parse_av_envelope(run_av_command(build_av_head_command(av_binary), cwd=cwd, timeout=timeout)["stdout"])
    commits = ((envelope or {}).get("data") or {}).get("commits") or []
    return commits[0].get("hash") if commits else None


def commit_candidate_to_vault(
    version_id: str,
    add_paths: list[str],
    metrics: dict[str, float],
    config: dict,
    cwd: Path | None = None,
) -> dict:
    """Runs add -> commit -> push sequentially, stopping at the first failing stage.

    Returns {"ok": bool, "stage": "add"|"commit"|"push"|"done", "vault_commit": str | None,
    "push_state": "skipped"|"drained"|"queued"|"unknown"|"failed"|None, "steps": {...}}.
    On ok=False the caller (retraining/orchestrator.py) sets
    retraining_events.status="failed" and appends `steps` to notes - the
    pipeline never proceeds to promotion on a vault failure. A push left queued
    only fails when config["require_push"] is true.
    """
    plan = build_commit_plan(version_id, add_paths, metrics, config)
    timeout = int(config.get("timeout_seconds", 120))
    steps: dict[str, dict] = {}
    av_binary = plan["add"][0]

    # A failed gate's leftovers must not land under this candidate's label.
    leftovers = staged_leftovers(av_binary, cwd=cwd, timeout=timeout)
    if leftovers:
        steps["staged_leftovers"] = {"ok": False, "paths": leftovers[:20], "error": "run `av unstage` first"}
        return {"ok": False, "stage": "staged_leftovers", "vault_commit": None, "push_state": None, "steps": steps}

    add_result = run_av_command(plan["add"], cwd=cwd, timeout=timeout)
    steps["add"] = add_result
    if not add_result["ok"]:
        return {"ok": False, "stage": "add", "vault_commit": None, "push_state": None, "steps": steps}

    commit_result = run_av_command(plan["commit"], cwd=cwd, timeout=timeout)
    steps["commit"] = commit_result
    if not commit_result["ok"]:
        error = (parse_av_envelope(commit_result["stdout"]) or {}).get("error") or {}
        if error.get("code") != "nothing_to_commit":
            return {"ok": False, "stage": "commit", "vault_commit": None, "push_state": None, "steps": steps}
        # An unchanged candidate is already in the vault: a retry after a killed run must succeed.
        vault_commit = current_head_hash(av_binary, cwd=cwd, timeout=timeout)
        if vault_commit is None:
            return {"ok": False, "stage": "commit", "vault_commit": None, "push_state": None, "steps": steps}
    else:
        vault_commit = parse_vault_commit_hash(commit_result["stdout"])

    if plan["push"] is None:
        return {"ok": True, "stage": "done", "vault_commit": vault_commit, "push_state": "skipped", "steps": steps}

    push_result = run_av_command(plan["push"], cwd=cwd, timeout=timeout)
    steps["push"] = push_result
    if not push_result["ok"]:
        return {"ok": False, "stage": "push", "vault_commit": vault_commit, "push_state": "failed", "steps": steps}

    push_state = parse_push_state(push_result["stdout"])
    if push_state == "queued" and config.get("require_push", False):
        return {"ok": False, "stage": "push", "vault_commit": vault_commit, "push_state": push_state, "steps": steps}
    return {"ok": True, "stage": "done", "vault_commit": vault_commit, "push_state": push_state, "steps": steps}


def restore_candidate_from_vault(commit_hash: str, relative_dir: str, config: dict, cwd: Path | None = None) -> dict:
    """Restores one candidate directory from a vault commit, touching nothing else.

    A repo-wide `av checkout` must never be used for this: it overwrites main.py, train.py and
    config.json and deletes every file the old commit did not track.
    """
    argv = build_av_restore_command(commit_hash, [relative_dir], av_binary=config.get("av_binary", "av"))
    return run_av_command(argv, cwd=cwd, timeout=int(config.get("timeout_seconds", 120)))
