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
- `retrain_candidate` here is still the original stateless, instantaneous
  heuristic (zero active experts plus low regime confidence) — the *real*
  trailing-window retrain signal now lives entirely outside this module,
  in `performance/triggers.py` (V2-16) and `retraining/` (V2-17), fed by
  the V2-13/14 Redis/PostgreSQL experience pipeline. This in-analyzer
  heuristic was never wired to that system and still isn't; it remains a
  separate, lightweight per-bar fallback signal.
- **Topology-elevated / topology-isolated rules (V2-11) are still the
  original deterministic thresholds, and this is a deliberate decision,
  not an oversight.** V2-17.5 added `topology/learned_topology.py`, a
  probabilistic overlay with confidence/uncertainty scoring trained from
  experience history (see `development/v2_architecture.md`'s
  "Non-Deterministic Topology & Retrain-Trigger Contract (V2-17.5)"
  section) — but its output is consumed by the retrain-trigger/retraining
  layer only, never by this module. `analyzer/market_analyzer.py` still
  reads only `topology_risk`/`state`, produced unchanged by the
  deterministic layer, so this file's decision logic is unaffected by
  V2-17.5. Wiring learned confidence into per-bar trading decisions was
  explicitly ruled out of scope for that phase as a materially riskier
  change than what its safety rule ("confidence/uncertainty only, never a
  randomized decision") allows.
- `main.py` only calls `_apply_signal` when `action == "trade"`. All five
  actions are written into the per-asset `signal_payload` for
  dashboard/Grafana visibility regardless of whether a real order is
  placed.
