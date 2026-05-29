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
