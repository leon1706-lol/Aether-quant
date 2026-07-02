# retraining

Owns Phase V2-17, Controlled Retraining: closes the loop `performance/`
(V2-16) deliberately left open. Reads `retrain_candidate = true` rows out
of the durable `performance_triggers` table, trains a candidate model in
isolation, validates and backtests it against the currently active model,
commits it to Aether-Vault, and only then may promote it to active — with
rollback always available. See `development/v2_architecture.md`'s
"Controlled Retraining Contract (V2-17)" section for the full design
writeup; this file is the short version.

**No uncontrolled live learning** is the hard constraint: every stage is a
Postgres-audited row (`retraining_events`/`model_versions`), and full
autonomy (the worker auto-promoting without a human looking) is an opt-in
config flag (`phase_v2.retraining.worker.auto_promote`), `false` by
default.

Files (pure/IO/worker split, matching `performance/`'s V2-16 convention):

- `planning.py` (pure) — `evaluate_retraining_plan()`: picks the newest
  eligible trigger, then checks minimum observations, cooldown, and a daily
  retraining cap, in that order.
- `postgres_registry.py` (IO) — embedded DDL for `model_versions` and
  `retraining_events`; a partial unique index enforces exactly one `active`
  model version at the DB level.
- `validation_gate.py` (pure) — candidate-vs-**active** comparison
  (drawdown, Sharpe, validation-loss stability, overfitting gap, trade
  count/exposure), mirroring `train.py`'s `assess_expert_quality()` shape.
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
- `status_export.py` (IO) — the sole writer of
  `visualization/grafana/retraining_status.json`.
- `orchestrator.py` — `plan`/`train`/`validate`/`backtest`/`commit`/
  `promote`/`rollback`/`status`, each usable as a library function or a CLI
  subcommand (`python -m retraining.orchestrator <stage> ...`) for
  manual/staged runs independent of the worker.
- `worker.py` — `RetrainingWorker`, a continuous loop through the same
  stages, toggled by `phase_v2.retraining.enabled`.

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
