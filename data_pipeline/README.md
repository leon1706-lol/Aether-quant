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

## Ad-hoc ticker fetch (`aq fetch`)

`fetch.py` is a narrower sibling to `yfinance_backfill.py` above, with a
different scope and a deliberately different `config.json` policy:

|  | `yfinance_backfill.py` | `fetch.py` (backs `aq fetch`) |
|---|---|---|
| Scope | Fills gaps in **already-configured** assets | Fetches **any** ticker, including ones with no `config.json` entry at all |
| Date range | Auto-detected gap vs. the asset's `"backfill"` block | Explicit `--start`/`--end` |
| `config.json` | **Never** edited — only prints suggested values | **Writes** a new asset block on `--apply`, for a ticker that isn't already configured |

The differing `config.json` policy is deliberate, not an inconsistency:
`yfinance_backfill.py`'s rule exists to stop it from silently widening an
*existing*, already-trained asset's date range without a human decision.
`fetch.py` exists specifically to *add a brand-new ticker* to the universe
on purpose — auto-writing `config.json` there is the intended effect, not
an accidental side effect. If a ticker fetched via `aq fetch` already has a
`config.json` entry, `fetch.py` leaves it untouched and points at
`yfinance_backfill.py` instead, since extending an existing asset's range
is that script's job, not this one's.

Reuses `yfinance_backfill.py`'s pure functions (`fetch_yahoo_ohlcv`,
`scale_for_lean`, `write_lean_zip`) unchanged — no duplicated logic. Same
dry-run-by-default/`--apply` safety convention. Never runs `train.py`
itself; see the root [`README.md`](../README.md#cli-reference) for the
full `aq fetch` usage.

### Two data-provenance contracts, by design (`aq fetch` tickers are pre-adjusted)

Every ticker fetched via `fetch_adhoc_asset()` (the bond ETF sleeve added in
Phase 1 of the 5/10 -> 9/10 roadmap is the first real-universe example) goes
through `fetch_yahoo_ohlcv()`'s `auto_adjust=True` — Yahoo applies its own
split/dividend adjustment **before** the data ever reaches a Lean zip. This
is a second, deliberate data-provenance contract living alongside the
original one: the original ~15 equities (AAPL, SPY, ...) use **raw** Lean
prices, adjusted separately at train time via a checked-in
`data/equity/usa/factor_files/<ticker>.csv`
(`train.py::apply_split_adjustments()`/`load_factor_file()`). An
`aq fetch`-added ticker deliberately has **no** factor file — adding one
would double-adjust already-adjusted prices — and `load_factor_file()`'s
existing "return `None` when missing" behavior is the correct, intended
no-op for this path, not an accidental gap (see
`tests/test_train_pipeline.py::test_apply_split_adjustments_noop_is_the_intended_contract_for_aq_fetch_tickers`).
This matters more for bond ETFs than most equities, since they distribute
income frequently (often monthly) — an un-adjusted bond ETF price series
would show a fake "return" on every distribution date.

`fetch_adhoc_asset()` also does **not** write a Lean
`data/equity/usa/map_files/<ticker>.csv` — that file is Lean's own
local-disk security-resolution convention (a two-row identity map,
`<start_date>,<ticker>,Q` / `20501231,<ticker>,Q`, mirroring e.g.
`aapl.csv`) and every currently-active equity ticker in this universe
already has one (bundled with QuantConnect's sample data, since no prior
`aq fetch`-added ticker had ever been wired into an active universe before
Phase 1). Since this repo's Lean backtests are run manually by the user
(see the Runbook), rather than block on an automated `lean backtest` check
this repo doesn't currently have Docker access to run, map files were
created proactively for the bond ETF sleeve, following the exact identity
format above — any future `aq fetch`-added ticker destined for the real
universe should get one the same way until/unless a real Lean run confirms
it's unnecessary.

