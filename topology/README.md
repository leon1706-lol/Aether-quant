# topology

3D market structure: correlation, clusters and risk per asset, for analysis as well as display.

## Deterministic layer: `market_topology.py::build_market_topology()`

Pure. Clusters assets by correlation (union-find) and places them so correlated assets sit together. Fewer than two assets with enough history gives `state: "insufficient_data"`, never an error.

- **Placement:** SMACOF stress majorization from a deterministic seed, with warm starts (`phase_v2.topology.warm_start_enabled`) and early exit.
- **3D (`phase_v2.topology.embedding_dimensions`, default 2):** at 3, z becomes a real correlation axis instead of volatility.
- **Embedding cache (`phase_v2.topology.cache_enabled`, off):** when no correlation moved past `correlation_stability_tolerance` (or a percentile of recent moves), SMACOF is skipped. Check with `aq profile --topology-cached`.
- **Speed:** full-length windows use one numpy matrix product, and shorter windows the scalar path, agreeing to 1e-12.
- **Outcomes:** `topology_risk` feeds the analyzer. An `elevated` node becomes `reduce_risk`, and an `isolated` one can't reach `trade`.
- **Per-class cutoff:** `phase_v2.topology.elevated_volatility_threshold` takes a float or `{"default": 0.45, "crypto": 0.87}`, because crypto sits above any single cutoff. Calibrate with `aq evaluate --calibrate-volatility-threshold`.

## Learned overlay: `learned_topology.py::apply_learned_topology()`

Probabilistic scoring on top of the deterministic output, never in place of it: cluster probabilities, confidence, uncertainty, disagreement and bounded offsets. `topology_source` reports whether a model was used.

- **Safety rule:** these fields never reach the analyzer. They resize approved trades only (`risk/position_sizing.py::topology_sizing_multiplier()`, shrink-only).
- **Training:** `aq train --topology-only` from realized outcomes in Postgres; it skips cleanly below `phase_v2.topology_learning.training.min_training_events`.
- **`learned_sizing_inputs()`:** scores a dataset row with the live distances, for offline parity.

## A model input too

`train.py::build_topology_features_by_date()` calls the same function per date, with `embedding_iterations=1` because the features don't need coordinates. It adds `topology_correlation_strength` and one-hot `topology_risk_*` columns. Thin dates read as "isolated, zero correlation", never NaN.
