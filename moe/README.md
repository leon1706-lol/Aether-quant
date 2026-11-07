# moe

The Mixture-of-Experts layer. `gating.py::build_gating_decision()` blends the four experts and the baseline into one probability. It feeds the legacy signal's `final_probability_up`; the book ranks on the rank heads, and the shipped sleeve skips this path.

**The default blend**

- Scores each expert on quality status, regime alignment and validation and backtest performance.
- `stable` and `watchlist` experts contribute; `disabled_for_gating` ones don't. `phase_v2.gating_network.disabled_experts` excludes more, and the rest renormalize.
- Missing artifacts fall back to the baseline.
- Magnitude and volatility blend the same way, over experts that have a head (#121). `_weighted_blend()` returns `None` when no expert has a value, so "no data" never reads as zero.

**Optional layers, each falling back**

- **Learned gating (`phase_v2.gating_network.learned_model_enabled`):** scores a 26-feature vector with a trained model through `run_exported_model()`, and `decision_source` becomes `learned_gating`. Any failure silently uses the default blend. It's direction-only. Train with `aq train --gating-only`, on the validation split replayed through the exported models, to avoid stacking circularity.
- **Sequence blend (`phase_v2.gating_network.sequence_weight`, default 0):** applied last, `w * sequence + (1 - w) * existing`, each field independently. `GatingDecision.sequence_blended` records whether it contributed.

Gating changes which probability wins, not how large the trade is: see [`risk/README.md`](../risk/README.md).
