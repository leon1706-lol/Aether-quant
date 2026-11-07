# liquidity

Per-asset liquidity and market impact from daily OHLCV alone. `market_liquidity.py::build_liquidity_decision()` is pure and needs no order book.

**Per bar**

- **`daily_dollar_volume`:** `close * volume`. A zero-volume bar uses a typical figure (`phase_v2.liquidity.zero_volume_fallback_ddv_by_type`), so bad data doesn't read as blocked.
- **`participation_rate`, `estimated_slippage`:** order size against that volume, times daily volatility.
- **`spread_proxy`:** the Corwin & Schultz (2012) high-low estimator, with a static fallback for the first bars. `cap_spread_proxy()` clamps what the gate sees per class (`phase_v2.liquidity.max_spread_proxy_by_type`), because it reads crypto and forex volatility as spread (#133, #143). The model feature stays uncapped.
- **`estimated_round_trip_cost`:** slippage plus spread. `main.py`'s Lean `SlippageModel` reads this (`execution/README.md`).

| `liquidity_risk` | `recommended_action` | Trigger |
|---|---|---|
| `normal` | `allow` | Participation below the thin threshold |
| `thin` | `simulate_instead` | Above the thin threshold |
| `high_impact` | `reduce_size` | Above the high-impact threshold |
| `blocked` | `block` | Zero volume, volume below the floor, or cost above `phase_v2.liquidity.max_round_trip_cost_fraction` |

`reduce_size` applies before the analyzer runs. Thresholds are in `phase_v2.liquidity`. `performance/triggers.py` watches the block and reduce rates.

## A model input too

- **Features:** `train.py::add_liquidity_features()` adds `liquidity_log_dollar_volume` and `liquidity_spread_proxy`. Participation and slippage are left out, because they need an order size no offline row has.
- **Order matters:** it runs on the raw frame, before `engineer_features()` drops each asset's first row, to match live's window.
- **Runtime:** `main.py::_build_model_input()` computes the spread once, and the decision reuses it.
