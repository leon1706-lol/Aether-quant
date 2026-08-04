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
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from execution.runtime_config_io import read_runtime_mode
from retraining.orchestrator import (
    _CONFIG_PATH,
    _load_retraining_config,
    auto_rollback_status,
    backtest,
    commit,
    plan,
    promote,
    reconcile_stale_running_events,
    rollback,
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
from performance.postgres_triggers import ensure_schema as ensure_performance_schema, fetch_triggers_since, insert_triggers

logger = logging.getLogger(__name__)

# V5.1 Phase 6 (production safety) - main.py's Phase 6 wiring writes
# kill_switch.tripped into this same file every bar (see main.py::
# _write_state()) - this worker never opens a connection to Lean's
# process, it only reads the locally-mounted file, same "read a file a
# separate process keeps fresh" pattern main.py itself uses in the other
# direction for retraining_status.json.
_STATE_PATH = Path(__file__).resolve().parent.parent / "visualization" / "state.json"


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

    def _live_degradation_signals(self) -> dict:
        """V5.1 Phase 6 (production safety) - best-effort, never raises:
        each individual signal degrades to False on any read failure,
        matching this file's own "a best-effort stage's failure never
        blocks the rest of the cycle" convention (train_topology()/
        train_gating()/etc.). Two independent sources:
          - kill_switch_tripped: state.json's kill_switch.tripped, written
            every bar by main.py's own Phase 6 wiring.
          - net_sharpe_decay / rank_ic_decay: whether a
            sharpe_degradation_trigger / rank_ic_decay_trigger
            (performance/triggers.py's own exact trigger_type strings -
            NOT the more abstract net_sharpe_decay/rank_ic_decay names
            phase_v2.retraining.auto_rollback.triggers uses, which is why
            this method exists rather than reading trigger rows verbatim)
            landed in performance_triggers within the lookback window."""
        signals = {"kill_switch_tripped": False, "net_sharpe_decay": False, "rank_ic_decay": False}

        try:
            if _STATE_PATH.exists():
                state = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
                signals["kill_switch_tripped"] = bool(state.get("kill_switch", {}).get("tripped", False))
        except Exception as error:
            logger.warning("RetrainingWorker: failed to read live kill-switch state - %s", error)

        try:
            lookback_hours = int(self.config.get("auto_rollback", {}).get("degradation_signal_lookback_hours", 24))
            since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
            trigger_types = {row.get("trigger_type") for row in fetch_triggers_since(self._conn, since)}
            signals["net_sharpe_decay"] = "sharpe_degradation_trigger" in trigger_types
            signals["rank_ic_decay"] = "rank_ic_decay_trigger" in trigger_types
        except Exception as error:
            logger.warning("RetrainingWorker: failed to read recent performance triggers - %s", error)

        return signals

    def _notify_auto_rollback(self, decision: dict, rollback_result: dict) -> None:
        """Manually constructs a performance_triggers row matching
        performance/triggers.py::_make_trigger()'s exact field shape,
        rather than calling that function - _make_trigger() dispatches on
        a FIXED set of trigger_type strings via its own internal
        _RECOMMENDED_ACTIONS/_is_retrain_candidate dicts that don't (and
        shouldn't) know about auto-rollback. Reuses the SAME
        insert_triggers() -> notifications/telegram_worker.py poll-and-
        alert pathway every other trigger in this codebase already goes
        through - this worker never calls Telegram directly."""
        trigger_row = {
            "trigger_id": str(uuid4()),
            "created_at": datetime.now(timezone.utc),
            "trigger_type": "auto_rollback_triggered",
            "severity": "critical",
            "mode": "live",
            "scope": "model",
            "metric_value": None,
            "threshold": None,
            "message": f"Auto-rollback: {decision.get('reason', '')}",
            "recommended_action": (
                f"Rolled back active model to {decision.get('to_version_id')}"
                if rollback_result.get("ok")
                else "Auto-rollback attempt FAILED - manual intervention required"
            ),
            "retrain_candidate": False,
        }
        try:
            insert_triggers(self._conn, [trigger_row])
        except Exception as error:
            logger.error("RetrainingWorker: failed to insert auto-rollback notification trigger - %s", error)

    def check_auto_rollback(self) -> dict:
        """V5.1 Phase 6 (production safety) - fully independent of
        run_once()'s plan->train->...->promote pipeline: this asks "is the
        model CURRENTLY ACTIVE in production degrading enough to roll
        back", not "should a new candidate be trained". Runs
        orchestrator.auto_rollback_status() (the exact same read-only
        diagnostic `aq retrain auto-rollback --status` uses) with live
        degradation signals overlaid, and only calls the existing,
        previously manual-stage-only orchestrator.rollback() when
        phase_v2.retraining.auto_rollback.enabled is True AND the pure
        selector (retraining/auto_rollback.py::select_rollback_target())
        says so. Best-effort - never raises, matching this file's own
        run()-loop exception handling."""
        result = auto_rollback_status(self._conn, self.config, degradation_overrides=self._live_degradation_signals())
        decision = result["decision"]

        if decision["should_rollback"]:
            logger.warning("RetrainingWorker: auto-rollback triggered - %s", decision["reason"])
            rollback_result = rollback(self._conn, decision["to_version_id"], self.config)
            self._notify_auto_rollback(decision, rollback_result)
            result = {**result, "rollback_result": rollback_result}

        return result

    def run(self) -> None:
        logger.info("RetrainingWorker: entering run loop.")
        while True:
            try:
                result = self.run_once()
                logger.info("RetrainingWorker: cycle result - %s", result)
                # V5.1 Phase 6 (production safety) - a SEPARATE check from
                # run_once() above, on the same poll cadence: run_once()
                # asks whether to train/promote a NEW candidate,
                # check_auto_rollback() asks whether the model CURRENTLY
                # ACTIVE in production should be rolled back. Both are
                # best-effort and independent - one failing/no-op-ing never
                # affects the other.
                try:
                    rollback_check = self.check_auto_rollback()
                    if rollback_check["decision"]["should_rollback"]:
                        logger.warning("RetrainingWorker: auto-rollback cycle result - %s", rollback_check)
                except Exception as exc:
                    logger.error("RetrainingWorker: check_auto_rollback() failed - %s", exc)
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
