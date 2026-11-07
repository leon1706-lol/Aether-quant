# retraining

Controlled retraining: reads `retrain_candidate` triggers from Postgres, trains a candidate in isolation, validates and backtests it against the active model, commits it to Aether-Vault, and only then may promote it, with rollback always available.

**No uncontrolled live learning.** Every stage is a Postgres-audited row. `phase_v2.retraining.worker.auto_promote` allows promotion without a human, but `auto_promote_blocked_in_live_mode` forces it to be manual once the mode is `live`.

## Files

| File | What |
|---|---|
| `planning.py` | `evaluate_retraining_plan()`: the highest-priority trigger, then minimum observations, cooldown and daily cap |
| `postgres_registry.py` | `model_versions` and `retraining_events`; a partial unique index allows one `active` version |
| `validation_gate.py` | Candidate against active on drawdown, Sharpe, loss stability, overfitting gap and ranking. Missing or non-finite metrics fail closed (#122) |
| `backtest_gate.py`, `lean_backtest.py` | Active, candidate and buy-and-hold, plus an optional real Lean run |
| `vault_commands.py`, `vault_client.py` | Runs `av` as an external CLI; a failure is a `failed` event, never a crash |
| `artifacts.py` | Completeness checks, hashes, copy and restore. Topology, gating, multitask and sequence files are optional |
| `auto_rollback.py`, `rollback_hardening.py` | `select_rollback_target()`, a dry run, and a degradation score |
| `status_export.py` | Writes `visualization/grafana/retraining_status.json` |
| `orchestrator.py` | Each stage as a function and a subcommand (`aq retrain <stage>`) |
| `worker.py` | `RetrainingWorker`, toggled by `phase_v2.retraining.enabled` |

Stages between `train` and `validate` (`train_topology`, `train_gating`, `train_multitask`, `train_sequence`, `train_strategy_selector`) can fail independently, and a failure never rejects the candidate.

## Running it

```powershell
docker compose up -d postgres retraining-worker                                # continuous
docker compose run --rm retraining-worker python -m retraining.worker --once   # one cycle
aq retrain plan
aq retrain status
```

## Auto-rollback

Off by default (`phase_v2.retraining.auto_rollback.enabled`), because an automatic weight swap is the most consequential action this system can take.

- **Asks:** is the active model degrading? It reads the kill-switch state and recent Sharpe and rank-IC triggers.
- **Acts:** only when `select_rollback_target()` agrees, then alerts through the trigger table.
- **Inspect:** `aq retrain auto-rollback --status` never acts.

## Related mechanisms

- **Walk-forward (`aq train --walk-forward`):** calendar-scheduled, not trigger-driven, so it stays outside this worker (`phase_v2.retraining.walk_forward`). Each window writes `window_result.json`, and `--resume-run-id` skips finished ones. The promotion gate (`phase_v2.retraining.validation_gate.ranking`) passes when any listed head clears it.
- **Generations:** `promote` fills one slot. With `enabled: true` in `ml/generations/policy.json` it refuses, and `aq cycle promote` takes over. `aq cycle retrain` is the research cycle's own retrain.
- **The vault:** the client reads `av --output json` and stores the full hash; `vault_preflight` checks it before a commit. `scripts/vault_record.py` records research rounds.
