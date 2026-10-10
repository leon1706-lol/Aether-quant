# analyzer

Owns the Central Market Analyzer: the final per-asset categorization
layer that sits after experts, regime detection, topology and the
risk engine, and before order placement.

- `analyzer/market_analyzer.py` combines `moe.gating` output, `regime`
  output, `topology` output and active risk-lock state into one
  categorical action: `observe`, `simulate`, `trade`, `reduce_risk` or
  `retrain_candidate`.
- Pure function, deterministic, explainable via a `reasons` list. No
  classes or state, matching the rest of the pure-module family.
- `main.py` only calls `_apply_signal` when `action == "trade"`. All five
  actions are written into the per-asset `signal_payload` for
  dashboard visibility regardless of whether a real order is
  placed.

## Decision tiers (in priority order)

1. **Hard safety overrides (priorities 0–6)** — exit-preservation,
   trade-lock, `risk_off` regime, elevated/isolated topology, liquidity
   block/thin, confidence threshold. Simple categorical gates, deliberately
   never aggregated: an `"elevated"` volatility-pressure node forces
   `reduce_risk`, an `"isolated"` node (no meaningfully correlated peers)
   cannot reach `trade` and is downgraded to `simulate`. Absent/empty
   topology (warmup) fires neither rule (`topology_considered=False`).
   **V5.6.0:** `topology_veto_applies_to_book_members` (config `phase_v2.topology.elevated_veto_applies_to_book_members`, default `true` = unchanged) lets a book-selected symbol skip the elevated-volatility override — the model already ranked it with that volatility as an input. The offline as-live simulator models the default as an entry veto (`entry_veto_column`).
   Every directional signal — `buy`, `sell` and the book's `short` —
   passes through the identical tiers, so a book-selected short never
   bypasses a safety check (see `portfolio/README.md` for why book
   construction lives in its own package).
2. **Net-edge cost gate (priority 6.5)** — when `execution/cost_model.py`'s
   expected-net-edge decision says an entry's expected edge doesn't clear
   its expected round-trip cost, the decision downgrades to `simulate`
   instead of `trade` — never blocks an **exit**. A disabled or
   uncalibrated cost model (`net_edge=None`) is a no-op, the same fail-open
   contract as every optional overlay here. See `execution/README.md`.
3. **Trade gate (priority 7) + simulate-vs-observe split (priority 8)** —
   by default gated on raw `confidence`. When
   `phase_v2.market_analyzer.use_composite_signal_score` is explicitly
   `true`, `compute_signal_quality_score()` — a bounded `[0,1]` weighted
   blend of model confidence (0.45), regime confidence (0.20), topology
   peer-support (0.20) and liquidity friction (0.15) — replaces raw
   confidence in exactly these two tiers. The composite score and its
   per-component breakdown are **always** computed and populated on every
   decision regardless of the flag (dashboard-visible via
   `state.json`); default `false` is byte-identical to plain-confidence
   behavior.

## Deliberately deterministic

- The learned topology overlay (`topology/learned_topology.py`'s
  confidence/uncertainty scoring) is consumed by the retrain-trigger and
  position-sizing layers only (`risk/position_sizing.py::
  topology_sizing_multiplier()` — a shrink-only multiplier that changes
  how large an already-approved trade is, never whether one happens).
  This module reads only the deterministic `topology_risk`/`state`, keeping
  the categorization fully deterministic.
- `retrain_candidate` here is a stateless, instantaneous fallback heuristic
  (zero active experts plus low regime confidence) — the real
  trailing-window retrain signal lives in `performance/triggers.py` and
  `retraining/`, fed by the Redis/PostgreSQL experience pipeline.
- `predicted_return_magnitude`/`predicted_volatility` fields are threaded
  through as informational payload only (they influence
  `risk/position_sizing.py` when
  `phase_v2.dynamic_risk.use_predicted_volatility` is enabled, never this
  module's categorization). When the sequence encoder blends into gating
  (`phase_v2.gating_network.sequence_weight`), these fields transitively
  reflect it via `gating_payload["final_magnitude"/"final_volatility"]`.
  Always `None` when no multitask model is loaded.
