# risk

Dynamic, per-asset-class risk control: volatility-adjusted position sizing,
leverage caps, drawdown-aware sizing, liquidity checks, market-impact/slippage
controls, and asset-class dispatch (equity/crypto/bond, futures, options,
forex). Equity/crypto/bond flow through the shared volatility-scaled sizer;
futures/options/forex get dedicated sizers behind one dispatch point
(`asset_class_router.py`) so downstream consumers stay asset-class-agnostic.

## Base sizing — `position_sizing.py`

`build_dynamic_position_sizing(...)` → `PositionSizingDecision`.
`classify_volatility_regime()` buckets `rolling_volatility_20d` into
low/normal/high, driving `volatility_multiplier` (shrinks in high-vol,
expands in low-vol toward a target daily volatility). Full chain:

`volatility_multiplier × confidence_multiplier(0.5+0.5*confidence) ×
topology_multiplier × rank_multiplier × rl_multiplier`, then
`cost_sizing_multiplier()` on top. Every optional multiplier below is a
strict `1.0` no-op unless its own config flag is on and its model output is
present.

| Multiplier | Function | Config flag (default) | Bounds / shape |
|---|---|---|---|
| Volatility source swap | `_resolve_effective_volatility()` | `phase_v2.dynamic_risk.use_predicted_volatility` (`false`) | swaps `rolling_volatility_20d` → predicted |
| Topology | `topology_sizing_multiplier()` | `phase_v2.dynamic_risk.topology_sizing_enabled` (`true`) | `[min,1.0]`, shrink-only |
| Rank | `rank_sizing_multiplier()` | `phase_v2.dynamic_risk.rank_sizing_enabled` (`false`) | `[0.75,1.25]`, can amplify |
| RL overlay | `rl_sizing.py::rl_sizing_multiplier()` | `phase_v2.dynamic_risk.rl_sizing_enabled` (`false`) | `[0.6,1.0]`, shrink-only |
| Cost | `cost_sizing_multiplier()` | `phase_v2.costs.cost_sizing_enabled` (`false`) | `<=1.0`, shrink-only |

### Predicted volatility

`build_dynamic_position_sizing(..., predicted_volatility=None,
use_predicted_volatility=False)` swaps the number driving
`volatility_regime`/`annualized_volatility`/`volatility_multiplier` from
trailing `rolling_volatility_20d` to the forward-looking `volatility` head of
the multi-task model (`train_multitask.py`/`AetherNetMultiTask`).
`_resolve_effective_volatility()` falls back to rolling whenever the flag is
off or the prediction is `None`. `PositionSizingDecision.volatility_source`
(`"rolling"`/`"predicted"`) records which was used. Fed from
`gating_payload["final_volatility"]` (`moe/gating.py::_weighted_blend()`,
also includes the sequence encoder when `phase_v2.gating_network.sequence_weight`
is on — see `moe/README.md`), not the raw multitask output directly. Wired
via `main.py::_build_dynamic_sizing_payload(..., predicted_volatility=...)`.
Sizing only, never routing — `analyzer/market_analyzer.py` never reads it.

### Topology multiplier (shrink-only)

