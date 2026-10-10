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
- `spread_proxy` — dynamic: `market_liquidity.py::estimate_high_low_spread(...)` implements the
  Corwin & Schultz (2012) high-low bid-ask spread estimator, computed from
  each asset's own recent daily high/low ranges (`main.py` pulls these from
  `self.symbol_windows[symbol]`, already collected every bar — no new
  instrumentation needed). `TYPICAL_SPREAD_BY_TYPE`'s static 2-entry lookup
  remains only as a fallback for the first bar or two of a run, before
  `phase_v2.liquidity.spread_estimation.min_bars` worth of history exists,
  or if the estimator's per-window result is degenerate.
- `estimated_round_trip_cost` — slippage + spread proxy
- **zero-volume DDV fallback** — when a bar's volume is exactly zero (a
  known data-quality artifact, not a real no-trade day),
  `TYPICAL_DAILY_DOLLAR_VOLUME_BY_TYPE` supplies a per-security-type
  typical DDV (configurable via
  `phase_v2.liquidity.zero_volume_fallback_ddv_by_type`) so the decision
  degrades to a conservative estimate instead of classifying every such
  bar as `blocked`.
- `cap_spread_proxy(spread, security_type, caps)` clamps the spread the *gate/cost* sees
  per asset class (`phase_v2.liquidity.max_spread_proxy_by_type`: crypto 0.001, forex
  0.0003). Corwin-Schultz reads crypto/forex daily high-low volatility as a ~1% spread,
  which blocked every crypto book selection against the 0.25% round-trip ceiling; the
  `liquidity_spread_proxy` *model feature* is deliberately left uncapped (Problems #133).
  V5.6.0 (#143): equity is capped at 0.001 too - the estimator exceeded the 0.25% ceiling on 62% of
  equity-days (AAPL median 40 bps against a real spread near 1 bp) and blocked ~24% of book-member decisions.

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
`retrain_candidate=true` for `retraining/` to pick up.

## Genuine model input feature (Phase 1 remainder)

Two asset-intrinsic liquidity quantities are now genuine model *inputs*,
not just downstream consumers of the model's own prediction — see
`regime/README.md`/`topology/README.md` for the matching story on those
two subsystems.

- `train.py::add_liquidity_features()` adds `liquidity_log_dollar_volume`
  (log1p of `close × volume`) and `liquidity_spread_proxy` (this module's
  own `estimate_high_low_spread()`, over a trailing 25-bar window, static
  fallback for the first bar) as new scaled continuous model inputs.
  **Deliberately excludes `participation_rate`/`estimated_slippage`** —
  both need an assumed order size (`target_weight × portfolio_value`),
  which has no principled offline value before any sizing decision
  exists; feeding a made-up order size in as a training feature would be
  circular. A documented adaptation of the original plan text, not an
  oversight.
- **Must run on the raw per-asset frame, before `train.py::engineer_features()`** —
  `engineer_features()` drops each asset's first raw row, so calling
  `add_liquidity_features()` *after* it would leave `spread_proxy`'s
  trailing window silently missing the true first bar for roughly each
  asset's first 25 rows — a real discrepancy from `main.py`'s live
  `self.symbol_windows`, which does include that bar. Verified via a
  train/runtime parity script (see `development/Changelog.md`'s
  "Phase 1 remainder + Phase 2" entry).
- `main.py::_build_model_input()` computes the same spread estimate once,
  before running any model, and the later `build_liquidity_decision()`
  call (the real sizing/liquidity decision) reuses that exact value
  instead of recomputing it a second time.

The spread proxy is the Corwin & Schultz (2012) high-low estimator — a
published, closed-form estimate needing only the OHLC data already
collected every bar, chosen over calibrating from realized fills after an
audit found no realized spread/slippage had ever been recorded in
`experience_events` to calibrate from. `main.py` now also attaches a real
Lean `SlippageModel` to every security reading this module's
`estimated_round_trip_cost` every bar (see `execution/README.md`'s
"Real fill slippage" section).

## A harder floor: `max_round_trip_cost_fraction`

`build_liquidity_decision()` gained an optional keyword,
`max_round_trip_cost_fraction` (default `None`, byte-identical when
unset): once `estimated_round_trip_cost` itself (not `participation_rate`)
crosses this fraction, the decision blocks outright regardless of how
small the order's participation rate looks — catching the case a thin,
low-participation order can still be genuinely expensive to fill. Config
per preset via `phase_v2.liquidity.max_round_trip_cost_fraction`.
