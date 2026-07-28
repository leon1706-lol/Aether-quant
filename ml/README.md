# ml

Model and dataset artifacts written by `train.py`. Gitignored (except
tracked schema/manifest JSON files where applicable) — regenerated locally
by running the training pipeline.

**Active model** (the one `main.py`'s Lean algorithm loads at runtime):

- `model_weights.json` — Lean-readable export: architecture, JSON state
  dict, training/backtest metrics. `main.py`'s `_validate_runtime_artifacts()`
  requires this file to exist.
- `feature_schema.json`, `scaler_stats.json` — also strictly required by
  `main.py`; `scaler_stats.json`'s mean/scale arrays are what Lean actually
  uses for inference (not `scaler.pkl`).
- `model.pt` — binary PyTorch checkpoint (training/debugging only, not read
  by Lean).
- `scaler.pkl` — joblib-pickled `StandardScaler` (training-only; not read
  by Lean).
- `training_metrics.json`, `dataset_manifest.json`, `dataset_inventory.json`
  — training/validation/backtest metrics, dataset build summary, and the
  Phase-1 Lean-data inventory respectively.
- `datasets/` — the built feature dataset CSVs (full/train/validation/backtest splits).
- `expert_models/<name>/`, `expert_training_metrics.json`,
  `expert_dataset_manifest.json` — the four MoE expert models (bullish,
  bearish, sideways, volatility) and their datasets.
- `multitask_model.json`, `multitask_feature_schema.json`,
  `multitask_training_metrics.json` — the joint direction+magnitude+
  volatility+rank model (`train_multitask.py`/`aq train --multitask-only`),
  including the `*_ranking_quality` promotion-gate verdicts (per-head,
  per-era) surfaced on the webui's Neural Network page.
- `sequence_model.json`, `sequence_feature_schema.json`,
  `sequence_training_metrics.json` — the Phase 2 causal-TCN sequence
  encoder (`train_sequence.py`/`aq train --sequence-only`), informational
  by default (`phase_v2.gating_network.sequence_weight`) until blended into
  the live decision via `moe/gating.py`.
- `gating_model.json`, `gating_feature_schema.json`,
  `gating_training_metrics.json` — the learned MoE gating blend
  (`train_gating.py`/`aq train --gating-only`, `moe/README.md`), optional
  and off by default until trained.
- `rl_sizing_model.json`, `rl_sizing_feature_schema.json`,
  `rl_sizing_training_metrics.json` (Phase 4.12, `development/Problems.md`
  #71) — the offline contextual-bandit sizing overlay
  (`train_rl_sizing.py`/`aq train --rl-sizing-only`, `risk/README.md`).
  Off by default (`phase_v2.dynamic_risk.rl_sizing_enabled`); this
  project's first real training run of it produced an honest negative
  result (backtest expected reward below the constant-baseline), so it
  ships disabled per its own pre-committed abandon criterion.

**Candidate models (V2-17)** — `versions/<model_version_id>/`: the exact
same artifact set as above (`model_weights.json`, `model.pt`,
`training_metrics.json`, `strategy_report.json`, `equity_curves.csv`,
`scaler.pkl`, `scaler_stats.json`, `feature_schema.json`,
`dataset_manifest.json`), produced by `python train.py --candidate
--version-id <uuid>` (see `train.py`'s `candidate_output_paths()`) and
never touching any of the active files above until
`retraining/orchestrator.py`'s `promote()` explicitly copies a validated,
Vault-committed candidate over them.
