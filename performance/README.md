# performance

Detects, scores and logs warning signs. It never retrains anything itself: `retrain_candidate` is a flag `retraining/` reads.

- **`triggers.py` (pure):** the trigger functions and `evaluate_all_triggers()`, over the same event dicts as `experience/observation_metrics.py`.
  - **Covers:** observation count, drawdown, Sharpe, win rate, confidence decay, regime shift, liquidity, risk lock, topology, trigger frequency, blocked live orders and trade counts.
  - **Severity:** 1.5x past the threshold is `critical`.
  - **Persistence:** topology triggers need a sustained breach, so one noisy bar can't fire them.
  - **Ops, not model:** broker and execution triggers are in `_NON_RETRAIN_TRIGGERS`, because a new model doesn't fix them.
- **`rank_ic_monitor.py`:** joins each prediction to its realized 20-day return, for `rank_ic_decay_trigger()`.
- **`postgres_triggers.py`:** the durable `performance_triggers` table and polling watermark, with deduplication on insert.
- **`trigger_worker.py`:** `python -m performance.trigger_worker [--once]` evaluates a real rolling window (`phase_v2.performance_triggers`), bounded to the last promoted retrain. Doesn't touch Redis.

`main.py` also keeps a fast, non-durable view for the dashboard (`_build_performance_triggers_view()`); only the Postgres table feeds `retraining/`.

The research cycle's decay tracking is separate: `aq cycle status`.
