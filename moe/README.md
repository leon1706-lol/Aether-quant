# moe

Owns the V2 Mixture-of-Experts layer:

- gating network
- expert routing
- expert weight blending
- final MoE signal composition

This package will build on the existing `train.py` feature pipeline and `main.py` Lean inference loop.

Current V2-9 behavior:

- `moe/gating.py` scores expert models with quality status, regime alignment and validation/backtest performance
- `stable` and `watchlist` experts can contribute to the final signal
- `disabled_for_gating` experts are ignored by the manager
- `main.py` loads local expert JSON exports from `ml/expert_models/<expert>/model_weights.json`
- runtime state now includes `moe_gating`, expert probabilities and the final MoE probability per asset
- if expert artifacts are missing, the runtime falls back to the baseline model
