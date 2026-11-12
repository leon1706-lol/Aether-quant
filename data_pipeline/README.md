# data_pipeline

Gets data into Lean's local `data/` folder, which training and backtesting both read. It wraps `train.py`'s dataset build, not replaces it. Every fetch is a dry run without `--apply`.

## The universe's bars

| Module | Scope | `config.json` |
|---|---|---|
| `yfinance_backfill.py` (`aq backfill yfinance`) | Refreshes **configured** assets; `--quotes` derives a missing crypto quote zip | Never edited |
| `fetch.py` (`aq fetch`) | Adds **any** ticker, reusing the same writers | Writes a new asset block |

- **Two price contracts:** a zip written here is already split- and dividend-adjusted, so it needs **no** factor file; genuine QuantConnect zips (integer volume) keep theirs. `factor_file_backfill.py --audit` polices this, and `--repair-adjusted-zips` fixes double adjustment (#130).
- **`price_overrides.json`:** back-adjustments for corporate actions Yahoo misses.
- **`data_audit.py` (`aq evaluate --audit-data`):** coverage, outliers, OHLC sanity, flat runs and a SHA-256 manifest.
- **`scripts/data_append_refresh.py`:** the routine way to add new bars.

## Reference series

- **`fred_backfill.py` (`aq backfill fred`):** Treasury yields, credit spreads, VIX, financial conditions and FX 3-month rates, cached in `data/reference/fred_series/`, with no API key. httpx is imported only when a series is fetched, so the module loads on the light install. Read through `series_value_asof()`, which respects publication lag.
- **`dividend_backfill.py` (`aq backfill dividends`):** ex-dates and a projected next date, for early-assignment scoring.
- **`cftc_cot.py`:** speculators' positioning, keyed by publication date.

## Interactive Brokers: `ib_backfill.py`

Futures and options for `aq fetch futures` and `aq fetch options`. Needs a running Gateway and `phase_v2.ib` (`aq ib status`); without them it fails cleanly. IB's historical API is per-contract and rate-limited, so a training set is built by repeated runs: `--contract-month` for a term structure, and `--family-ticker` to group contracts for term-structure and skew features. Lean's backtest engine only reads local files, so bars must be backfilled before a backtest can use them.

## Research sources

Free, with no account. They write to the research roots (`data_wide/`, `data_crypto_wide/`), never `data/`.

- **`sp500_membership.py`:** point-in-time S&P 500 members.
- **`edgar_facts.py`:** first-filing fundamentals, available a session after filing; quarterly accruals, sectors from SIC. Needs `AQ_SEC_CONTACT`.
- **`filing_text.py`:** pure text handling for filings: tags stripped, words hashed to buckets (stable across runs), cosine similarity, earnings-release dates from the 8-K item list. `scripts/build_filing_signals.py` drives it and keeps hashed counts only, never filing text.
- **`sec_form345.py`:** insider trades by filing date. **`finra_short_volume.py`:** daily short ratios.
- **`binance_archive.py`:** spot klines and funding, delisted pairs included.
- **`factor_library.py`:** French's and AQR's daily factors.
- **`public_candles.py` (`aq hello`, `aether_quant.data`):** Coinbase's keyless daily candles, paged at 300 rows and cached in `~/.cache/aether-quant/candles`. It takes closed bars only, names a coin that fails, and uses urllib only, so it works on the light install (#343). `scripts/build_hello_sample.py` freezes the 185 KB sample the wheel ships.

## Helpers

- **`bar_synthesis.py`:** `midpoint_bar_from_quote_bar()`, `pad_sequence_history()` and the adaptive sell threshold, extracted from `main.py` to be testable.
- **`net_retry.py`:** a download that survives a dropped connection; only the server's own answer means a file is absent.
- **`v2_manifest.py`:** the metadata contract for the dataset pipeline.

Data parity with live is checked against live: AGENTS.md rule 12, and `aq evaluate --reconcile-features`.
