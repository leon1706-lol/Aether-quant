# ml

Models, datasets and evidence. Gitignored, except for what must survive a clone. Regenerate with `aq train`.

**What Lean loads now:** `target_weights.csv`, the shipped weights, pinned by `phase_v2.target_weights.weights_sha256`; and, only when `phase_v2.target_weights.source` is `"model_book"`, the models themselves.

**Model artifacts** (trained and installed; they drive the model book's 30% share of the shipped book, scored offline by `scripts/model_book_decide.py`)

| Files | What |
|---|---|
| `model_weights.json`, `feature_schema.json`, `scaler_stats.json` | The baseline model and what `main.py` requires at load |
| `model.pt`, `scaler.pkl` | Training only; Lean never reads them |
| `multitask_*`, `sequence_*` | Rank, direction, magnitude and volatility heads, with their schemas and metrics |
| `expert_models/<name>/`, `expert_*` | The four experts |
| `gating_*`, `topology_*`, `rl_sizing_*` | Optional overlays, off until trained or enabled |
| `training_metrics.json`, `dataset_manifest.json`, `dataset_inventory.json` | Metrics and dataset summaries |
| `datasets/` | The feature CSVs |
| `artifact_pins.json` | Tracked. The sha256 of every installed model file, written by an install or a restore only (V6.6.9, #382). `scripts/check_artifact_pins.py` checks it |

**Other folders**

- **`versions/<id>/`:** a retraining candidate, never touching active files until `aq retrain promote`.
- **`versions/walk-forward-<run>/`:** one directory per window, plus `walk_forward_summary.json`.
- **`evaluation/`:** reports from `aq evaluate` and each phase's rules and scores.
- **`generations/`:** tracked. Which generations exist, the glide policy, the lifecycle log and the once-only holdout ledger. Nothing in Lean reads it.
- **`forward/`:** the frozen rules the forward ledger records.
- **`cycle/`:** resumable retraining state.

Remove old candidates with `aq clean ml`.
