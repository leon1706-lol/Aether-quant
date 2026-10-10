# data

Lean's local market-data folder — flat files on disk, one directory tree per
asset type/market, matching Lean's own `securityType/marketName/resolution/`
layout. This entire folder is gitignored (`.gitignore`'s `data/**` block)
except `.keep`/`.gitkeep` placeholders and the small hand-authored files
under `data/reference/`, since real market data is too large for a public
repo — see `development/Problems.md` #10.

Populated subfolders actually used by this project:

- `equity/usa/` — US equities (minute/daily bars), plus Lean's own
  `factor_files/<ticker>.csv` (splits/dividends adjustment) and
  `map_files/<ticker>.csv` (ticker-to-permtick history), both consumed
  directly by Lean's data reader, not by this project's own code.
- `forex/`, `future/`, `option/`, `cryptofuture/`, `crypto/`, `index/`,
  `indexoption/`, `cfd/` — the remaining asset classes this project trades
  (Forex, futures, options, crypto, index/index-options), each following
  Lean's standard per-market subfolder convention.
- `reference/` — small, hand-authored reference/config JSON and CSV files
  that this codebase treats as checked-in source, not bulk market data
  (explicit `.gitignore` exception; see `tests/test_futures_risk.py`,
  `tests/test_ib_backfill.py`, `tests/test_train_cross_sectional_features.py`).
  `reference/fred_series/*.csv` holds `data_pipeline/fred_backfill.py`'s
  cached FRED macro series.
- `market-hours/`, `symbol-properties/` — Lean's own exchange-calendar and
  contract-spec databases, required by the engine regardless of which
  asset classes are active.

`data_pipeline/README.md` documents how this folder actually gets populated
(Yahoo Finance thin-series backfill, FRED macro backfill, IB historical
backfill) and which files each downstream module reads from it.