`topology_sizing_multiplier(topology_source, topology_confidence,
topology_disagreement, min_topology_multiplier=0.5,
max_topology_multiplier=1.0)`. No-op unless `topology_source == "learned"`
(the `topology/learned_topology.py` overlay's own confidence-gated label);
otherwise `multiplier = min + (max-min) * confidence * (1-disagreement)`,
always `<= max`. Config: `phase_v2.dynamic_risk.topology_sizing_enabled`
(`true`), `min_topology_multiplier`/`max_topology_multiplier` (`0.5`/`1.0`)
— independent of `phase_v2.topology_learning.enabled` (gates the unrelated
dashboard/retrain consumers). Wired via
`main.py::_build_dynamic_sizing_payload(..., topology=...)`. Not wired into
`analyzer/market_analyzer.py`'s trade decision — changes size only.

### Rank multiplier (bounded, direction-preserving)

`rank_sizing_multiplier(rank_prediction, rank_sizing_enabled,
min_rank_multiplier=0.75, max_rank_multiplier=1.25)`. Source: `rank_20d`
head (predicted cross-sectional percentile rank, [0,1], `train.py::compute_rank_ic()`).
`multiplier = min + (max-min) * rank_prediction` — rank near `1.0` scales up,
near `0.0` scales down, `0.5` is a no-op; can amplify (unlike topology). No-op
if disabled or prediction is `None` (model unloaded, inference failed, or
universe below `train.py`'s `min_universe_size`). Config:
`phase_v2.dynamic_risk.rank_sizing_enabled` — **default `false`**: full-series
backtest is significant (sequence model, mean rank-IC 0.073, t-stat 4.40) but
the 28-window non-overlapping subsample isn't yet independently significant
(t-stat 1.20). `PositionSizingDecision.rank_multiplier`/`.rank_sizing_reason`.
Wired via `main.py::_build_dynamic_sizing_payload(..., predicted_rank_20d=...)`
— sequence model's head preferred, multitask model's as fallback.

### RL sizing overlay (Phase 4.12 — ships disabled)

`rl_sizing.py::rl_sizing_multiplier(model, state, rl_sizing_enabled,
min_rl_multiplier=0.6, max_rl_multiplier=1.0)` — an offline **contextual
bandit**, not online/off-policy RL (no exploration data exists;
`train_rl_sizing.py` docstring). `build_rl_sizing_state()` assembles
`RL_SIZING_STATE_KEYS` (rank confidence, predicted volatility, regime,
topology risk, liquidity) from `base_features`/`confidence`; returns `None`
(no-op) if any key is missing or the flag is off. `_softmax_argmax_index()`
is deterministic — argmax over the trained policy, never samples at runtime.
Trained by `train_rl_sizing.py`: softmax policy-gradient over
`ml/datasets/validation_dataset.csv`, reward = realized PnL net of fees.
`aq train --rl-sizing-only` wires it like `_train_topology_only()`. **Ships
disabled**: backtest expected reward (`-8.542e-5`) underperformed the
constant-`1.0` baseline (`-8.264e-5`) — documented in
`development/Problems.md` #71 rather than re-tuned.
`PositionSizingDecision.rl_multiplier`/`.rl_sizing_reason`. All chain
multipliers render in the webui's `AssetSizingTable.tsx` as a `label×value`
chip, muted at `1.0`.

### Cost-scaled sizing

`cost_sizing_multiplier()` shrinks (never grows) sized weight when expected
edge doesn't clear expected round-trip cost (`execution/cost_model.py`) —
same shrink-only contract as topology. Config:
`phase_v2.costs.cost_sizing_enabled` (default off).

## Multi-asset-class dispatch — `asset_class_router.py`

`route_position_sizing()` is the single dispatch point. Equity/crypto/bond →
`build_dynamic_position_sizing()` unchanged (bonds get better features via
`features/bond_features.py`, not a new sizing formula). `future`/`option` →
dedicated modules below, adapted onto the same `PositionSizingDecision` shape
so `portfolio/book_construction.py`, liquidity, analyzer, and
`main.py::_apply_signal()` stay asset-class-agnostic.

### Futures — `futures_risk.py`

`build_futures_position_sizing()` — margin-utilization-targeted, not
volatility-of-notional. Max contracts at `max_margin_utilization` (hard
ceiling), scales toward `target_margin_utilization` by confidence, floors to
integer `contract_count`. Specs via `load_futures_contract_specs()` from
`data/reference/futures_contract_specs.json` (static fallback, always
available). **Live margin source (opt-in, Problems.md #67)**:
`phase_v2.futures_risk.margin_source` (`"static"` default / `"live"`,
`resolve_futures_margin_source()`) attaches Lean's IB-calibrated
`BuyingPowerModel` per-security (`main.py::_add_asset()`, never a global
`SetBrokerageModel()`), queried via `main.py::_resolve_futures_contract_spec()`/
`build_live_contract_spec()`. "Live" = Lean's local calc, no network
round-trip; falls back to static file on any failure. Code-complete,
Lean-API-unverified. `rollover_due()` is a diagnostic date check only —
rollover itself is Lean's native `add_future()` + `SetFilter()`. Config:
`phase_v2.futures_risk.{enabled,target_margin_utilization,
max_margin_utilization,margin_source}`, off by default.

### Options — `portfolio/options_strategy.py` (lives in `portfolio/`, needs the option chain)

- **Single-leg**: `build_options_position_sizing()` — BSM greeks
  (`features/options_greeks.py`) size a long call/put by target delta
  (scales with confidence), capped by a vega risk budget. Config:
  `phase_v2.options_risk.{enabled,target_delta_at_full_confidence,
  max_vega_budget_pct_of_equity,risk_free_rate}`, off by default.
- **Vertical spread**: `phase_v2.options_risk.spread_strategy`
  (`"single_leg"`/`"vertical"`) → `build_vertical_spread_position_sizing()`/
  `select_vertical_spread_legs()` — sized by **net** vega (long − short);
  `short_leg_delta_offset` (default `0.20`); short leg filtered to the
  risk-capping strike side explicitly. `main.py::_apply_option_order()`
  places it atomically (`OptionStrategies.bull_call_spread()`/
  `bear_put_spread()` + `self.Buy(strategy, quantity)`); closing liquidates
  each leg independently, not atomic (Problems.md #38).
- **Full 43-strategy registry** (Problems.md #59):
  `MULTI_LEG_STRATEGY_REGISTRY`, one `StrategySpec` per `OptionStrategies`
  factory (factory name, `arg_order`, per-leg side/ratio/right/strike_role
  transcribed from Lean's `OptionStrategies.cs`), grouped into shape families
  (vertical, straddle, strangle, butterfly, iron condor/butterfly, calendar,
  backspread, ladder, naked, covered/protective, collar, 3 arbitrage
  families), one shared selector per family. Gated by
  `phase_v2.options_risk.multi_leg_strategies_enabled` (default `false`).
  - **3 sizing paradigms**: vega budget (`build_multi_leg_position_sizing()`,
    bounded-risk shapes, sizes by `abs(net_vega)`); margin
    (`portfolio/options_margin_sizing.py` — Reg-T-style naked/uncovered-leg/
    bounded-max-loss margin, mirrors `futures_risk.py`'s soft-target/
    hard-ceiling shape, first approximation not broker-accurate, hard-gated
    to `runtime_mode == "backtest"` as a code invariant); equity-ratio
    (`build_covered_protective_position_sizing()` — option leg(s)
    floor-rounded off the held equity quantity; `main.py` never submits
    Lean's bundled `covered_call`/`protective_put`/`protective_collar`
    factory, only the option leg(s), force-liquidated once equity no longer
    covers them).
  - Risk-tier notes: of the 4 ladders, only `bull_call_ladder`/
    `bear_put_ladder` are net-short/unbounded; of the 4 backspreads, only the
    inverted `short_*` variants are unbounded.
  - **Volatility-view gating**: `atm_implied_volatility()`/
    `classify_volatility_view()` classify `predicted_volatility`
    (annualized ×√252 at the `main.py` call site) against chain ATM IV into
    long_vol/short_vol/neutral — gates straddle/strangle/iron-condor/
    butterfly selection only.
  - **Strategy selection**: `phase_v2.options_risk.enabled_strategy_names`
    is an ordered priority list (first match that sizes wins).
    `risk_tier_preference` (`"defined_risk_first"` default) reorders
    defined-risk names ahead of unbounded ones. Per-asset override via
    `"options_strategy_override": {"enabled_strategy_names": [...]}` on a
    `phase1.universe.assets` entry (`resolve_enabled_strategy_names()`).
  - **Learned reranking** (Problems.md #61):
    `route_multi_leg_option_sizing(..., strategy_selector_scores=None)` —
    falsy (default) reproduces static `order_enabled_strategies()` ordering
    byte-identically; when present, `rerank_enabled_strategies_by_score()`
    reranks by score. Model: `train_strategy_selector.py`/
    `inference/strategy_selector_inference.py` (`portfolio/README.md`).
    Ships dormant (`phase_v2.strategy_selector.enabled=false`).
  - **Arbitrage detector** (Problems.md #60):
    `portfolio/options_arbitrage_detector.py` — box-spread/put-call-parity/
    jelly-roll fair value vs. chain market price via a configurable bps
    threshold (`phase_v2.options_risk.arbitrage_detector`, default
    `enabled: false`); resolves strike/expiry roles from
    `MULTI_LEG_STRATEGY_REGISTRY` directly.
- **Held-position sizing**: `build_options_position_sizing_for_contract()`/
  `build_vertical_spread_position_sizing_for_legs()` size the actually-held
  contract/legs on current greeks, skipping chain selection (share
  `_size_single_leg_contract()`/`_size_vertical_spread()` with the chain-first
  sizers). Multi-position book: `phase_v2.options_risk.max_positions_per_underlying`
  (default `1`); tracked in `main.py`'s
  `self.option_positions_by_symbol: dict[str, list[dict]]`
  (`_apply_option_order()`/`_apply_option_multi_leg_order()`;
  `_liquidate_option_record()` closes one, `_liquidate_position()` closes all).
- **Combo limit orders**: `main.py::_try_submit_multi_leg_limit_order()` — N-leg
  combo via Lean's `ComboLimitOrder` (`_apply_option_multi_leg_order()`).
  Note: supersedes the earlier 2-leg-only `_try_submit_spread_limit_order()`/
  `_apply_option_spread_order()`, folded into "multi_leg" with the full
  registry. `pending_limit_orders` keyed by order-target Symbol, not chain
  symbol_key, so concurrent positions on one underlying don't collide.
- **Anti-thrashing**: `rotate_on_drift` (below), `phase_v2.options_risk.rotation_cooldown_bars`
  (default `5`), same-bar netting (re-sizes new legs against post-liquidation
  `Portfolio.TotalPortfolioValue`). `_active_position_count()` resolves each
  Symbol to its chain-level identity first, so a 4-leg position counts once,
  not once per leg.
- **Dividend/assignment risk** (Problems.md #61):
  `portfolio/options_assignment_risk.py` + `data_pipeline/dividend_backfill.py`,
  and `features/options_greeks.py::baw_american_price()` (Barone-Adesi-Whaley)
  — pure feature/signal modules, no `risk/` involvement (`portfolio/README.md`).
- **Verification status**: every combo-order path (single-leg, vertical,
  43-strategy registry, margin sizing) is code-complete but
  Lean-API-unverified — no real Lean backtest has placed a combo option order.

### Forex — `forex_risk.py`

`build_forex_position_sizing()` mirrors `futures_risk.py`'s soft-target/
hard-ceiling shape, leverage-utilization-targeted (margin = `lot_size * price
* margin_pct`). Specs via `load_forex_pair_specs()` from
`data/reference/forex_pair_specs.json` (15 pairs — EURUSD, GBPUSD, USDJPY,
AUDUSD, USDCAD, USDCHF, NZDUSD, EURGBP, EURJPY, GBPJPY, EURCHF, EURAUD,
AUDJPY, CADJPY, GBPCAD — via `aq fetch forex`, `data_pipeline/fetch.py`, in
`config.json`'s universe; see `development/asset_universe.md`).
`asset_class_router.py::_forex_decision_to_position_sizing()` adapts the
result; `resolve_asset_class_enabled()` takes `forex_risk_enabled`.
Quote-bar (bid/ask, not trade-bar) data: additive fallback in
`main.py::on_data()` consulting `slice.quote_bars` only for
`security_type == "forex"` with no `TradeBar` that bar. Config:
`phase_v2.forex_risk.enabled`, default `false` — nothing technically blocks
enabling (`aq config set phase_v2.forex_risk.enabled true`). Code-complete,
IB-unverified for live.

Individual-bond trading is infeasible under this Lean version (no
`SecurityType.Bond`) — reframed as bond-ETF duration/convexity in
`features/bond_features.py` (`portfolio/README.md`).

## Adding to / rotating an existing position (Problems.md #57, #58)

`risk_controls.py` (repo root) closes a bug where a repeated same-direction
signal either fully blocked (equity/crypto/bond) or silently restacked an
absolute sizing target as an incremental order every bar
(futures/options — dormant bug, reachable only when those risk modules are
enabled):

- `should_scale_position(current_weight, target_weight,
  rebalance_threshold_weight=0.03)` — equity/crypto/bond churn guard: resubmit
  `SetHoldings()` only when target moved ≥ threshold from current weight.
- `compute_incremental_order_quantity(target_quantity, current_quantity)` —
  signed delta a `MarketOrder`/`self.Buy` submits to converge a
  discrete-contract instrument (futures/options/spreads) toward its fresh
  absolute target. Applied unconditionally (churn guard is simply "integer
  delta rounds to nonzero" — no weight threshold applies to a margin/vega
  budget target).

Gated by `phase_v2.functionality.position_scaling.{enabled,rotate_on_drift}`,
both off by default:
- `enabled` — whether an already-open matching position may be topped up.
  `false` = byte-identical pre-existing behavior (`kept_long`/`kept_short`
  for equity/crypto/bond; safe no-op for futures/options).
- `rotate_on_drift` — whether a drifted option contract/spread (different
  strike/expiry) is rotated: `Liquidate()` old, fresh entry same bar.
  Independent of `enabled` — a same-bar reenter carries real transient
  margin/vega exposure a same-instrument top-up doesn't.

Scale-down: single-leg — `delta == 0` is the only no-op, negative delta sells
via `MarketOrder(contract_symbol, delta)`. Multi-leg —
`self.Sell(strategy, abs(delta))` (Sell-side sibling of `self.Buy()` entry).
None of `build_futures_position_sizing()`/`build_options_position_sizing()`/
`build_vertical_spread_position_sizing()` needed signature changes — the bug
was purely `main.py`'s execution layer treating an absolute target as
incremental.

## Liquidating positions when an asset class is disabled

Flipping `phase_v2.futures_risk.enabled`/`phase_v2.options_risk.enabled` to
`False` mid-run zeroes new *sizing* but previously left an already-open
position untouched (equity/crypto/bond have no enable/disable flag — this
only applies to futures/options).

- `asset_class_router.py::resolve_asset_class_enabled(asset_class,
  futures_risk_enabled, options_risk_enabled, forex_risk_enabled=True)` —
  pure lookup: `True` for equity/crypto/bond/unrecognized always;
  future/option/forex follow their flags.
- `asset_class_router.py::should_liquidate_disabled_asset_class_position(
  asset_class_enabled, is_invested)` — pure predicate:
  `(not asset_class_enabled) and is_invested`.
- `main.py::_liquidate_positions_for_disabled_asset_classes()` — per-bar
  sweep called right after `_refresh_risk_state()`. Liquidates via real
  `_liquidate_position()` or simulated
  `experience/simulated_portfolio.py::SimulatedPortfolioState.exit_using_last_known_price()`;
  logs via `self.Debug()` only.

## Kill switch and manual overrides

`kill_switch.py::evaluate_kill_switch(runtime_metrics, config)` →
`KillSwitchDecision` — automated production circuit breaker. Pure per-bar
function over tracked runtime state (rolling return history, drawdown
velocity, live rank-IC, consecutive losing sessions, slippage divergence,
model age, a reconciliation-breach flag); trips `main.py`'s existing sticky
trade lock (never a second one) if any of 7 independently config-gated
conditions fires. Every threshold defaults to a value it can never cross —
strict no-op until configured.

`manual_override.py`: `read_manual_trade_lock_override()`/
`write_manual_trade_lock_override()` (pre-existing trade-lock override);
`read_kill_switch_manual_override()`/`write_kill_switch_manual_override()`
(matching `kill_switch_manual_override` key, same read/write/cache shape).
Both driven by `aq kill-switch --arm|--disarm|--auto|--status|--history`.

See `development/architecture.md`'s Kill-Switch, Reconciliation, and
Auto-Rollback Contract, including `execution/reconciliation.py` and
`retraining/auto_rollback.py`.

## Backtest safety-gate bypass flags (`risk_controls.py`, V5.2.7)

Three flags, all backtest-only (`runtime_mode == "backtest"`, else always
`False`) and off by default. The legacy flag still works standalone; new
code should prefer the two split flags, which both OR the legacy flag in for
backward compatibility.

- `is_backtest_safety_bypass_active(runtime_mode, bypass_flag)` —
  **legacy/combined**, `phase_v2.backtest.bypass_safety_gates`. Its old
  docstring claimed a narrow scope, but it always covered both behaviors
  below at once. Kept for backward compatibility only.
- `is_sticky_trade_lock_bypass_active(runtime_mode, sticky_bypass_flag,
  legacy_bypass_flag)` — true when backtesting with EITHER
  `phase_v2.backtest.bypass_sticky_trade_lock` OR the legacy flag. Controls
  **only** `main.py`'s session-rollover clear of a
  `total_drawdown_limit_breached`/`kill_switch_*` sticky lock — never the
  regime drawdown branch. Fixes a real bug: `kill_switch_*` reasons are
  deliberately exempt from the normal daily auto-clear (correct for
  live/paper, where a human decides when to resume) but an unattended
  backtest has no human to clear it — one real case stayed locked 13 months
  of a 2.2-year backtest after a single trip.
- `is_regime_drawdown_bypass_active(runtime_mode, regime_bypass_flag,
  legacy_bypass_flag)` — true when backtesting with EITHER
  `phase_v2.backtest.bypass_regime_drawdown_gate` OR the legacy flag.
  Controls **only** `main.py::_build_regime_payload()`'s
  `risk_off_drawdown_threshold` override (set to infinity when active) —
  never the sticky trade-lock clear. The bearish-trend/high-vol and
  composite-risk-score branches of `classify_risk_regime` stay active
  regardless.

The two split flags are deliberately independent: unsticking a stuck
kill-switch lock shouldn't force disabling the unrelated regime-drawdown
protection too.
