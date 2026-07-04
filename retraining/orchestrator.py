"""Retraining pipeline orchestrator (Phase V2-17).

Exposes each pipeline stage (plan, train, validate, backtest, commit,
promote, rollback, status) as both a plain Python function (called by
retraining/worker.py's continuous loop) and a CLI subcommand (for manual,
staged, one-stage-at-a-time invocation - `python -m retraining.orchestrator
<stage> ...`). This dual use is what lets retraining run either as a
toggleable continuous worker or purely on-demand.

Reads config.json's phase_v2.retraining block directly, mirroring
performance/trigger_worker.py's _load_performance_triggers_config()
convention - these are strategy thresholds, not infra config.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from performance.postgres_triggers import ensure_schema as ensure_performance_schema
from performance.postgres_triggers import fetch_candidate_triggers
from retraining import planning
from retraining.artifacts import (
    ACTIVE_ARTIFACT_FILES,
    ALL_TRACKED_FILES,
    candidate_dir,
    check_required_artifacts,
    compute_artifact_hashes,
    copy_backtest_report_to_active,
    copy_candidate_to_active,
    restore_active_from_version,
)
from retraining.backtest_gate import compare_backtests
from retraining.lean_backtest import run_lean_backtest
from retraining.postgres_registry import (
    count_experience_events,
    ensure_schema,
    fetch_active_model_version,
    fetch_model_version,
    fetch_recent_retraining_events,
    insert_model_version,
    insert_retraining_event,
    promote_model_version,
    update_model_version_status,
    update_retraining_event_status,
)
from retraining.status_export import build_status_view, write_status_file
from retraining.validation_gate import evaluate_validation_gate
from retraining.vault_client import commit_candidate_to_vault, run_av_command
from risk.manual_override import write_manual_trade_lock_override

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
ML_DIR = ROOT_DIR / "ml"
BACKTESTS_DIR = ROOT_DIR / "backtests"
ACTIVE_TRAINING_METRICS_PATH = ML_DIR / "training_metrics.json"
ACTIVE_STRATEGY_REPORT_PATH = BACKTESTS_DIR / "strategy_report.json"
_CONFIG_PATH = ROOT_DIR / "config.json"

_PLAN_LOOKBACK_DAYS = 30


def _load_retraining_config(config_path: Path = _CONFIG_PATH) -> dict:
    with config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)
    return config.get("phase_v2", {}).get("retraining", {})


def _load_json_if_exists(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def connect(postgres_dsn: str = ""):
    import psycopg

    dsn = os.environ.get("AETHER_POSTGRES_DSN", postgres_dsn)
    conn = psycopg.connect(dsn, autocommit=False)
    ensure_schema(conn)
    ensure_performance_schema(conn)  # performance_triggers table must exist before we read it
    return conn


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------


def plan(conn, config: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    triggers = fetch_candidate_triggers(conn, limit=50)
    recent_events = fetch_recent_retraining_events(
        conn, since=now - timedelta(days=_PLAN_LOOKBACK_DAYS), limit=200
    )
    observation_count = count_experience_events(conn)

    result = planning.evaluate_retraining_plan(triggers, recent_events, observation_count, config, now)

    if result["should_plan"]:
        retraining_id = str(uuid.uuid4())
        selected = result["selected_trigger"]
        insert_retraining_event(
            conn,
            {
                "retraining_id": retraining_id,
                "source_trigger_id": selected["trigger_id"] if selected else None,
                "candidate_version_id": None,
                "status": "planned",
                "reason": result["reason"],
                "metrics": {},
                "notes": [],
            },
        )
        result["retraining_id"] = retraining_id
        logger.info("plan: retraining %s planned - %s", retraining_id, result["reason"])
    else:
        logger.info("plan: not planning - %s", result["reason"])

    return result


def train(conn, retraining_id: str, version_id: str | None = None, timeout_seconds: int = 3600) -> dict:
    """Runs `python train.py --candidate --version-id <id>` as a subprocess.

    Training is CPU/GPU-heavy and must not block the worker's own event loop
    or share its Postgres connection lifetime - hence a subprocess, not an
    in-process import of train.py.
    """
    version_id = version_id or str(uuid.uuid4())
    update_retraining_event_status(conn, retraining_id, status="running", candidate_version_id=version_id)
    insert_model_version(conn, {"model_version_id": version_id, "status": "candidate"})

    train_script = ROOT_DIR / "train.py"
    try:
        result = subprocess.run(
            [sys.executable, str(train_script), "--candidate", "--version-id", version_id],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except Exception as exc:  # never let a training subprocess crash the orchestrator
        logger.error("train: subprocess failed to launch - %s", exc)
        update_retraining_event_status(conn, retraining_id, status="failed", notes=[{"stage": "train", "error": str(exc)}])
        update_model_version_status(conn, version_id, status="rejected")
        return {"ok": False, "version_id": version_id, "error": str(exc)}

    if result.returncode != 0:
        logger.error("train: candidate %s training failed - %s", version_id, result.stderr[-2000:])
        update_retraining_event_status(
            conn,
            retraining_id,
            status="failed",
            notes=[{"stage": "train", "returncode": result.returncode, "stderr": result.stderr[-2000:]}],
        )
        update_model_version_status(conn, version_id, status="rejected")
        return {"ok": False, "version_id": version_id, "error": result.stderr}

    logger.info("train: candidate %s trained.", version_id)
    return {"ok": True, "version_id": version_id, "stdout": result.stdout}


def train_topology(conn, retraining_id: str, version_id: str, config: dict, timeout_seconds: int | None = None) -> dict:
    """Runs `python train_topology.py --version-id <id>` as a second,
    independently-failable subprocess (V2-17.5), between `train` and
    `validate`. Learned-topology training is best-effort: unlike `train`,
    a failure here is logged and swallowed - it never rejects the
    candidate model_version or overwrites a later stage's retraining_events
    status transition, it only appends a note. topology_model.json etc. are
    optional artifacts (see retraining/artifacts.py's OPTIONAL_TOPOLOGY_FILES)
    precisely so this stage can fail without blocking the primary model.
    """
    topology_config = config.get("topology_training", {})
    if not topology_config.get("enabled", True):
        return {"ok": False, "version_id": version_id, "reason": "topology_training_disabled"}

    timeout_seconds = timeout_seconds or int(topology_config.get("timeout_seconds", 900))
    train_topology_script = ROOT_DIR / "train_topology.py"
    try:
        result = subprocess.run(
            [sys.executable, str(train_topology_script), "--version-id", version_id],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except Exception as exc:  # never let a best-effort subprocess crash the orchestrator
        logger.warning("train_topology: subprocess failed to launch for %s - %s", version_id, exc)
        update_retraining_event_status(
            conn, retraining_id, status="running", notes=[{"stage": "train_topology", "error": str(exc)}]
        )
        return {"ok": False, "version_id": version_id, "error": str(exc)}

    if result.returncode != 0:
        logger.warning(
            "train_topology: candidate %s topology training failed (rc=%d) - continuing without it.",
            version_id,
            result.returncode,
        )
        update_retraining_event_status(
            conn,
            retraining_id,
            status="running",
            notes=[{"stage": "train_topology", "returncode": result.returncode, "stderr": result.stderr[-2000:]}],
        )
        return {"ok": False, "version_id": version_id, "error": result.stderr}

    logger.info("train_topology: candidate %s topology model trained (or skipped for insufficient data).", version_id)
    return {"ok": True, "version_id": version_id, "stdout": result.stdout}


def validate(conn, retraining_id: str, version_id: str, config: dict) -> dict:
    version_dir = candidate_dir(version_id)
    present, missing = check_required_artifacts(version_dir)
    if not present:
        reason = f"missing_candidate_artifacts: {missing}"
        update_model_version_status(conn, version_id, status="rejected")
        update_retraining_event_status(conn, retraining_id, status="rejected", reason=reason)
        return {"ok": False, "reason": reason}

    candidate_metrics = _load_json_if_exists(version_dir / "training_metrics.json")
    candidate_report = _load_json_if_exists(version_dir / "strategy_report.json")
    active_metrics = _load_json_if_exists(ACTIVE_TRAINING_METRICS_PATH)
    active_report = _load_json_if_exists(ACTIVE_STRATEGY_REPORT_PATH)

    gate_result = evaluate_validation_gate(
        candidate_metrics, candidate_report, active_metrics, active_report, config.get("validation_gate", {})
    )

    if not gate_result["passed"]:
        update_model_version_status(conn, version_id, status="rejected", metrics={"validation_gate": gate_result})
        update_retraining_event_status(
            conn,
            retraining_id,
            status="rejected",
            metrics={"validation_gate": gate_result},
            reason=f"validation_gate_failed: {gate_result['failures']}",
        )
        logger.info("validate: candidate %s rejected - %s", version_id, gate_result["failures"])
        return {"ok": False, "gate": gate_result}

    update_model_version_status(conn, version_id, status="candidate", metrics={"validation_gate": gate_result})
    logger.info("validate: candidate %s passed validation gate.", version_id)
    return {"ok": True, "gate": gate_result}


def backtest(conn, retraining_id: str, version_id: str, config: dict) -> dict:
    version_dir = candidate_dir(version_id)
    candidate_report = _load_json_if_exists(version_dir / "strategy_report.json")
    active_report = _load_json_if_exists(ACTIVE_STRATEGY_REPORT_PATH)

    comparison = compare_backtests(active_report, candidate_report, config.get("backtest_gate", {}))
    lean_result = run_lean_backtest(version_dir, config.get("backtest_gate", {}))
    report = {"comparison": comparison, "lean": lean_result}

    report_path = BACKTESTS_DIR / f"candidate_{version_id}_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    passed = comparison["passed"]
    status = "candidate" if passed else "rejected"
    update_model_version_status(conn, version_id, status=status, metrics={"backtest_gate": report})
    update_retraining_event_status(
        conn,
        retraining_id,
        status=("running" if passed else "rejected"),
        metrics={"backtest_gate": report},
        reason=("backtest_gate_passed" if passed else f"backtest_gate_failed: {comparison['reasons']}"),
    )
    logger.info("backtest: candidate %s %s.", version_id, "passed" if passed else "rejected")
    return {"ok": passed, "report": report}


def commit(conn, retraining_id: str, version_id: str, config: dict) -> dict:
    version_dir = candidate_dir(version_id)
    vault_config = config.get("vault", {})
    add_paths = list(vault_config.get("add_paths", ["train.py", "main.py", "config.json"]))
    add_paths.append(str(version_dir.relative_to(ROOT_DIR)))

    candidate_report = _load_json_if_exists(version_dir / "strategy_report.json")
    strategy = candidate_report.get("backtest", {}).get("strategy", {})
    metrics = {
        "sharpe": float(strategy.get("sharpe", 0.0) or 0.0),
        "drawdown": float(strategy.get("max_drawdown", 0.0) or 0.0),
    }

    result = commit_candidate_to_vault(version_id, add_paths, metrics, vault_config, cwd=ROOT_DIR)

    if not result["ok"]:
        update_retraining_event_status(
            conn, retraining_id, status="failed", notes=[{"stage": "commit", "steps": result["steps"]}]
        )
        logger.warning("commit: candidate %s vault commit failed at stage %s.", version_id, result["stage"])
        return result

    hashes = compute_artifact_hashes(version_dir, filenames=ALL_TRACKED_FILES)
    update_model_version_status(
        conn,
        version_id,
        status="candidate",
        aether_vault_commit=result["vault_commit"],
        artifact_hashes=hashes,
    )
    update_retraining_event_status(
        conn,
        retraining_id,
        status="validated",
        candidate_version_id=version_id,
        metrics={"vault_commit": result["vault_commit"]},
        reason="vault_commit_succeeded",
    )
    logger.info("commit: candidate %s committed to vault (%s).", version_id, result["vault_commit"])
    return result


def promote(conn, version_id: str, retraining_id: str | None = None, config: dict | None = None) -> dict:
    config = config or {}
    version = fetch_model_version(conn, version_id)
    if version is None:
        return {"ok": False, "error": "model_version_not_found"}
    if version.get("status") != "candidate":
        return {"ok": False, "error": "promotion_requires_validated_candidate_status"}
    if config.get("promotion", {}).get("require_vault_commit", True) and not version.get("aether_vault_commit"):
        return {"ok": False, "error": "promotion_requires_vault_commit"}

    active_files = tuple(config.get("promotion", {}).get("active_artifact_files", ACTIVE_ARTIFACT_FILES))
    version_dir = candidate_dir(version_id)
    active = fetch_active_model_version(conn)

    hashes = copy_candidate_to_active(version_dir, ml_dir=ML_DIR, filenames=active_files)
    copy_backtest_report_to_active(version_dir, BACKTESTS_DIR)

    promote_model_version(conn, old_active_id=active["model_version_id"] if active else None, new_active_id=version_id)
    update_model_version_status(conn, version_id, status="active", artifact_hashes=hashes)
    if retraining_id:
        update_retraining_event_status(conn, retraining_id, status="promoted")

    write_status_file(build_status_view(conn))
    logger.info("promote: %s is now the active model.", version_id)

    if config.get("promotion", {}).get("auto_clear_trade_lock", True):
        write_manual_trade_lock_override(False, _CONFIG_PATH)
        logger.info("promote: cleared trade-lock override so trading resumes on the new model.")

    return {"ok": True, "version_id": version_id}


def rollback(conn, to_version_id: str, config: dict | None = None) -> dict:
    config = config or {}
    target = fetch_model_version(conn, to_version_id)
    if target is None or target.get("status") not in ("archived", "rolled_back", "active"):
        return {"ok": False, "error": "rollback_target_not_eligible"}

    active_files = tuple(config.get("promotion", {}).get("active_artifact_files", ACTIVE_ARTIFACT_FILES))
    version_dir = candidate_dir(to_version_id)
    expected_hashes = target.get("artifact_hashes") or None

    restore_result = restore_active_from_version(
        version_dir, ml_dir=ML_DIR, filenames=active_files, expected_hashes=expected_hashes
    )

    if not restore_result["ok"] and target.get("aether_vault_commit"):
        vault_config = config.get("vault", {})
        av_binary = vault_config.get("av_binary", "av")
        checkout_result = run_av_command(
            [av_binary, "checkout", target["aether_vault_commit"]], cwd=ROOT_DIR
        )
        if checkout_result["ok"]:
            restore_result = restore_active_from_version(
                version_dir, ml_dir=ML_DIR, filenames=active_files, expected_hashes=expected_hashes
            )

    if not restore_result["ok"]:
        logger.error("rollback: artifact restore failed for %s - %s", to_version_id, restore_result)
        return {"ok": False, "error": "artifact_hash_mismatch", "details": restore_result}

    current_active = fetch_active_model_version(conn)
    promote_model_version(
        conn,
        old_active_id=current_active["model_version_id"] if current_active else None,
        new_active_id=to_version_id,
    )
    update_model_version_status(conn, to_version_id, status="active")
    if current_active:
        update_model_version_status(conn, current_active["model_version_id"], status="rolled_back")

    retraining_id = str(uuid.uuid4())
    insert_retraining_event(
        conn,
        {
            "retraining_id": retraining_id,
            "source_trigger_id": None,
            "candidate_version_id": to_version_id,
            "status": "promoted",
            "reason": f"rollback to {to_version_id}",
            "metrics": {},
            "notes": [],
        },
    )

    write_status_file(build_status_view(conn))
    logger.info("rollback: %s restored as active model.", to_version_id)
    return {"ok": True, "version_id": to_version_id}


def status(conn) -> dict:
    view = build_status_view(conn)
    write_status_file(view)
    return view


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
    parser = argparse.ArgumentParser(description="Aether Quant retraining orchestrator")
    subparsers = parser.add_subparsers(dest="stage", required=True)

    subparsers.add_parser("plan")

    train_parser = subparsers.add_parser("train")
    train_parser.add_argument("--retraining-id", required=True)
    train_parser.add_argument("--version-id", default=None)

    train_topology_parser = subparsers.add_parser("train_topology")
    train_topology_parser.add_argument("--retraining-id", required=True)
    train_topology_parser.add_argument("--version-id", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--retraining-id", required=True)
    validate_parser.add_argument("--version-id", required=True)

    backtest_parser = subparsers.add_parser("backtest")
    backtest_parser.add_argument("--retraining-id", required=True)
    backtest_parser.add_argument("--version-id", required=True)

    commit_parser = subparsers.add_parser("commit")
    commit_parser.add_argument("--retraining-id", required=True)
    commit_parser.add_argument("--version-id", required=True)

    promote_parser = subparsers.add_parser("promote")
    promote_parser.add_argument("--version-id", required=True)
    promote_parser.add_argument("--retraining-id", default=None)

    rollback_parser = subparsers.add_parser("rollback")
    rollback_parser.add_argument("--to-version-id", required=True)

    subparsers.add_parser("status")

    args = parser.parse_args()
    config = _load_retraining_config()
    conn = connect()
    try:
        if args.stage == "plan":
            print(json.dumps(plan(conn, config), indent=2, default=str))
        elif args.stage == "train":
            print(json.dumps(train(conn, args.retraining_id, args.version_id), indent=2, default=str))
        elif args.stage == "train_topology":
            print(json.dumps(train_topology(conn, args.retraining_id, args.version_id, config), indent=2, default=str))
        elif args.stage == "validate":
            print(json.dumps(validate(conn, args.retraining_id, args.version_id, config), indent=2, default=str))
        elif args.stage == "backtest":
            print(json.dumps(backtest(conn, args.retraining_id, args.version_id, config), indent=2, default=str))
        elif args.stage == "commit":
            print(json.dumps(commit(conn, args.retraining_id, args.version_id, config), indent=2, default=str))
        elif args.stage == "promote":
            print(json.dumps(promote(conn, args.version_id, args.retraining_id, config), indent=2, default=str))
        elif args.stage == "rollback":
            print(json.dumps(rollback(conn, args.to_version_id, config), indent=2, default=str))
        elif args.stage == "status":
            print(json.dumps(status(conn), indent=2, default=str))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
