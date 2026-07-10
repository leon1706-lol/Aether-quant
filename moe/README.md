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

## Real learned gating weights (optional, additive, always-falls-back)

The hardcoded quality/performance/regime-alignment blend above is no
longer the only option — `moe/gating.py` can now optionally score a
trained model instead, without changing anything about the fallback path:

- `build_gating_model_features(regime, baseline_probability_up, weights)`
  builds a fixed 26-dim feature vector (`GATING_MODEL_FEATURE_KEYS`): each
  expert's probability/quality-multiplier/performance-score/regime-alignment
  ×4, the baseline probability, and one-hot trend/volatility/risk regime.
  Every value is already a bounded `[0,1]` probability or a one-hot flag,
  so — unlike `topology/learned_topology.py`'s z-scored prototypes — no
  scaler/feature_stats is needed.
- `build_gating_decision(..., gating_model=None, gating_feature_schema=None)`
  gains two optional params. When both are present, the hardcoded blend is
  still computed first (unchanged), then the learned model scores the
  feature vector via the existing `inference/exported_model.py::run_exported_model()`
  interpreter — no new inference code. On success, `decision_source`
  becomes `"learned_gating"` (joining `"baseline_fallback"`,
  `"experts_only"`, `"baseline_and_experts"`). Any exception (missing key,
  unsupported layer type, malformed export) is caught and silently falls
  back to the hardcoded blend — a degraded/missing learned model must
  never crash a bar or block a decision, only forfeit the improvement it
  would have added, mirroring `topology/learned_topology.py`'s per-node
  fallback isolation.
- `main.py::_load_gating_model()` loads `ml/gating_model.json` +
  `ml/gating_feature_schema.json` (optional artifact pair, same
  graceful-degrade contract as `_load_learned_topology_model()`), gated by
  `phase_v2.gating_network.learned_model_enabled` (default `true`).
- **Training:** `train_gating.py` (repo root, sibling of
  `train_topology.py`) trains the blend on the dataset's `validation`
  split replayed through the exported baseline+expert models (avoids
  stacking circularity — `train` already fit those models), evaluated once
  on the `backtest` split. Run it directly, via `aq train --gating-only`
  (installs straight into active `ml/`), or let the retraining pipeline's
  best-effort `train_gating()` stage produce a versioned candidate
  automatically.
- **Sizing, not routing:** a learned gating model changes which
  probability wins, not how large the resulting trade is — that's a
  separate, also-optional layer; see `risk/README.md`'s learned-topology
  sizing section.

## Multi-task model (direction + magnitude + volatility) now routes through gating

**Follow-up, same session as the note below's original writing:** per-expert
multitask heads now exist (`train.py::_train_expert_multitask()`, writing
`ml/expert_models/<name>/multitask_model.json` as a sibling to each
expert's direction-only `model_weights.json`), so `GatingDecision` gains
`final_magnitude`/`final_volatility` after all — the scope decision this
section originally documented was resolved, not abandoned.

- `build_gating_decision(..., expert_magnitudes=None, expert_volatilities=None,
  baseline_magnitude=None, baseline_volatility=None)` gains four optional
  params (parallel to `expert_probabilities`/`baseline_probability_up`).
  New `_weighted_blend()` generalizes the exact weighted-average pattern
  `expert_probability` already uses (`weight.weight × value`, summed over
  experts with a non-`None` value), with one deliberate difference: it
  returns `None` (not `0.0`) when no expert has a value at all — a
  spurious `0.0` would misrepresent "no data" as "predicted zero
  magnitude/volatility".
- Same baseline-anchor blend shape `final_probability_up` already uses:
  `baseline_weight × baseline_value + (1 − baseline_weight) × expert_average`
  when both sides have a value, falling back to whichever single side
  does when the other is `None`. The `baseline_fallback` branch (no
  experts eligible at all) uses `baseline_magnitude`/`baseline_volatility`
  directly, matching how it already uses `baseline_probability_up`
  directly there.
- The learned-gating override (`gating_model`/`gating_feature_schema`,
  above) stays **direction-only** — it predicts a single probability, not
  magnitude/volatility, so `final_magnitude`/`final_volatility` are
  unaffected by `decision_source` switching to `"learned_gating"`.
- `main.py::_run_expert_multitask_models()` loads and runs each expert's
  optional multitask export (same per-expert graceful-degradation
  contract as `_run_expert_models()` — a missing/failed expert
  contributes `None` to both dicts, never blocks the bar).
  `predicted_return_magnitude`/`predicted_volatility` (threaded into
  `signal_payload`, the market analyzer and position sizing — see
  `analyzer/README.md`/`risk/README.md`) now come from
  `gating_payload["final_magnitude"/"final_volatility"]` — the full blend
  — instead of directly from the single baseline-scale multitask model,
  the same treatment `probability_up` itself already got from gating.

See `development/Changelog.md`'s "Phase 1 remainder + Phase 2" entry for
the full writeup.
