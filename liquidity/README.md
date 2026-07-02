# liquidity

Owns the V2-12 per-asset liquidity and market-impact engine:

- `market_liquidity.py::assess_liquidity(...)` — pure, deterministic
  function using only daily OHLCV (no order book/VWAP/real bid-ask data
  required).

It computes, per asset per bar:

- `daily_dollar_volume` — `close * volume`, a DDV proxy
- `order_value` / `participation_rate` — how large the intended order is
  relative to that proxy
- `estimated_slippage` — `participation_rate * daily_volatility * slippage_factor`
- `spread_proxy` — a static lookup by security type (`TYPICAL_SPREAD_BY_TYPE`:
  equity vs. crypto)
- `estimated_round_trip_cost` — slippage + spread proxy

and classifies `liquidity_risk`/`recommended_action`:

| `liquidity_risk` | `recommended_action` | Trigger |
|---|---|---|
| `normal` | `allow` | participation below the thin threshold |
| `thin` | `simulate_instead` | participation above the thin threshold |
| `high_impact` | `reduce_size` | participation above the high-impact threshold |
| `blocked` | `block` | zero volume or DDV below the configured floor |

When `reduce_size` is recommended, `adjusted_target_weight` is applied
**before** `analyzer.market_analyzer` runs, so the analyzer always sees the
already-reduced weight. All thresholds live in `config.json`'s
`phase_v2.liquidity` block. `performance/triggers.py`'s
`liquidity_warning_trigger` watches this module's `block`/`reduce_size`
rate over a rolling window (explicitly excluding `simulate_instead`, which
is observation-mode routing, not a liquidity problem) and can flag
`retrain_candidate=true` for V2-17 to pick up.

Roadmap item V2-23.1 will replace these static thresholds with values
calibrated from real fill data once the experience pipeline (V2-13/14) has
accumulated enough history.
