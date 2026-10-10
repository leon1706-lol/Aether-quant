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
`ml/datasets/validation_dataset.csv`, reward = realized PnL net of fees
(asymmetrically weighted so oversizing is punished more than undersizing —
the V5.4.1 fix for an earlier reward that made the policy look honestly
negative). `aq train --rl-sizing-only` wires it like `_train_topology_only()`.
**Ships
disabled** pending a retrain demonstrating positive expected reward over
the constant-`1.0` baseline (see `development/Problems.md` #71 and the
V5.4.1 changelog entry).
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

`book_candidate_trading_eligible()` (V5.6.0) is the book-side twin of `resolve_asset_class_enabled()`: a symbol of a disabled class (e.g. forex with `forex_risk.enabled=false`) is not a book candidate, live (`main.py`) or in the as-live simulation (`aq_cli._universe_asset_metadata`), so it cannot hold a slot or neutrality weight it will never trade.

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

Sizing for options is chain-aware, so the modules live in `portfolio/` —
see `portfolio/README.md` for the full options design (the 43-strategy
registry, held-position sizing, combo limit orders, assignment risk).
The sizing-relevant summary:

- **3 sizing paradigms**, dispatched by strategy shape: vega budget
  (`build_options_position_sizing()` single-leg / `build_multi_leg_position_sizing()`
  for bounded-risk multi-leg shapes, sized by `abs(net_vega)`); margin
  (`portfolio/options_margin_sizing.py` — naked/uncovered-leg/
  bounded-max-loss margin, hard-gated to `runtime_mode == "backtest"`);
  equity-ratio (`build_covered_protective_position_sizing()` — option
  legs sized off the held equity quantity).
- **Volatility-view gating**: `classify_volatility_view()` classifies
  `predicted_volatility` against chain ATM IV into
  long_vol/short_vol/neutral — gates straddle/strangle/iron-condor/
  butterfly selection only.
- **Strategy selection**: `phase_v2.options_risk.enabled_strategy_names`
  is an ordered priority list (first match that sizes wins) +
  `risk_tier_preference` (defined-risk-first by default) + optional
  per-asset override. A trained strategy-selector model can rerank the
  list (`route_multi_leg_option_sizing(..., strategy_selector_scores=...)`,
  dormant by default).
- Config: `phase_v2.options_risk.{enabled,target_delta_at_full_confidence,
  max_vega_budget_pct_of_equity,risk_free_rate,spread_strategy,
  multi_leg_strategies_enabled,max_positions_per_underlying,
  rotation_cooldown_bars,arbitrage_detector}`, off by default.
- **Verification status**: every combo-order path is code-complete but
  Lean-API-unverified — no real Lean backtest has placed a combo option
  order.

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

### Forex vs the book (V5.5.0)

`build_forex_position_sizing` is margin-driven, so its `target_weight` is several
x NAV; only direction came from the book. `cap_forex_target_to_book_weight()` makes
it a ceiling for a book member (`phase_v2.portfolio_book.forex_cap_to_book_weight`).
`main.py` also sizes against held + still-open order quantity
(`risk_controls.projected_signed_quantity`), resizes only on rebalance bars with a
`forex_resize_min_fraction` deadband, and gives forex shorts their own
`max_forex_short_exposure` budget. `rl_sizing_multiplier` returns a strict no-op
(`rl_sizing_non_finite_score`) when any action score is NaN/inf - NaN at index 0
used to select the most aggressive shrink (0.6x).

## Adding to / rotating an existing position

`risk_controls.py` (repo root) governs whether an already-open position may
be scaled toward a fresh target, instead of either fully blocking
(equity/crypto/bond) or restacking an absolute target as an incremental
order every bar (futures/options):

- `should_scale_position(current_weight, target_weight,
  rebalance_threshold_weight=0.03)` — equity/crypto/bond churn guard: resubmit
  `SetHoldings()` only when target moved ≥ threshold from current weight.
- `compute_incremental_order_quantity(target_quantity, current_quantity)` —
  signed delta a `MarketOrder`/`self.Buy` submits to converge a
  discrete-contract instrument (futures/options/spreads) toward its fresh
  absolute target (churn guard is "integer delta rounds to nonzero").

Gated by `phase_v2.functionality.position_scaling.{enabled,rotate_on_drift}`,
both off by default (`enabled` = may top up an open matching position;
`rotate_on_drift` = a drifted option contract/spread is rotated
`Liquidate()` → fresh entry same bar — independent of `enabled` because a
same-bar reenter carries real transient margin/vega exposure). Scale-down:
single-leg negative delta sells via `MarketOrder(contract_symbol, delta)`;
multi-leg via `self.Sell(strategy, abs(delta))`.

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

## Backtest safety-gate bypass flags (`risk_controls.py`)

Three flags, all backtest-only (`runtime_mode == "backtest"`, else always
`False`) and off by default. The legacy flag still works standalone; the
two split flags both OR the legacy flag in for backward compatibility:

- `is_backtest_safety_bypass_active(runtime_mode, bypass_flag)` —
  **legacy/combined**, `phase_v2.backtest.bypass_safety_gates` (covers both
  behaviors below at once; kept for backward compatibility).
- `is_sticky_trade_lock_bypass_active(...)` — backtesting with
  `phase_v2.backtest.bypass_sticky_trade_lock` OR the legacy flag. Controls
  **only** `main.py`'s session-rollover clear of a
  `total_drawdown_limit_breached`/`kill_switch_*` sticky lock — never the
  regime drawdown branch. (Rationale: `kill_switch_*` locks are exempt from
  the normal daily auto-clear — correct for live/paper where a human
  decides — but an unattended backtest has no human to clear it.)
- `is_regime_drawdown_bypass_active(...)` — backtesting with
  `phase_v2.backtest.bypass_regime_drawdown_gate` OR the legacy flag.
  Controls **only** `main.py::_build_regime_payload()`'s
  `risk_off_drawdown_threshold` override (set to infinity when active) —
  never the sticky trade-lock clear. The two flags are deliberately
  independent: unsticking a stuck kill-switch lock shouldn't force
  disabling the unrelated regime-drawdown protection too.
