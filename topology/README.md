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
  layout: `_stress_majorize(...)` runs SMACOF (Scaling by MAjorizing a
  COmplicated Function) — an iterative stress-majorization algorithm,
  seeded from a deterministic circular layout (for reproducibility and fast
  convergence, never randomness) — over the full pairwise correlation
  distance matrix across all eligible symbols, so two assets end up
  spatially closer only when they're actually more correlated, not merely
  because of index ordering or shared cluster membership. Iteration count
  is `phase_v2.topology.embedding_iterations` (default 100). In the
  default 2D mode the z-axis (volatility encoding) is unchanged by this —
  it's a separate, deliberate encoding, not part of the spatial
  embedding. See the V4-W3 section below for the 3D mode, where z
  *becomes* part of the embedding.
- **Genuinely 3D embedding, opt-in** (V4-W3) —
  `phase_v2.topology.embedding_dimensions` (default `2`) selects how many
  axes SMACOF embeds. `_stress_majorize(...)` (renamed from
  `_stress_majorize_2d` when it became dimension-agnostic) infers
  dimensionality from the width of its seed tuples rather than taking a
  flag, so 2-tuples reproduce the original behavior exactly — the parity
  test below is what holds that guarantee.
  - At `3`, z stops being the volatility encoding and becomes a real
    correlation-distance axis on the same `0..100` scale as x/y, and
    `dimensions.depth` reports `100` instead of `1` so every consumer can
    tell the modes apart. Volatility is still visible: the webui already
    encoded it as node radius, which is why z was the redundant copy and
    is the axis that could be reclaimed.
  - The z seed is derived from that same volatility value, spread across
    a range comparable to the x/y seed. This matters: SMACOF can only
    separate points along directions its seed already separates them on,
    so seeding z flat — or on the raw `0.1..0.95` volatility scale, about
    1/100th of the x/y spread — would collapse the third axis and leave
    the layout visually 2D despite claiming three dimensions.
  - Positions carried between bars (warm start, correlation cache) whose
    tuple width doesn't match the active mode are discarded like an
    unseen symbol, so flipping the flag mid-run degrades to a cold start
    instead of crashing.
  - **Prototype z offsets are normalized, not absolute** (development/
    Problems.md #56): unlike x/y, whose offsets are always absolute scene
    units clamped straight to `max_offset_xy`, `train_topology.py` emits z
    normalized to `[-1, 1]` and `learned_topology.py`'s `_score_node()`
    multiplies it by the active `max_offset_z` before the same
    confidence-weighted clamp. This is deliberate, not an inconsistency —
    z is the one axis whose scene scale changes between the 2D (`0..1`
    volatility encoding) and 3D (`0..100` spatial axis) modes, so a raw
    offset tuned for one scale would be meaningless on the other. The
    normalization is provably identity-preserving in 2D
    (`(win_rate − 0.5) × 2.0 × 0.1 ≡ (win_rate − 0.5) × 0.2` for every win
    rate and confidence — the old raw formula), so 2D mode's output is
    unaffected; in 3D mode the same offset now produces real z movement
    instead of a near-zero shift. `main.py`'s existing `max_offset_z`
    override (raising it to the xy cap in 3D mode) is what this
    normalization is designed to actually push against — the two work
    together, not as separate fixes.
  - **The overlay is still entirely dormant** — no topology model has ever
    been trained (`ml/topology_model.json` does not exist anywhere,
    including every `ml/versions/*`), so `apply_learned_topology()` still
    takes its `learned_topology_model_missing` path on every bar and every
    node still reports `topology_source: "fallback"`. Training the first
    model needs the full stack (Postgres + audit worker) up long enough to
    accumulate `phase_v2.topology_learning.training.min_training_events`
    (default 500) realized-outcome events, then `aq train --topology-only`.
    See `development/Problems.md` #56 for the full story.
- **Vectorized with numpy** (latency-optimization pass, post-V2-23) —
  `_stress_majorize` was pure Python, an `O(N² × iterations)` nested
  loop and the dominant per-bar cost in this whole module. Same
  inputs/outputs/iteration count/seeding as the pure-Python version it
  replaced; `tests/test_market_topology.py`'s
  `test_stress_majorize_matches_pure_python_reference` is the parity
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
  default `0.01`) lets `_stress_majorize` exit before the full iteration
  budget once movement drops below it — the actual source of the speedup,
  since a warm start alone saves nothing if every iteration still runs
  regardless. **This changes bar-by-bar topology coordinate values** —
  historical backtests and models trained/validated against the old
  always-fresh-seed behavior won't reproduce bit-for-bit. Setting
  `warm_start_enabled: false` reproduces the exact pre-warm-start behavior
  as a redeploy-free rollback. See `development/v2_architecture.md`'s "3D
  Topology Contract" section and `development/Problems.md` for the full
  writeup.
