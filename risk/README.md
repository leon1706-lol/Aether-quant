# risk

Owns V2 dynamic risk controls:

- volatility-adjusted position sizing
- leverage caps
- drawdown-aware sizing
- liquidity checks
- market-impact and slippage controls

This package should reuse the existing conservative risk-control behavior and extend it gradually.

Current V2-7 behavior:

- classifies rolling volatility into low, normal and high regimes
- scales target position weight toward a target daily volatility
- reduces exposure in high-volatility regimes
- allows controlled expansion in low-volatility regimes
- emits leverage/sizing telemetry for the future HTML volatility dashboard

## Learned topology → position sizing (optional, shrink-only)

`position_sizing.py::topology_sizing_multiplier(topology_source,
topology_confidence, topology_disagreement, min_topology_multiplier=0.5,
max_topology_multiplier=1.0)` adds a third, optional factor to the
`volatility_multiplier × confidence_multiplier` chain, sourced from the
learned probabilistic topology overlay (V2-17.5,
`topology/learned_topology.py`) that previously only reached the
dashboard and the offline retrain-trigger pipeline, never a trade.

- A strict no-op (`1.0`) unless `topology_source == "learned"` — the
  overlay's own confidence-gated label, absent whenever the model is
  missing/disabled/still warming up. Otherwise:
  `multiplier = min + (max-min) * confidence * (1-disagreement)`, always
  `<= max_topology_multiplier` (`1.0` by default) — it can only shrink an
  already-sized position, never amplify it beyond what the deterministic
  volatility/confidence factors alone would produce.
- Deliberately **not** wired into `analyzer/market_analyzer.py`'s
  `trade`/`simulate`/`observe`/`reduce_risk` decision — see
  `analyzer/README.md` for why that integration point stays
  deterministic. This lives here instead because sizing already exists
  purely as a continuous multiplier chain applied *after* the analyzer has
  decided to trade, so adding a symmetric, shrink-only factor changes only
  *how large* an approved trade is, never *whether* it happens.
- Config: `phase_v2.dynamic_risk.topology_sizing_enabled` (default
  `true`), `min_topology_multiplier` (`0.5`), `max_topology_multiplier`
  (`1.0`) — a dedicated kill switch independent of
  `phase_v2.topology_learning.enabled` (which also gates the unrelated
  dashboard/retrain-trigger consumers).
- Wired via `main.py::_build_dynamic_sizing_payload(..., topology=...)`.

## Predicted volatility → position sizing (optional, config-gated swap)

`position_sizing.py::build_dynamic_position_sizing(..., predicted_volatility=None,
use_predicted_volatility=False)` can swap the volatility number that drives
`volatility_regime` classification, `annualized_volatility`, and the
`volatility_multiplier` itself, from the existing backward-looking
`rolling_volatility_20d` average to the forward-looking `volatility` head
of the optional multi-task model (`train_multitask.py`/`AetherNetMultiTask`,
see `inference/README.md`) — the root problem this closes: position sizing
previously had no actual volatility *forecast* to work with, only a trailing
statistic.

- Off by default (`phase_v2.dynamic_risk.use_predicted_volatility: false`):
  `_resolve_effective_volatility()` falls back to `rolling_volatility`
  whenever the flag is off, `predicted_volatility` is `None` (model not
  loaded, or inference failed for this bar), or both — byte-identical to
  pre-this-change behavior in every case.
- `PositionSizingDecision` gains `volatility_source` (`"rolling"` or
  `"predicted"`, defaults to `"rolling"`) so the dashboard/CSV export can
  always show which volatility number actually drove a given bar's sizing.
- This changes sizing only, never routing: `analyzer/market_analyzer.py`'s
  action categorization never reads `predicted_volatility` (see
  `analyzer/README.md`) — same "shrink/resize an already-approved trade,
  never decide whether it happens" boundary the topology multiplier above
  already established.
