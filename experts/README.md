# experts

The datasets behind the four expert models: bullish, bearish, sideways and volatility.

- **`expert_datasets.py`:** labels rows with quantitative regimes and builds each expert's slice from training-eligible rows (`ml/expert_datasets/`, `ml/expert_dataset_manifest.json`).
- **Training:** `aq train --experts-only`, or a full `aq train`. Each writes `ml/expert_models/<expert>/`, and weights are exported to JSON so Lean loads them without PyTorch.
- **Quality gate (in `train.py`, read by `moe/gating.py`):** smaller, more regularized than the baseline; each expert ends `stable`, `watchlist` or `disabled_for_gating`. Weak ones stay available for diagnosis but aren't trusted.
