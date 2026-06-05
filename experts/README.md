# experts

Owns specialized V2 expert models:

- bullish expert
- bearish expert
- sideways expert
- volatility expert

Each expert should be trainable from local Lean `data/` folder features and evaluated separately before being routed by the gating network.

Current V2-7 behavior:

- `experts/expert_datasets.py` annotates dataset rows with quantitative regime labels
- bullish, bearish, sideways and volatility expert slices are built from training-eligible rows
- the training pipeline writes local expert CSVs under `ml/expert_datasets/`
- `ml/expert_dataset_manifest.json` records row counts, split counts, tickers, target balance and routing filters
- generated expert artifacts stay local and are ignored by Git

Current V2-8 behavior:

- `train.py --experts-only` trains bullish, bearish, sideways and volatility experts without retraining the baseline model
- normal `train.py` runs train the baseline model and then refresh expert models
- each expert writes local `model_weights.json`, `metrics.json` and `model.pt` files under `ml/expert_models/<expert>/`
- `ml/expert_training_metrics.json` summarizes trained and skipped experts
- expert weights are JSON-exported so the later gating network can load them without a PyTorch runtime inside Lean

Current V2-8.5 behavior:

- expert defaults are intentionally smaller and more regularized than the baseline model
- each expert receives a quality gate after training
- quality status is one of `stable`, `watchlist` or `disabled_for_gating`
- `gating_eligible_experts` lists experts the next gating network may use first
- weak or overfit experts remain available for diagnosis but are not trusted by default
