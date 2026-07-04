# liquidity

Owns the V2-12 per-asset liquidity and market-impact engine:

- `market_liquidity.py::build_liquidity_decision(...)` — pure, deterministic
  function using only daily OHLCV (no order book/VWAP/real bid-ask data
  required).

It computes, per asset per bar:

- `daily_dollar_volume` — `close * volume`, a DDV proxy
- `order_value` / `participation_rate` — how large the intended order is
  relative to that proxy
- `estimated_slippage` — `participation_rate * daily_volatility * slippage_factor`
- `spread_proxy` — **dynamic since the static/dynamic architecture audit**:
  `market_liquidity.py::estimate_high_low_spread(...)` implements the
  Corwin & Schultz (2012) high-low bid-ask spread estimator, computed from
  each asset's own recent daily high/low ranges (`main.py` pulls these from
  `self.symbol_windows[symbol]`, already collected every bar — no new
  instrumentation needed). `TYPICAL_SPREAD_BY_TYPE`'s static 2-entry lookup
  remains only as a fallback for the first bar or two of a run, before
  `phase_v2.liquidity.spread_estimation.min_bars` worth of history exists,
  or if the estimator's per-window result is degenerate.
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

**V2-23.1, closed.** The original plan was to calibrate the spread proxy
from real historical fill/slippage data once the experience pipeline
(V2-13/14) accumulated enough history. A deeper look found that premise had
no data to stand on: Lean backtest fills never had a `SlippageModel` set
(only an `InteractiveBrokersFeeModel`, which is a transaction *fee*, not
price-impact slippage), and observation-mode's `SimulatedPortfolioState`
always calls `execution.order_gate.simulate_fill(...)` with the default
`slippage_bps=0.0` — so no realized spread/slippage had ever been recorded
anywhere in `experience_events` to calibrate from. Rather than build new
fill-telemetry instrumentation from scratch as a prerequisite, V2-23.1
shipped via `estimate_high_low_spread()` instead — a published, closed-form
estimator that needs only the OHLC data already collected every bar. Same
end goal (a real, dynamic, per-asset spread estimate instead of a static
lookup), no new instrumentation, no waiting for data to accumulate.
