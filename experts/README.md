# experts

Owns the specialized V2 expert models and the datasets they train from:

- bullish expert
- bearish expert
- sideways expert
- volatility expert

Each expert is trainable from local Lean `data/` folder features and
evaluated separately before being routed by the gating network (`moe/`).

## What lives here

`experts/expert_datasets.py` is the only module: it annotates dataset rows
with quantitative regime labels and builds the four expert slices
(bullish, bearish, sideways, volatility) from training-eligible rows.

- Expert CSVs are written under `ml/expert_datasets/`;
  `ml/expert_dataset_manifest.json` records row counts, split counts,
  tickers, target balance and routing filters. Generated expert artifacts
  stay local and are gitignored.
- `train.py --experts-only` trains the four experts without retraining the
  baseline model; a normal `train.py` run trains the baseline and then
  refreshes the experts. Each expert writes `model_weights.json`,
  `metrics.json` and `model.pt` under `ml/expert_models/<expert>/`, and
  `ml/expert_training_metrics.json` summarizes trained and skipped experts.
  Weights are JSON-exported so the gating network (and Lean) can load them
  without a PyTorch runtime.
- Expert defaults are intentionally smaller and more regularized than the
  baseline model, and each expert passes through a post-training quality
  gate: status is `stable`, `watchlist` or `disabled_for_gating`, and
  `gating_eligible_experts` lists the experts the gating network may use.
  Weak or overfit experts remain available for diagnosis but are not
  trusted by default. (The gate itself is implemented in `train.py` and
  consumed by `moe/gating.py` — this package owns the datasets, not the
  gate.)
