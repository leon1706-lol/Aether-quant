# topology

Owns 3D market topology:

- asset correlation structure
- volatility and momentum clustering
- topology snapshots for visualization
- JSON exports for the live dashboard

The goal is to make market structure useful for analysis, not only visual.

## Deterministic layer — `market_topology.py::build_market_topology(...)`

Pure, deterministic function: computes pairwise return correlation,
clusters assets via union-find on a correlation threshold, and assigns 3D
coordinates so correlated assets sit near each other and high-volatility
assets separate on the z-axis.

- **x/y placement is a real distance-preserving embedding**:
  `_stress_majorize(...)` runs SMACOF (stress majorization), seeded from a
  deterministic circular layout (never randomness) over the full pairwise
  correlation distance matrix — two assets end up spatially closer only
  when they're actually more correlated. Iteration count is
  `phase_v2.topology.embedding_iterations` (default 100).
- **Genuinely 3D embedding, opt-in** — `phase_v2.topology.embedding_dimensions`
  (default `2`). At `3`, z stops being the volatility encoding and becomes
  a real correlation-distance axis on the same `0..100` scale as x/y
  (`dimensions.depth` reports `100` vs `1` so consumers can tell the modes
  apart; volatility stays visible as node radius). The z seed derives from
  volatility spread across a range comparable to x/y — SMACOF can only
  separate along directions its seed already separates. Positions carried
  between bars with a mismatched tuple width are discarded (mode flip ⇒
  cold start, never a crash). Prototype z offsets are normalized to
  `[-1, 1]` and scaled by `max_offset_z` at apply time (see
  `development/Problems.md` #56) — z's scene scale changes between modes,
  x/y's don't.
- **Warm-started seeding + early convergence exit**:
  `previous_positions` seeds SMACOF from prior-bar positions
  (`phase_v2.topology.warm_start_enabled`, default `true`), and
  `convergence_tolerance` (default `0.01`) exits before the full iteration
  budget once movement drops below it. This changes bar-by-bar coordinates
  (old backtests won't reproduce bit-for-bit); `warm_start_enabled: false`
  reproduces the pre-warm-start behavior exactly.
- **Correlation-stability embedding cache** (off by default):
  `previous_correlations`/`correlation_stability_tolerance` — when every
  pairwise correlation moved by no more than the tolerance since the prior
  bar (same eligible universe), SMACOF is skipped entirely and prior
  converged positions reused (`reasons` gains
  `"topology_embedding_reused_stable_correlations"`). SMACOF is the single
  largest per-bar cost in the system, so skipping beats shrinking.
  `phase_v2.topology.cache_enabled` (default `false`) +
  `correlation_stability_tolerance` (default `0.02`). Only coordinates are
  reused — every other per-node field is recomputed fresh each bar.
  Validate with `aq profile --topology-cached`.
- **Percentile-tolerance mode** —
  `correlation_stability_tolerance_percentile` (default `null` =
  fixed-tolerance behavior) makes the effective tolerance each bar that
  percentile of a rolling window of recent prior bars' own max-pairwise
  correlation changes (never including the current bar), making the skip
  rate a guaranteed function of the percentile instead of a guessed
  constant. Recommended over the fixed value once caching is enabled.
- The pairwise-correlation loop stays pure Python on purpose (eligible
  symbols don't share a common window length in practice, so a
  vectorized `np.corrcoef` over ragged input isn't a safe drop-in);
  `_stress_majorize` itself is numpy-vectorized with a pure-Python parity
  guard in `tests/test_market_topology.py`.
- `main.py` calls it once per bar (before the per-symbol loop), writes
  `visualization/topology_state.json` and `state["topology"]`. Per-asset
  context (`cluster_id`, `correlation_strength`, `market_distance`,
  `topology_risk`) feeds the analyzer and **does** change outcomes: an
  `"elevated"` node is forced to `reduce_risk`, an `"isolated"` node cannot
  reach `trade` (see `analyzer/README.md`).
- Degrades to `state: "insufficient_data"` when fewer than two assets have
  enough return history — never raises.

## Learned overlay — `learned_topology.py::apply_learned_topology(...)`

A pure-Python (no numpy/sklearn at runtime — its own cost is negligible at
this universe size) probabilistic overlay on top of the deterministic
output, never in place of it. Per node it adds `cluster_probs`,
`topology_confidence`, `topology_uncertainty`, `stress_score`,
`neighbor_shift_score`, `topology_disagreement`, `learned_neighbors`,
`cluster_dominant_regime_label`, and bounded x/y/z offsets.
`topology_source` (`deterministic`/`learned`/`hybrid`/`fallback`) reports
whether a trained model was actually used.

- The model (`ml/topology_model.json` + `ml/topology_feature_schema.json`)
  is trained offline by `train_topology.py` from historical
  `experience_events`, versioned through the same `ml/versions/<id>/`
  candidate pipeline — see `development/architecture.md`'s "Non-Deterministic
  Topology & Retrain-Trigger Contract" for the design.
- `main.py` loads the model gracefully (missing file ⇒ `None`) and never
  lets these fields influence the analyzer's decisions — only
  `topology_risk`/`state` do. The safety rule: probabilistic scoring, not
  randomized trading. `topology_confidence`/`topology_disagreement` DO
  reach a real trade — through position sizing
  (`risk/position_sizing.py::topology_sizing_multiplier()`, a shrink-only
  multiplier applied after the analyzer has decided to trade).
- **Currently dormant**: no topology model has ever been trained
  (`ml/topology_model.json` does not exist). Training the first one needs
  the full stack (Postgres + audit worker) up long enough to accumulate
  `phase_v2.topology_learning.training.min_training_events` (default 500)
  realized-outcome events, then `aq train --topology-only`.

## Genuine model input feature

`correlation_strength` and `topology_risk` are genuine model *inputs* too,
not just downstream consumers (see `regime/README.md`/`liquidity/README.md`
for the other two):

- `train.py::build_topology_features_by_date()` computes, for each unique
  historical date across the universe, every asset's trailing 24-return
  window and calls this module's own `build_market_topology()` — the exact
  runtime function, not a reimplementation.
- **`embedding_iterations=1` at dataset-build time, deliberately** —
  `correlation_strength`/`topology_risk` don't depend on the SMACOF
  embedding at all (only visualization coordinates do), so the expensive
  embedding step is skipped offline.
- Adds `topology_correlation_strength` (scaled continuous) plus 3 one-hot
  columns `topology_risk_normal/elevated/isolated` as model inputs. Thin
  dates default to the same "isolated, zero correlation" signal the
  runtime fallback produces — never NaN.