- **Correlation-stability embedding cache** (`development/Problems.md#36`,
  off by default): `build_market_topology(...)` also accepts
  `previous_correlations`/`correlation_stability_tolerance` — when both are
  given and every pairwise correlation moved by no more than the tolerance
  since the prior bar (and the eligible-symbol universe is unchanged),
  SMACOF is skipped entirely and the prior bar's already-converged,
  already-rescaled positions are reused directly, `reasons` gaining
  `"topology_embedding_reused_stable_correlations"`. This is a much bigger
  win than warm-starting alone: SMACOF measured ~500-600ms/bar at this
  project's real universe size (the single largest per-bar cost in the
  whole system, larger than the entire per-symbol inference total) —
  skipping it outright on a stable bar removes that cost, not just reduces
  its iteration count. `main.py` gates this via
  `phase_v2.topology.cache_enabled` (default `false`) and
  `phase_v2.topology.correlation_stability_tolerance` (default `0.02`),
  storing `_previous_topology_correlations` unconditionally every bar so
  flipping the flag on mid-run has a valid baseline immediately.
  `cache_enabled: false` (or omitting `previous_correlations`/
  `correlation_stability_tolerance` entirely) reproduces the exact
  pre-caching behavior, byte-identical, same rollback contract
  `warm_start_enabled: false` already guarantees above. Only
  x/y coordinates are ever reused — every other per-node field
  (`correlation_strength`, `market_distance`, `volatility_pressure`,
  `topology_risk`, `regime_label`, `top_peers`/`top_peer_returns`,
  `cluster_id`) is still recomputed fresh from the current bar's
  `returns_by_symbol`/`regime_labels_by_symbol` regardless, since none of
  those depend on the SMACOF embedding at all (same reason
  `embedding_iterations=1` is safe at dataset-build time, below).
  Validate with `aq profile --topology-cached`
  (`scripts/profile_subsystems.py`'s slowly-drifting synthetic workload —
  `--topology`'s own workload draws fully independent returns every
  iteration by design and can never show this cache's benefit). **Not yet
  validated against a real Lean backtest** — that happens in a later
  session's health-check pass, not this one.
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
- **Follow-up:** `topology_confidence`/`topology_disagreement` now do
  reach a real trade, just not through the analyzer — see
  `risk/position_sizing.py::topology_sizing_multiplier()`
  (`risk/README.md`). It's a continuous, shrink-only multiplier applied
  after the analyzer has already decided to trade, so the safety rule
  above still holds: the analyzer's action categorization stays fully
  deterministic, only the size of an already-approved trade can shrink.

## Genuine model input feature (Phase 1 remainder)

`correlation_strength` and `topology_risk` are now genuine model *inputs*
too, not just downstream consumers of the model's own prediction — the
highest-effort of the three subsystems made into inputs this pass (see
`regime/README.md`/`liquidity/README.md` for the other two), because it's
the only one needing a genuinely new cross-sectional computation offline.

- `train.py::build_topology_features_by_date()` is new code — no prior
  function computed a cross-asset relationship at dataset-build time
  (only `main.py`'s runtime path did, once per live bar). For each unique
  historical date across the whole universe, it gathers every asset's
  trailing 24-return window ending at that date and calls this module's
  own `build_market_topology()` — the exact same function the runtime
  path uses, not a reimplementation.
- **`embedding_iterations=1` at dataset-build time, deliberately.**
  `correlation_strength`/`topology_risk` (the only two fields the new
  input features consume) are computed in `build_market_topology()`'s
  Pass 1/Pass 3 and do not depend on the SMACOF x/y embedding at all —
  only the visualization coordinates do. Running the expensive iterative
  embedding step for every historical date would have been wasted work
  with zero effect on either output value, so it's skipped for speed.
- Adds `topology_correlation_strength` (scaled continuous) plus 3 one-hot
  columns, `topology_risk_normal/elevated/isolated` (unscaled, same
  treatment as the asset-context one-hots) as new model inputs. Dates
  with fewer than `min_observations` trailing returns for a given asset
  default to the same "isolated, zero correlation" signal
  `_isolated_node()`'s own runtime fallback already produces — never a
  NaN needing a separate dropna pass.
- Topology itself needed **no reordering** in `main.py` — it was already
  computed once per bar, before the per-symbol loop, so it was already
  available before `_build_model_input()` runs (unlike regime, which
  previously ran only *after* the model — see `regime/README.md`).
