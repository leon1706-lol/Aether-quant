# performance

Owns the V2-16 performance trigger system: detects, scores and durably logs
warning signs in live/observation/backtest activity — but never retrains
anything itself. `retrain_candidate` is a flag consumed by `retraining/`
(V2-17), not an action taken here.

- `triggers.py` (pure) — 8 trigger functions
  (`observation_count_trigger`, `drawdown_trigger`,
  `sharpe_degradation_trigger`, `win_rate_trigger`,
  `confidence_decay_trigger`, `regime_shift_trigger`,
  `liquidity_warning_trigger`, `risk_lock_trigger`) plus
  `evaluate_all_triggers()`, operating on the same source-agnostic
  `list[dict]` of experience-event dicts that `experience/observation_metrics.py`
  established in V2-15 — reuses its `simulated_sharpe`/`simulated_max_drawdown`
  rather than reimplementing them. Each fired trigger carries `severity`
  (breach-ratio rule: ≥1.5x past threshold → `critical`) and a
  `retrain_candidate` boolean.
- `postgres_triggers.py` (IO) — embedded DDL for the durable
  `performance_triggers` table (the system of record — separate from
  `experience_events` so Grafana/V2-17 can query it cleanly) plus a
  `performance_trigger_watermark` table for incremental polling, suppression
  -window dedup on insert, and `fetch_candidate_triggers()` (added in V2-17)
  for `retraining/planning.py` to read `retrain_candidate=true` rows.
- `trigger_worker.py` — standalone worker (`python -m
  performance.trigger_worker [--once]`) that polls `experience_events` past
  the watermark, evaluates triggers, and persists them. Reads
  `config.json`'s `phase_v2.performance_triggers` thresholds directly (no
  Redis dependency — this worker never touches the Redis stream).
- `main.py` additionally keeps a fast, **non-durable**, in-memory-only view
  (`_build_performance_triggers_view()`) for the current run's dashboard —
  the Postgres table populated by `trigger_worker.py` is the only source
  V2-17 reads from.

Dashboard/API: `visualization/grafana/performance_triggers.json`,
`/api/grafana/performance-triggers`, and the webui's
`PerformanceTriggersPanel.tsx`.
