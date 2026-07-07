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
  - **Follow-up:** the learned topology overlay's confidence/disagreement
    scores now *do* reach a real trade — but through position sizing
    (`risk/position_sizing.py::topology_sizing_multiplier()`), not this
    module. That integration point was chosen specifically because sizing
    is already a continuous, shrink-only multiplier applied after this
    analyzer has categorized the action, so it changes only *how large* an
    already-approved trade is, never *whether* one happens — preserving
    exactly the "confidence/uncertainty only, never a randomized decision"
    rule above. This module's own `trade`/`simulate`/`observe`/
    `reduce_risk` categorization remains fully deterministic and
    unaffected. See `risk/README.md` for details.
- `main.py` only calls `_apply_signal` when `action == "trade"`. All five
  actions are written into the per-asset `signal_payload` for
  dashboard/Grafana visibility regardless of whether a real order is
  placed.
- **Real composite scoring (additive, config-gated).** Until now, every
  priority tier here checked exactly one raw field in isolation against a
  fixed threshold (confidence alone, `topology_risk` alone,
  `liquidity_action` alone) — pure if/elif routing, no aggregation. New
  `compute_signal_quality_score(confidence, regime_confidence, topology,
  liquidity)` computes a real bounded `[0,1]` composite — a small,
  hand-tuned weighted blend of raw model confidence (0.45), regime
  confidence (0.20), topology peer-support (0.20, penalized when
  `topology_risk` is `isolated`/`elevated`), and liquidity friction (0.15,
  penalized by `participation_rate`) — mirroring `moe/gating.py`'s
  `_quality_multiplier`/`_performance_score` style: real math over
  already-available fields, not a trained model. `MarketAnalysisDecision`
  gains `signal_quality_score`/`signal_quality_breakdown` fields that are
  **always** computed and populated on every decision, regardless of any
  flag — visible in `visualization/state.json` immediately for dashboard
  use. It only ever changes routing when
  `phase_v2.market_analyzer.use_composite_signal_score` is explicitly
  `true` (default `false`) — in that case it replaces raw `confidence`
  with the composite score in the `trade` gate (priority 7) and the
  `simulate`-vs-`observe` split (priority 8) only. The hard safety-override
  tiers (trade-lock, `risk_off` regime, elevated topology, liquidity
  blocked — priorities 1-6) are **never** affected by this flag, regardless
  of its value — they stay simple categorical gates on purpose, same
  reasoning as the topology-elevated/isolated rules above. Default `false`
  means output is byte-identical to pre-this-change behavior everywhere
  the flag isn't explicitly turned on.
