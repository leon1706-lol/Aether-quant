# features

Pure feature functions called by both `train.py` and `main.py`, so training and runtime can't drift. Each is neutral when its input is missing.

**Neutral default:** missing data returns `0.0`, so "no data" reads as "neutral today", never a crash. The exception is `empirical_duration_beta()`, which returns `None` below its minimum observations, to keep "unknown" apart from "zero".

| Module | What |
|---|---|
| `technical_indicators.py` | RSI, ATR%, Bollinger %B, volume z-score, MACD histogram, distance from the 52-week high, cross-sectional momentum rank |
| `cross_asset_timing.py` | **The one definition of what a tick may see.** A daily bar exists once its period closed: equity at the close, crypto and forex at the next midnight. `CrossAssetTimeline` replays it for `train.py`, so a dataset row sees what live would (#135). Handles Lean's forex holidays |
| `macro_features.py` | Yield-curve slope, credit spread and crypto risk-appetite proxies, from prices |
| `bond_features.py` | Real FRED yield and credit series, and a rolling duration beta |
| `alt_data_features.py` | VIX level and term structure, financial-conditions change. Publication-lag aware (`series_value_asof()`) |
| `derivatives_macro_features.py` | Futures term structure, put/call skew. Neutral until such assets are in the universe (#29) |
| `cross_asset_sensitivity.py` | Rolling betas to VIX, real rate, credit and dollar, so macro varies cross-sectionally |
| `options_greeks.py` | Black-Scholes pricing, greeks and implied volatility |
| `fx_carry.py`, `fx_signals.py` | 3-month rate differentials; sleeve scores by `model_rank`, `carry`, `ts_momentum` or `carry_momentum` |
| `sector_map.py` | `load_sector_mapping()`, from `data/reference/sector_mapping.json` |
| `cross_sectional_norm.py`, `cross_sectional_inputs.py` | Per-date percentile ranks; ranked model inputs (`phase1.features.cross_sectional_inputs`, off by default) |
| `asof_beta_labels.py` | Trailing betas with no lookahead, and the labels built on them |
| `training_splits.py` | Split walls, label purges, purged folds, yearly windows, with no torch or sklearn |
| `wide_panel.py` | The research universe's features and label, each known at that session's close |
