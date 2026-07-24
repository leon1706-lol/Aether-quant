"""Continuous, toggleable retraining worker (Phase V2-17).

Mirrors performance/trigger_worker.py's TriggerWorker shape (Postgres-only,
--once CLI flag, _pg_conn injection for tests, config read from config.json
directly). Unlike TriggerWorker, each run_once() cycle can drive the full
plan -> train -> validate -> backtest -> commit -> (promote) pipeline via
retraining/orchestrator.py's stage functions.

Three safety knobs keep this "no uncontrolled live learning":
- config["enabled"] (phase_v2.retraining.enabled): a live off-switch checked
  every cycle - flip it in config.json without touching the running
  container.
- config["worker"]["auto_promote"] (default False): the worker stops after
  a successful vault commit (status="validated") and leaves promotion for a
  manual `python -m retraining.orchestrator promote --version-id <id>` call.
  Only when explicitly set True does the worker call promote() itself.
- config["worker"]["auto_promote_blocked_in_live_mode"] (default True,
  V2-22): even with auto_promote=True, the worker forces manual promotion
  whenever phase_v2.runtime.mode == "live" - full autonomy is fine while no
  live trading exists yet, but a model change should not silently go live
  without a human looking at it once real orders are possible.
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from pathlib import Path

from execution.runtime_config_io import read_runtime_mode
from retraining.orchestrator import (
    _CONFIG_PATH,
    _load_retraining_config,
    backtest,
    commit,
    plan,
    promote,
    reconcile_stale_running_events,
    status,
    train,
    train_gating,
    train_multitask,
    train_sequence,
    train_strategy_selector,
    train_topology,
    validate,
)
from retraining.postgres_registry import ensure_schema
from performance.postgres_triggers import ensure_schema as ensure_performance_schema

logger = logging.getLogger(__name__)


class RetrainingWorker:
    """Drives the retraining pipeline on a poll interval.

    Parameters
    ----------
    postgres_dsn  : psycopg3 DSN (overridden by AETHER_POSTGRES_DSN env)
    config        : phase_v2.retraining config dict
    poll_interval : seconds to sleep between polls in run()
    _pg_conn      : injected psycopg3 connection (skips real connection — tests only)
    """

    def __init__(
        self,
        *,
        postgres_dsn: str = "",
        config: dict,
        poll_interval: int = 300,
        config_path: Path = _CONFIG_PATH,
        _pg_conn=None,
    ) -> None:
        self.config = config
        self.poll_interval = poll_interval
        self._config_path = config_path

        if _pg_conn is not None:
            self._conn = _pg_conn
        else:
            import psycopg

            dsn = os.environ.get("AETHER_POSTGRES_DSN", postgres_dsn)
            self._conn = psycopg.connect(dsn, autocommit=False)
            logger.info("RetrainingWorker: PostgreSQL connected.")

        ensure_schema(self._conn)
        ensure_performance_schema(self._conn)

        # Reconcile any retraining_events row orphaned by a prior crash/
        # redeploy mid-cycle (see development/Problems.md #48) before the
        # poll loop starts - otherwise a single interrupted cycle silently
        # blocks every future retraining attempt for the full cooldown window.
        reconciled = reconcile_stale_running_events(self._conn, self.config)
        if reconciled:
            logger.warning("RetrainingWorker: reconciled %d orphaned retraining_events row(s) on startup.", len(reconciled))

    def run_once(self) -> dict:
        """Runs at most one full retraining cycle. Returns a summary dict.

        no-ops immediately (returns {"ran": False, "reason": "disabled"})
        if config["enabled"] is False - the master toggle.
        """
        if not self.config.get("enabled", True):
            return {"ran": False, "reason": "disabled"}

        plan_result = plan(self._conn, self.config)
        if not plan_result["should_plan"]:
            return {"ran": False, "reason": plan_result["reason"]}

        retraining_id = plan_result["retraining_id"]
        train_result = train(self._conn, retraining_id)
        if not train_result["ok"]:
            return {"ran": True, "reason": "train_failed", "retraining_id": retraining_id}

        version_id = train_result["version_id"]

        # Best-effort learned-topology training (V2-17.5) - failure here is
        # logged inside train_topology() itself and never blocks the
        # primary candidate's own validate/backtest/commit/promote path.
        train_topology(self._conn, retraining_id, version_id, self.config)

        # Best-effort learned-gating training - same contract, failure is
        # logged inside train_gating() itself and never blocks the primary
        # candidate's own validate/backtest/commit/promote path.
        train_gating(self._conn, retraining_id, version_id, self.config)

        # Best-effort multitask (direction+magnitude+volatility) training -
        # same contract, failure is logged inside train_multitask() itself
        # and never blocks the primary candidate's own validate/backtest/
        # commit/promote path.
        train_multitask(self._conn, retraining_id, version_id, self.config)

        # Best-effort Phase 2 sequence-encoder training - same contract,
        # failure is logged inside train_sequence() itself and never
        # blocks the primary candidate's own validate/backtest/commit/
        # promote path.
        train_sequence(self._conn, retraining_id, version_id, self.config)

        # Best-effort learned strategy-selector training (V4.7,
        # development/Problems.md #29's own framing) - same contract,
        # failure is logged inside train_strategy_selector() itself and
        # never blocks the primary candidate's own validate/backtest/
        # commit/promote path. Realistically a no-op skip every cycle in
        # this environment - see train_strategy_selector.py's own module
        # docstring for why.
        train_strategy_selector(self._conn, retraining_id, version_id, self.config)

        validate_result = validate(self._conn, retraining_id, version_id, self.config)
        if not validate_result["ok"]:
            return {"ran": True, "reason": "validation_failed", "retraining_id": retraining_id, "version_id": version_id}

        backtest_result = backtest(self._conn, retraining_id, version_id, self.config)
        if not backtest_result["ok"]:
            return {"ran": True, "reason": "backtest_failed", "retraining_id": retraining_id, "version_id": version_id}

        commit_result = commit(self._conn, retraining_id, version_id, self.config)
        if not commit_result["ok"]:
            return {"ran": True, "reason": "vault_commit_failed", "retraining_id": retraining_id, "version_id": version_id}

        worker_config = self.config.get("worker", {})
        auto_promote = bool(worker_config.get("auto_promote", False))
        auto_promote_blocked_in_live_mode = bool(worker_config.get("auto_promote_blocked_in_live_mode", True))
        if auto_promote and auto_promote_blocked_in_live_mode and read_runtime_mode(self._config_path) == "live":
            auto_promote = False
            logger.warning(
                "RetrainingWorker: auto_promote forced off because phase_v2.runtime.mode=='live' "
                "(V2-22 safety net) - promote manually via `aq retrain promote --version-id <id>`."
            )
        if auto_promote:
            promote_result = promote(self._conn, version_id, retraining_id, self.config)
            status(self._conn)
            return {
                "ran": True,
                "reason": "promoted" if promote_result["ok"] else "promotion_failed",
                "retraining_id": retraining_id,
                "version_id": version_id,
            }

        status(self._conn)
        return {
            "ran": True,
            "reason": "validated_awaiting_manual_promotion",
            "retraining_id": retraining_id,
            "version_id": version_id,
        }

    def run(self) -> None:
        logger.info("RetrainingWorker: entering run loop.")
        while True:
            try:
                result = self.run_once()
                logger.info("RetrainingWorker: cycle result - %s", result)
                time.sleep(self.poll_interval)
            except KeyboardInterrupt:
                logger.info("RetrainingWorker: shutdown requested.")
                break
            except Exception as exc:
                logger.error("RetrainingWorker error — %s. Retrying in %ds.", exc, self.poll_interval)
                time.sleep(self.poll_interval)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    parser = argparse.ArgumentParser(description="Aether Quant retraining worker")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    parser.add_argument("--poll-interval", type=int, default=None, help="Overrides phase_v2.retraining.worker.poll_interval_seconds")
    args = parser.parse_args()

    postgres_dsn = os.environ.get("AETHER_POSTGRES_DSN", "")
    config = _load_retraining_config()
    poll_interval = args.poll_interval
    if poll_interval is None:
        poll_interval = int(config.get("worker", {}).get("poll_interval_seconds", 300))

    worker = RetrainingWorker(postgres_dsn=postgres_dsn, config=config, poll_interval=poll_interval)
    try:
        if args.once:
            result = worker.run_once()
            logger.info("--once: %s", result)
        else:
            worker.run()
    finally:
        worker.close()


if __name__ == "__main__":
    main()
