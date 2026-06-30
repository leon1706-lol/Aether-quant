# analyzer

Owns the V2-10 Central Market Analyzer: the final per-asset categorization
layer that sits after experts, regime detection, topology (V2-11) and the
risk engine, and before action categorization / Lean order placement.

- `analyzer/market_analyzer.py` combines `moe.gating` output, `regime`
  output, `topology` output and active risk-lock state into one
  categorical action: `observe`, `simulate`, `trade`, `reduce_risk` or
  `retrain_candidate`.
- Pure function, deterministic, explainable via a `reasons` list. No
  classes or state, matching the rest of the V2 module family.
- `topology` is supplied by `main.py` every bar as of V2-11 and now
  actually changes outcomes, not just metadata: an `"elevated"`
  volatility-pressure node is forced to `reduce_risk`, and an
  `"isolated"` node (no meaningfully correlated peers) cannot reach
  `trade` and is downgraded to `simulate`. When `topology` is absent or
  empty (e.g. during warmup) neither rule fires and behavior is
  unchanged, recorded via `topology_considered=False`.
- `retrain_candidate` is currently a stateless, instantaneous heuristic
  (zero active experts plus low regime confidence). V2-16 (Performance
  Triggers) will replace or augment this with a trailing-window trigger
  fed by the V2-13/14 Redis/PostgreSQL experience pipeline.
- **Both the `retrain_candidate` heuristic (V2-10) and the topology-elevated
  / topology-isolated rules (V2-11) are deliberately simple, deterministic
  placeholders** — see roadmap item **V2-17.5** in the root `README.md`:
  once the V2-13/14 experience pipeline has persisted enough history and
  V2-16/17's controlled retraining loop exists, these rules should be
  replaced with data-driven/learned versions instead of fixed thresholds.
- `main.py` only calls `_apply_signal` when `action == "trade"`. All five
  actions are written into the per-asset `signal_payload` for
  dashboard/Grafana visibility regardless of whether a real order is
  placed.
