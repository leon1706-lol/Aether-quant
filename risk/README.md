# risk

Per-asset-class risk control: sizing, leverage, the kill switch and manual overrides. Pure functions, shared by `main.py` and the simulators. `risk_controls.py` at the repo root holds the position-scaling and drawdown helpers.

## Base sizing: `position_sizing.py`

`build_dynamic_position_sizing()` returns a `PositionSizingDecision`: `volatility_multiplier * confidence_multiplier * topology * rank * rl`, then the cost multiplier. It never flips a trade or exceeds its cap (proved in `formal/AetherFormal/PositionSizing.lean`). Each optional multiplier is a strict no-op unless its flag is on and its model output exists.

| Multiplier | Function | Config | Shape |
|---|---|---|---|
| Volatility source | `_resolve_effective_volatility()` | `phase_v2.dynamic_risk.use_predicted_volatility` | Swaps rolling for predicted volatility |
| Topology | `topology_sizing_multiplier()` | `phase_v2.dynamic_risk.topology_sizing_enabled` | `[min, 1.0]`, shrink-only, needs a learned source |
| Rank | `rank_sizing_multiplier()` | `phase_v2.dynamic_risk.rank_sizing_enabled` | Bounded, keeps direction |
| RL overlay | `rl_sizing.py::rl_sizing_multiplier()` | `phase_v2.dynamic_risk.rl_sizing_enabled` | Bounded; a non-finite score is a no-op |
| Cost | `cost_sizing_multiplier()` | `phase_v2.costs.cost_sizing_enabled` | Shrink-only |

The target-weights path takes its weights from the file and skips this chain.

## Multi-asset-class risk dispatch: `asset_class_router.py`

`route_position_sizing()` is the single dispatch point, adapted to one decision shape so everything downstream stays class-agnostic.

- **Equity, crypto, bond:** `build_dynamic_position_sizing()`.
- **Futures (`futures_risk.py`):** margin-utilization targets, integer contracts. Specs come from `data/reference/futures_contract_specs.json`, or Lean's buying-power model with `phase_v2.futures_risk.margin_source: "live"`, falling back to static.
- **Forex (`forex_risk.py`):** leverage-utilization targets, with `cap_forex_target_to_book_weight()` as a ceiling for book members. `phase_v2.forex_risk.enabled` is false.
- **Options:** chain-aware, in [`portfolio/`](../portfolio/README.md). Three paradigms: vega budget, margin (backtest only) and equity ratio. `classify_volatility_view()` gates long-vol and short-vol shapes.
- **`resolve_asset_class_enabled()`, `should_liquidate_disabled_asset_class_position()`:** disabling a class liquidates what it holds. `book_candidate_trading_eligible()` is the book-side twin.

## Existing positions

Gated by `phase_v2.functionality.position_scaling` (off by default):

- **`should_scale_position()`:** a churn guard, resubmitting only when the target moved past a threshold.
- **`compute_incremental_order_quantity()`:** the signed delta for discrete contracts, so an absolute target can't stack.
- **`projected_signed_quantity()`:** sizes against held plus still-open quantity.

## Kill switch: `kill_switch.py`

`evaluate_kill_switch(metrics, config)` runs per bar over rolling return, drawdown velocity, live rank IC, consecutive losses, slippage divergence, model age and reconciliation breaches.

- **One lock:** a trip feeds `main.py`'s sticky trade lock, never a second one.
- **Liquidates:** in paper and live a trip liquidates instead of freezing the book (#289).
- **Options:** `release_rolling_sharpe` holds a trip until recovery, and `trip_confirm_bars` asks for consecutive readings. Every threshold defaults to a value it can't cross.
- **Rule sleeves:** a sleeve no longer trips on a model's age.

`manual_override.py` reads and writes the overrides behind `aq trade-lock` and `aq kill-switch`. See `development/architecture.md`.

## Backtest-only bypass flags (`risk_controls.py`)

Backtest only, off by default, and always false in paper and live:

- **`phase_v2.backtest.bypass_sticky_trade_lock`:** clears a drawdown or kill-switch lock at session rollover, because an unattended backtest has no human to clear it.
- **`phase_v2.backtest.bypass_regime_drawdown_gate`:** removes the regime's drawdown threshold.
- **`phase_v2.backtest.bypass_safety_gates`:** both of the above, kept for compatibility.

The target-weights path's velocity lock stays off by rule R-VEL1, recorded and enforced by paper readiness (#303).
