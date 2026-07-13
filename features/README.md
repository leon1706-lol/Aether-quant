# features

Pure, dependency-light feature-computation functions shared between the
offline training pipeline (`train.py`) and the Lean runtime (`main.py`) —
every function here is called from both places for train/inference parity
by construction, never re-derived independently in either one.

- `technical_indicators.py` — RSI, ATR%, Bollinger %B, volume z-score,
  MACD histogram, distance-from-52w-high, cross-sectional momentum rank.
- `macro_features.py` — cross-asset "macro" signals derived from bond-ETF/
  crypto price momentum (yield-curve slope proxy, credit spread proxy,
  crypto risk appetite proxy), computed once per date/bar and broadcast
  identically to every asset's model input.
- `bond_features.py` — the real-data sibling of `macro_features.py`'s
  proxies: actual FRED Treasury-yield/credit-spread series
  (`data_pipeline/fred_backfill.py`, no API key required) instead of
  price-momentum proxies, plus an empirically-regressed per-ETF duration
  beta (`empirical_duration_beta()`). All 5 features broadcast to every
  asset, not just bonds — the mechanism making real yield-curve signal
  usable for equity/crypto predictions too.
- `options_greeks.py` — real Black-Scholes-Merton pricing, greeks (delta/
  gamma/theta/vega/rho), and implied volatility (safeguarded Newton-
  Raphson + bisection). Verified against Hull's textbook example and
  put-call parity (`tests/test_options_greeks.py`). Consumed by
  `portfolio/options_strategy.py` for greeks-sized options position
  construction — see `risk/README.md`/`portfolio/README.md`.
- `derivatives_macro_features.py` — futures term-structure slope and
  options put/call-ratio (a bounded skew, not a raw ratio)/IV-skew,
  broadcast to every asset like the macro/bond features above. Fully
  wired into both pipelines but always neutral (`0.0`) until
  `config.json`'s universe contains futures/options assets shaped for a
  real front/next-month or chain-aggregate lookup — see
  `train.py::build_derivatives_macro_features_by_date()`'s docstring and
  `development/Problems.md` #29.

## Neutral-default convention

Every function here returns a documented neutral default (almost always
`0.0`) when its inputs are missing — a reference ticker not yet trading, a
FRED series never backfilled, no futures/options data configured — rather
than raising. This is deliberate: "no data available" must be
indistinguishable from "the signal happens to be neutral today" in the
model's input, never a crash. The one exception is
`bond_features.py::empirical_duration_beta()`, which returns `None` (not
`0.0`) below its minimum-observation floor — an unknown duration
sensitivity must stay distinguishable from a genuinely-zero one; callers
are responsible for substituting the neutral default at the point they
assign a model-input feature value.
