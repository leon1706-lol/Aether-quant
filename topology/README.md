# topology

Owns 3D market topology:

- asset correlation structure
- volatility and momentum clustering
- topology snapshots for visualization
- JSON exports for the live dashboard

The goal is to make market structure useful for analysis, not only visual.

## V2-11 behavior

- `topology/market_topology.py::build_market_topology(...)` is a pure,
  deterministic function (no numpy/sklearn, matching `regime/` and `risk/`):
  it computes pairwise return correlation, clusters assets via union-find
  on a correlation threshold, and assigns 3D coordinates so correlated
  assets sit near each other and high-volatility assets separate on the
  z-axis.
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
  promised replacement layer: a pure-Python (no numpy/sklearn at runtime)
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
