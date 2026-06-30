# analyzer

Owns the V2-10 Central Market Analyzer: the final per-asset categorization
layer that sits after experts, regime detection, topology (V2-11, optional
for now) and the risk engine, and before action categorization /
Lean order placement.

- `analyzer/market_analyzer.py` combines `moe.gating` output, `regime`
  output, an optional topology payload and active risk-lock state into
  one categorical action: `observe`, `simulate`, `trade`, `reduce_risk`
  or `retrain_candidate`.
- Pure function, deterministic, explainable via a `reasons` list. No
  classes or state, matching the rest of the V2 module family.
- `topology` is optional and currently always absent until V2-11 ships;
  the analyzer degrades gracefully and records `topology_considered=False`.
- `retrain_candidate` is currently a stateless, instantaneous heuristic
  (zero active experts plus low regime confidence). V2-16 (Performance
  Triggers) will replace or augment this with a trailing-window trigger
  fed by the V2-13/14 Redis/PostgreSQL experience pipeline.
- This phase does not change real order-placement behavior: `main.py`
  only calls `_apply_signal` when `action == "trade"`. All five actions
  are written into the per-asset `signal_payload` for dashboard/Grafana
  visibility regardless of whether a real order is placed.
