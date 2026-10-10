# retraining

Owns Phase V2-17, Controlled Retraining: closes the loop `performance/`
(V2-16) deliberately left open. Reads `retrain_candidate = true` rows out
of the durable `performance_triggers` table, trains a candidate model in
isolation, validates and backtests it against the currently active model,
commits it to Aether-Vault, and only then may promote it to active — with
rollback always available. See `development/architecture.md`'s
"Controlled Retraining Contract (V2-17)" section for the full design
writeup; this file is the short version.

**No uncontrolled live learning** is the hard constraint: every stage is a
Postgres-audited row (`retraining_events`/`model_versions`). Full autonomy
(the worker auto-promoting without a human looking) is controlled by
`phase_v2.retraining.worker.auto_promote` — `true` by default as of V2-22,
judged safe because no live trading exists yet. The moment
`phase_v2.runtime.mode` is genuinely `"live"`,
`phase_v2.retraining.worker.auto_promote_blocked_in_live_mode` (`true` by
default) forces manual promotion regardless of `auto_promote` — see
`execution/runtime_config_io.py` and the Live Deployment Contract in
`development/architecture.md`.

Files (pure/IO/worker split, matching `performance/`'s V2-16 convention):

- `planning.py` (pure) — `evaluate_retraining_plan()`: picks the
  highest-priority eligible trigger (V2-17.5: severity + trigger-type
  weight + a regime-shift/topology co-occurrence bonus + a repeated-
  trigger bonus, ties broken by newest — see
  `development/architecture.md`'s V2-17.5 section), then checks minimum
  observations, cooldown, and a daily retraining cap, in that order.
  `rank_ic_decay_trigger` (Phase 6 of the 5/10 -> 9/10 roadmap,
  `performance/rank_ic_monitor.py`) is registered in `_TYPE_BASE_SCORE` at
  the same weight as `sharpe_degradation_trigger` — no other change
  needed, this function already generically handles any
  `retrain_candidate=true` trigger type.
- `postgres_registry.py` (IO) — embedded DDL for `model_versions` and
  `retraining_events`; a partial unique index enforces exactly one `active`
  model version at the DB level.
- `validation_gate.py` (pure) — candidate-vs-**active** comparison
  (drawdown, Sharpe, validation-loss stability, overfitting gap, trade
  count/exposure), mirroring `train.py`'s `assess_expert_quality()` shape.
  V5.4.7 (#122): missing/non-finite metrics fail CLOSED with explicit
  reasons (`active_baseline_metrics_missing`, `candidate_*_missing_or_non_finite`)
  - the old fake-zero defaults either deadlocked all promotion or let NaN
  pass every comparison.
- `backtest_gate.py` (pure) + `lean_backtest.py` (best-effort IO) — 3-way
  active/candidate/buy-and-hold comparison, plus an optional real Lean
  backtest that only runs if `shutil.which("lean")` finds a binary.
- `vault_commands.py` (pure) + `vault_client.py` (IO) — builds and runs
  `av add`/`av commit`/`av push`; a missing `av` binary, timeout, or
  non-zero exit always resolves to a `failed` retraining event, never a
  crash. Aether-Vault is invoked purely as this external CLI subprocess —
  its source is never read or imported.
- `artifacts.py` (IO) — candidate artifact completeness checks, SHA-256
  hashing, and the copy/restore primitives promotion and rollback share.
  V2-17.5 adds `OPTIONAL_TOPOLOGY_FILES` (`topology_model.json`,
  `topology_training_metrics.json`, `topology_feature_schema.json`) —
  included in `ACTIVE_ARTIFACT_FILES`/`ALL_TRACKED_FILES` but deliberately
  **not** `REQUIRED_CANDIDATE_FILES`, so a candidate is never rejected for
  missing topology artifacts. `OPTIONAL_GATING_FILES` (`gating_model.json`
  + 2 more), `OPTIONAL_MULTITASK_FILES` (`multitask_model.json`,
  `multitask_feature_schema.json`, `multitask_training_metrics.json`) and
  `OPTIONAL_SEQUENCE_FILES` (`sequence_model.json`,
  `sequence_feature_schema.json`, `sequence_training_metrics.json`, Phase
  2) all follow the identical optional/best-effort contract.
- `status_export.py` (IO) — the sole writer of
  `visualization/grafana/retraining_status.json`, including an
  `auto_rollback` section (see below).
- `auto_rollback.py` (pure) — `select_rollback_target()`: whether the
  currently-active model should be rolled back given live degradation
  signals, a minimum runway since promotion, a cooldown since the last
  rollback, and a target that previously passed the validation gate.
- `rollback_hardening.py` (V5.4.1, pure) — hardening utilities for the
  above: `compute_degradation_score()` (a continuous 0–1 weighted
  composite replacing pass/fail-only signals) and
  `select_rollback_target_dry_run()` (the same return shape as
  `select_rollback_target()` plus `dry_run: True` and the degradation
  score, for audit without execution).
- `orchestrator.py` — `plan`/`train`/`validate`/`backtest`/`commit`/
  `promote`/`rollback`/`status`, each usable as a library function or a CLI
  subcommand (`python -m retraining.orchestrator <stage> ...`) for
  manual/staged runs independent of the worker, plus `train_strategy_selector`.
  Independently-failable subprocess stages run between `train` and
  `validate`, in order: `train_topology` (`../train_topology.py`), `train_gating`
  (`../train_gating.py`), `train_multitask`
  (`../train_multitask.py`, the joint direction+magnitude+volatility
  trainer), `train_sequence` (`../train_sequence.py`, the causal-TCN
  sequence encoder — see `inference/README.md`/`moe/README.md`/
  `risk/README.md`) and `train_strategy_selector`
  (`../train_strategy_selector.py`, dormant until real option positions
  trade). Each one's failure is logged as a note and never rejects the
  candidate.
- `worker.py` — `RetrainingWorker`, a continuous loop through the same
  stages (now including `train_topology`, `train_gating`, `train_multitask`
  and `train_sequence`), toggled by `phase_v2.retraining.enabled`.

## Running it

```powershell
docker compose up -d postgres retraining-worker      # continuous
docker compose run --rm retraining-worker python -m retraining.worker --once   # one cycle
python -m retraining.orchestrator plan               # single stage, manual
python -m retraining.orchestrator status
```

See `development/infrastructure.md`'s "Controlled Retraining Betreiben
(V2-17)" section for the full command reference, including every
orchestrator subcommand and the Postgres inspection queries.

## Auto-rollback: a separate concern from the plan→train→promote loop

`RetrainingWorker.check_auto_rollback()` runs on the same poll cadence as
`run_once()` but asks a different question — is the model *currently
active* in production degrading, not whether a new candidate is ready. It
feeds `auto_rollback.select_rollback_target()` live signals
(`_live_degradation_signals()`: `main.py`'s kill-switch state read from
`visualization/state.json`, plus recent `sharpe_degradation_trigger`/
`rank_ic_decay_trigger` rows from `performance_triggers`), reports a continuous
`rollback_hardening.compute_degradation_score()` alongside the binary
decision (`aq retrain auto-rollback --status` / `--dry-run` show it; it is
informational, never the trigger), and, only
when
the selector agrees, calls the existing `orchestrator.rollback()` and
pushes a notification through the same trigger-table → Telegram pathway
every other alert already uses. `select_rollback_target_dry_run()` gives
the full verdict + degradation score without executing anything. Off by
default
(`phase_v2.retraining.auto_rollback.enabled: false`) — an automatic
weight swap is the most consequential single action this system can
take. `aq retrain auto-rollback --status` and the `retraining_status.json`
`auto_rollback` section are both read-only diagnostics backed by the same
`auto_rollback_status()` function; neither one ever triggers a rollback
itself.

## Walk-forward retraining is a separate, scheduled mechanism (Phase 4)

`python train.py --walk-forward --step-days N --mode {rolling,expanding}`
(see `train.py::generate_walk_forward_windows()`/`_run_walk_forward()`) is
**not** part of this package's reactive, trigger-driven loop above —
deliberately kept separate, since it's a proactive, calendar-scheduled
mechanism ("retrain periodically regardless of triggers"), not a response
to a detected quality problem. Folding it into `RetrainingWorker`'s
cooldown/daily-limit logic (designed around reactive trigger bursts, not a
predictable schedule) would conflate two different concepts. Config lives
at `phase_v2.retraining.walk_forward` (`enabled: false` by default) —
intentionally namespaced under `retraining` since it's still a form of
retraining, just not one this package's worker orchestrates.

**V5.6.0:** each finished window writes `window_result.json` and `--resume-run-id <run-id>` reloads
finished windows instead of retraining them (the training Codespace's VM reboots about hourly; a
torn or incomplete file means the window reruns). The ranking promotion gate
(`phase_v2.retraining.validation_gate.ranking`) takes `heads: [...]` and passes when any listed head
clears it — the shipped list is the book's own heads (`rank_5d`, `rank_20d`), not the demoted
`residual_rank_20d` that rejected every candidate.
