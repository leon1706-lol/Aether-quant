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

**Candidate models (V2-17)** — `versions/<model_version_id>/`: the exact
same artifact set as above (`model_weights.json`, `model.pt`,
`training_metrics.json`, `strategy_report.json`, `equity_curves.csv`,
`scaler.pkl`, `scaler_stats.json`, `feature_schema.json`,
`dataset_manifest.json`), produced by `python train.py --candidate
--version-id <uuid>` (see `train.py`'s `candidate_output_paths()`) and
never touching any of the active files above until
`retraining/orchestrator.py`'s `promote()` explicitly copies a validated,
Vault-committed candidate over them.