- Wired via `main.py::_build_dynamic_sizing_payload(..., predicted_volatility=...)`,
  fed by `gating_payload["final_volatility"]` — the full baseline-anchor-
  plus-per-expert-weighted-average blend (`moe/gating.py`'s
  `_weighted_blend()`), not directly from the single baseline-scale
  multitask model. See `moe/README.md`'s "now routes through gating"
  section.
- **Follow-up:** `final_volatility` (and therefore `predicted_volatility`
  here, when `use_predicted_volatility` is on) now also transitively
  includes the Phase 2 sequence encoder's contribution whenever
  `phase_v2.gating_network.sequence_weight` is enabled — see
  `moe/README.md`'s "Phase 2 sequence encoder now optionally blends into
  the gating decision" section, which explains why gating (not a second,
  parallel input here) was chosen as the integration point: this module
  already has exactly one volatility-forecast input, and adding a second
  one directly would risk the two silently disagreeing.

## Cross-sectional rank_20d → position sizing (optional, bounded, direction-preserving)

`position_sizing.py::rank_sizing_multiplier(rank_prediction,
rank_sizing_enabled, min_rank_multiplier=0.75, max_rank_multiplier=1.25)`
adds a fourth, optional factor to the
`volatility_multiplier × confidence_multiplier × topology_multiplier`
chain, sourced from the multitask/sequence models' `rank_20d` head — the
predicted cross-sectional percentile rank ([0, 1]) of this asset's
20-day forward return against the rest of the trading universe on that
date (see `train.py::compute_rank_ic()`, `development/Changelog.md`'s
"frontier-model edge investigation" entry). This is the first of the
Phase 4 ranking-signal outputs to be wired into an actual trading
decision — previously `rank_5d`/`rank_20d` were computed and logged
(`signal_payload["sequence_model"]`/`multitask_payload`) for monitoring
only, with zero influence on `target_weight`.

- `multiplier = min + (max-min) * rank_prediction`: a predicted rank near
  `1.0` (top of the universe) scales the position UP toward
  `max_rank_multiplier`; a rank near `0.0` (predicted bottom) scales it
  DOWN toward `min_rank_multiplier`; a rank of exactly `0.5` (predicted
  median) is a no-op (`1.0`). It only ever scales the magnitude of the
  direction the existing 1d-direction gating decision already picked —
  same "never flips sign, never decides whether a trade happens" boundary
  as `topology_sizing_multiplier()` above, except this factor can also
  amplify (not just shrink), bounded by `max_rank_multiplier`.
- A strict no-op (`1.0`) whenever `rank_sizing_enabled` is `false` or the
  rank prediction is `None` (model not loaded, inference failed, or
  universe too small that day for a rank to be defined — see
  `train.py`'s `min_universe_size` gate).
- **Off by default**
  (`phase_v2.dynamic_risk.rank_sizing_enabled: false`): the full backtest
  series for this signal is statistically significant (sequence model,
  mean rank-IC `0.073`, t-stat `4.40`), but the non-overlapping-date
  subsample (28 independent 20-day windows) was not yet independently
  significant on its own (t-stat `1.20`) — it ships available, tested,
  and wired end-to-end, but not defaulted on until validated further on
  more out-of-sample data. `min_rank_multiplier`/`max_rank_multiplier`
  default to `0.75`/`1.25`.
- Wired via `main.py::_build_dynamic_sizing_payload(...,
  predicted_rank_20d=...)`, fed by the sequence model's `rank_20d` head
  when available (strongest result), falling back to the multitask
  model's own `rank_20d` head otherwise. `predicted_rank_20d` is also
  surfaced directly on `signal_payload` for dashboard/CSV visibility,
  alongside the existing `predicted_return_magnitude`/`predicted_volatility`.
- `PositionSizingDecision` gains `rank_multiplier` (default `1.0`) and
  `rank_sizing_reason` (default `"rank_sizing_disabled_or_absent"`, or
  `"rank_prediction_scaled_sizing"` when actively engaged).
