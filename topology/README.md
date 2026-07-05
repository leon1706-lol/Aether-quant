# topology

Owns 3D market topology:

- asset correlation structure
- volatility and momentum clustering
- topology snapshots for visualization
- JSON exports for the live dashboard

The goal is to make market structure useful for analysis, not only visual.

## V2-11 behavior

- `topology/market_topology.py::build_market_topology(...)` is a pure,
  deterministic function: it computes pairwise return correlation, clusters
  assets via union-find on a correlation threshold, and assigns 3D
  coordinates so correlated assets sit near each other and high-volatility
  assets separate on the z-axis. Deterministic given the same inputs, but
  no longer numpy-free — see the vectorization note below.
- **x/y placement is a real distance-preserving embedding**, not a cosmetic
  layout: `_stress_majorize_2d(...)` runs SMACOF (Scaling by MAjorizing a
  COmplicated Function) — an iterative stress-majorization algorithm,
  seeded from a deterministic circular layout (for reproducibility and fast
  convergence, never randomness) — over the full pairwise correlation
  distance matrix across all eligible symbols, so two assets end up
  spatially closer only when they're actually more correlated, not merely
  because of index ordering or shared cluster membership. Iteration count
  is `phase_v2.topology.embedding_iterations` (default 100). The z-axis
  (volatility encoding) is unchanged by this — it's a separate, deliberate
  encoding, not part of the spatial embedding.
- **Vectorized with numpy** (latency-optimization pass, post-V2-23) —
  `_stress_majorize_2d` was pure Python, an `O(N² × iterations)` nested
  loop and the dominant per-bar cost in this whole module. Same
  inputs/outputs/iteration count/seeding as the pure-Python version it
  replaced; `tests/test_market_topology.py`'s
  `test_stress_majorize_2d_matches_pure_python_reference` is the parity
  guard. The pairwise-correlation loop above stays pure Python on
  purpose — eligible symbols don't share a common window length in
  practice (staggered asset onboarding, thin markets like
  ETHUSD/LTCUSD), so a single vectorized `np.corrcoef` call over a ragged
  input isn't a safe drop-in. `topology/learned_topology.py` (below)
  stays fully numpy-free for the same reason plus its own — see its
  section below.
- **Warm-started seeding + early convergence exit** (same pass,
  **behavior-changing**): `build_market_topology(...)` accepts an optional
  `previous_positions` dict — any eligible symbol present in it seeds
  SMACOF from its prior-bar position instead of the cosmetic angle-based
  layout (correlations evolve slowly bar to bar, so this is usually
  already close to the new stationary point). `main.py` stores every bar's
  node positions and feeds them back in, gated by
  `phase_v2.topology.warm_start_enabled` (default `true`). A new
  `convergence_tolerance` parameter (`phase_v2.topology.convergence_tolerance`,
  default `0.01`) lets `_stress_majorize_2d` exit before the full iteration
  budget once movement drops below it — the actual source of the speedup,
  since a warm start alone saves nothing if every iteration still runs
  regardless. **This changes bar-by-bar topology coordinate values** —
  historical backtests and models trained/validated against the old
  always-fresh-seed behavior won't reproduce bit-for-bit. Setting
  `warm_start_enabled: false` reproduces the exact pre-warm-start behavior
  as a redeploy-free rollback. See `development/v2_architecture.md`'s "3D
  Topology Contract" section and `development/Problems.md` for the full
  writeup.
- `main.py` calls it once per bar (before the per-symbol loop) from
  `self.symbol_windows`, writes the result to `visualization/topology_state.json`
  and `state["topology"]`, and replaces `_build_scene_payload`'s orbit
  placement with the real topology coordinates.
- Per-asset topology context (`cluster_id`, `correlation_strength`,
  `market_distance`, `topology_risk`) is passed into
  `analyzer.build_market_analysis_decision` and **does** change outcomes:
  an `"elevated"` volatility-pressure node is forced to `reduce_risk`, and
  an `"isolated"` node (no correlated peers) cannot reach `trade`. See
  `analyzer/README.md` for the exact priority tiers, and the
  `V2-17.5` roadmap entry in the root `README.md` for the plan to replace
  these deterministic rules with a learned version once the experience
  pipeline (V2-13/14) and controlled retraining (V2-16/17) exist.
- Gracefully degrades to `state: "insufficient_data"` when fewer than two
  assets have enough return history — never raises.

## V2-17.5 behavior

- `topology/learned_topology.py::apply_learned_topology(...)` is the
  promised replacement layer: a pure-Python (no numpy/sklearn at runtime —
  deliberately kept that way even after `market_topology.py`'s
  vectorization above; its own `O(N² × 5)` cost is negligible at this
  project's universe size, and vectorizing it would mean restructuring its
  per-node try/except fallback isolation for no measurable benefit)
  probabilistic overlay on top of `build_market_topology(...)`'s output,
  never in place of it. Per node it adds `cluster_probs`,
  `topology_confidence`, `topology_uncertainty`, `stress_score`,
  `neighbor_shift_score`, `topology_disagreement`, `learned_neighbors`,
  `cluster_dominant_regime_label`, and bounded x/y/z offsets on top of the
  deterministic coordinates. `topology_source` (`deterministic`/`learned`/
  `hybrid`/`fallback`) reports whether a trained model was actually used.
- The model itself (`ml/topology_model.json` + `ml/topology_feature_schema.json`)
  is trained offline by the root-level `train_topology.py` script from
  historical `experience_events`, and versioned through the same
  `ml/versions/<id>/` candidate pipeline V2-17 built — see
  `development/v2_architecture.md`'s "Non-Deterministic Topology &
  Retrain-Trigger Contract (V2-17.5)" section for the full design.
- `main.py` loads the model gracefully (missing file ⇒ `None`, never a
  hard failure) and never lets these new fields influence
  `analyzer/market_analyzer.py`'s decisions — only `topology_risk`/`state`
  do, exactly as before. The safety rule: probabilistic scoring, not
  randomized trading.
