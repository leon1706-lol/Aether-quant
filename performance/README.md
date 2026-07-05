# performance

Owns the V2-16 performance trigger system: detects, scores and durably logs
warning signs in live/observation/backtest activity — but never retrains
anything itself. `retrain_candidate` is a flag consumed by `retraining/`
(V2-17), not an action taken here.

- `triggers.py` (pure) — 14 trigger functions
  (`observation_count_trigger`, `drawdown_trigger`,
  `sharpe_degradation_trigger`, `win_rate_trigger`,
  `confidence_decay_trigger`, `regime_shift_trigger`,
  `liquidity_warning_trigger`, `risk_lock_trigger`, and, added in V2-17.5,
  `topology_uncertainty_trigger`, `topology_regime_mismatch_trigger`,
  `cluster_drift_trigger`, `model_topology_disagreement_trigger`,
  `trigger_frequency_spike`) plus `evaluate_all_triggers()`, operating on
  the same source-agnostic `list[dict]` of experience-event dicts that
  `experience/observation_metrics.py` established in V2-15 — reuses its
  `simulated_sharpe`/`simulated_max_drawdown` rather than reimplementing
  them. Each fired trigger carries `severity` (breach-ratio rule: ≥1.5x
  past threshold → `critical`) and a `retrain_candidate` boolean. The four
  topology triggers are persistence-guarded (a rolling-window average
  breach plus a minimum fraction of individually-breaching bars) so a
  single noisy observation never fires them; `trigger_frequency_spike` is a
  meta-trigger over trigger *rows*, not events, and is the one exception
  wired in only when `evaluate_all_triggers()`'s new optional
  `recent_triggers` argument is supplied. V2-22 adds
  `live_order_permission_blocked_trigger` — a deployment-health trigger
  (fires `critical` when `mode == "live"` but orders are still being
  simulated) that's deliberately excluded from `retrain_candidate` via a
  `_NON_RETRAIN_TRIGGERS` set, since a broker misconfiguration is an ops
  problem, not something a new model version fixes.
- `postgres_triggers.py` (IO) — embedded DDL for the durable
  `performance_triggers` table (the system of record — separate from
  `experience_events` so Grafana/V2-17 can query it cleanly) plus a
  `performance_trigger_watermark` table for incremental polling, suppression
  -window dedup on insert, `fetch_candidate_triggers()` (added in V2-17)
  for `retraining/planning.py` to read `retrain_candidate=true` rows, and
  (V2-17.5) `fetch_recent_events()` (a true rolling-window read, distinct
  from the incremental `fetch_events_since()`), `fetch_triggers_since()`
  and `fetch_last_retraining_at()` (best-effort, never raises).
- `trigger_worker.py` — standalone worker (`python -m
  performance.trigger_worker [--once]`) that polls `experience_events` past
  the watermark to advance it cheaply, but (V2-17.5) evaluates triggers
  over a real rolling window instead — the last `rolling_window_events`
  observations bounded to `rolling_window_days` or since the last
  promoted/validated retrain, whichever is more recent — fixing the V2-16
  limitation where evaluation only ever saw whatever arrived since the
  last poll. Reads `config.json`'s `phase_v2.performance_triggers`
  thresholds directly (no Redis dependency — this worker never touches the
  Redis stream).
- `main.py` additionally keeps a fast, **non-durable**, in-memory-only view
  (`_build_performance_triggers_view()`) for the current run's dashboard —
  the Postgres table populated by `trigger_worker.py` is the only source
  V2-17 reads from.

Dashboard/API: `visualization/grafana/performance_triggers.json`,
`/api/grafana/performance-triggers`, and the webui's
`PerformanceTriggersPanel.tsx`.
