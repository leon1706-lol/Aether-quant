# data_pipeline

Owns the V2 Lean-data pipeline contract.

The current rule stays simple and important: training and backtesting use the local Lean `data/` folder. This package describes that contract for later V2 modules such as MoE experts, regime detection, topology modeling, dynamic risk and the volatility dashboard.

It does not replace `train.py`; it wraps and documents the existing dataset pipeline so later modules can depend on a stable manifest.

## Yahoo Finance historical data backfill (V2-19.5)

`yfinance_backfill.py` is a deliberate, narrow exception to the rule above:
it is the first thing in this package that reaches outside the local Lean
`data/` folder, to fill gaps in thin series (initially `ETHUSD`/`LTCUSD`,
which have only a few scattered days of real Coinbase minute data — see
`train.py::ensure_derived_crypto_daily_series()` and this repo's Changelog).
It is a **manual, offline maintenance script** — never invoked from
`train.py`, `main.py`, or any Docker worker; no network calls happen during
training or a backtest.

- Per-asset opt-in via a `"backfill"` sub-block in `config.json`'s
  `phase1.universe.assets[]` entries (`source`, `symbol`, `backfill_from`,
  `backfill_to`). Assets without it are skipped entirely.
- Fetched Yahoo rows are converted to the exact Lean zip format
  (`train.py::ensure_derived_crypto_daily_series()`'s row/member-name
  convention) and merged into the existing zip — **existing real Lean rows
  always win on any overlapping date**; Yahoo data only fills genuine gaps.
- **Dry run by default.** Writing zip files requires an explicit `--apply`
  flag. Regardless of `--apply`, this script **never** edits `config.json`'s
  `available_from`/`available_to` — it only prints the suggested new values,
  because `train.py::build_asset_quality()` only counts rows inside those
  configured windows, so a human must deliberately widen them for the extra
  history to actually affect training/backtesting.

Usage: `python -m data_pipeline.yfinance_backfill [--tickers ETHUSD LTCUSD] [--apply]`.
`yfinance` is a dev-only dependency (`requirements/requirements-dev.txt`),
never in `requirements.txt`/`requirements-runtime.txt`.

