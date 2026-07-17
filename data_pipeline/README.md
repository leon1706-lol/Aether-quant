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
never in `requirements.txt` (the one requirements file the consolidated
`aether-quant-engine` Docker image installs).

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

## Real Treasury yield/credit-spread backfill (`fred_backfill.py`)

A third sibling, alongside `yfinance_backfill.py`/`fetch.py` above, backing
`features/bond_features.py`'s real-data yield-curve/credit-spread features
(distinct from `features/macro_features.py`'s price-momentum proxies).
Fetches FRED's public graph CSV endpoint — **no API key required**, stdlib
`urllib.request` only (no new runtime dependency, unlike
`yfinance_backfill.py`'s deferred `import yfinance`). Same
dry-run-by-default/`--apply` safety convention; writes a local cache
(`data/reference/fred_series/*.csv`, never committed as real market data
the way Lean zips are) rather than editing `config.json` at all — nothing
in this codebase's asset universe schema needs to change for bond features
to exist, since they're cross-asset macro signals broadcast to every asset,
not a new configured ticker.

`load_cached_fred_series()` is the read-side: loaded once at
`train.py`/`main.py` startup (never fetched live mid-backtest — Lean
backtests are date-bounded), `{}` if the cache was never populated (fresh
clone), in which case every bond feature neutral-defaults to `0.0` — the
same "missing reference -> 0.0" convention `macro_features.py` already
established, never a crash.

Usage: `python -m data_pipeline.fred_backfill [--series treasury_10yr ...] [--apply]`.

## Interactive Brokers historical backfill (`ib_backfill.py`) — futures/options only

The futures/options sibling to `fetch.py`, but a fundamentally different
data source: `ib_insync` (a **dev-only** dependency,
`requirements/requirements-dev.txt`, never in `requirements.txt` — this
module is importable with `ib_insync` absent as long as IB stays
disabled, same deferred-import convention as `yfinance_backfill.py`).

This is deliberately a **separate integration** from Lean's own native
live/paper Interactive Brokers brokerage (`lean.json`'s
`ib-account`/`ib-user-name`/`ib-password`/`ib-trading-mode` fields, and
`environments.live-interactive` — untouched by this module, see root
`README.md`'s `aq ib` section for the full explanation of why there are
two IB integrations, not one). Lean's `environments.backtesting` is
hardcoded to `FileSystemDataFeed`/`SubscriptionDataReaderHistoryProvider`
— it never talks to IB regardless of `lean.json`'s contents — so
historical futures/options bars still need this separate, offline
data-prep step to land as local Lean-format zip files before any backtest
can use them.

- **"IB ready" requires both**: `config.json`'s `phase_v2.ib.enabled ==
  true` (Aether's own app-level feature flag) AND `lean.json`'s
  `ib-account`/`ib-user-name` non-empty (Lean's own credential fields,
  read-only from this module's perspective). `phase_v2.ib.host`/`port`/
  `client_id` are TWS/IB Gateway **socket API connection settings only**
  (not credentials — your Gateway session already handles login), a
  second, independent API client alongside whatever Lean's own brokerage
  uses when live-deployed (standard IB API pattern — Gateway supports
  multiple simultaneous API clients).
- Every public function raises `IBNotConfiguredError` — never a raw
  traceback — when IB isn't ready, so `aq fetch futures`/`aq fetch
  options` fail cleanly with a message pointing at `aq ib status`.
- Plugs into `fetch.py::ASSET_CLASS_CONFIG`'s `"futures"`/`"options"`
  entries the same way `yfinance_backfill.py`'s functions plug into
  `"crypto"`/`"stock"` — `aq_cli.py::cmd_fetch()` builds a closure binding
  the connected IB client + contract spec/expiry/strike/right before
  calling the same `fetch_adhoc_asset()` every asset class shares.

Usage: `aq fetch futures --ticker ES --start ... --end ... --expiry ... [--apply]`,
`aq fetch options --ticker SPY --start ... --end ... --expiry ... --strike ... --right call [--apply]`
— see root `README.md`'s CLI Reference.

### Building a real training-time derivatives dataset (manual, per-contract)

`train.py::build_derivatives_macro_features_by_date()` computes real
futures term structure / options put-call-ratio / IV-skew features from
whatever future/option assets are configured in `config.json` — but IB's
historical API is per-contract and rate-limited, so there is no single
bulk-fetch command for this. Building a useful training window means
repeating `aq fetch futures`/`aq fetch options` once per contract:

- **Futures term structure** needs at least two same-root contracts tagged
  with the same `--family-ticker` and *different* `--contract-month`
  (`YYYYMM`), e.g.:
  ```text
  aq fetch futures --ticker ES_FRONT --family-ticker ES --contract-month 202603 --start ... --end ... --expiry ... --apply
  aq fetch futures --ticker ES_NEXT  --family-ticker ES --contract-month 202606 --start ... --end ... --expiry ... --apply
  ```
  Without `--contract-month`, `aq fetch futures` fetches Lean's default
  *continuous* contract — fine for price/return features, but a single
  continuous series can't produce a term-structure slope; you need two
  distinct dated contracts for that.
- **Options sentiment (put/call ratio, IV skew)** needs option assets
  tagged with `--family-ticker <underlying>` (matching
  `phase1.features.derivatives_reference_tickers.options_sentiment` in
  `config.json`, default `"SPY"`) plus their own `--strike`/`--expiry`/
  `--right`, e.g.:
  ```text
  aq fetch options --ticker SPY_500C --family-ticker SPY --strike 500 --expiry 2026-08-21 --right call --start ... --end ... --apply
  aq fetch options --ticker SPY_490P --family-ticker SPY --strike 490 --expiry 2026-08-21 --right put  --start ... --end ... --apply
  ```
- Any family/underlying with too few tagged contracts (or missing
  `strike`/`expiry`/`right` metadata) resolves to the neutral default
  (0.0) for that feature, silently — never a crash. This is the honest
  "no data configured" case, not a bug; run `aq assets status` to see
  what's currently configured.
- After fetching, run `python train.py --dataset-only` (then `python
  train.py` when ready) to actually train on the new data — `aq fetch`
  never trains anything itself.

