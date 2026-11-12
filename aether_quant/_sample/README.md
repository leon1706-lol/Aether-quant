# Sample data for `aq hello` and the notebooks

- **File:** `coinbase_daily.csv.gz`, 20995 rows, columns `date,ticker,open,close` (8 significant figures).
- **Coins:** ADAUSD, BCHUSD, BTCUSD, DOGEUSD, ETCUSD, ETHUSD, LINKUSD, LTCUSD, XLMUSD, XRPUSD, ZECUSD: the shipped book's universe.
- **Window:** 2021-06-01 to 2026-10-31, daily bars in UTC. XRP-USD trades on Coinbase only from 2023-07-13.
- **Source:** Coinbase Exchange public candles (`api.exchange.coinbase.com/products/<id>/candles`), no key. Prices are factual market data, kept here only so the demo runs offline.
- **Rebuild:** `python scripts/build_hello_sample.py` (byte-identical for the same data); `--check` verifies the digest.
- **sha256:** `4b1b3b3b006aafc2b55284d0a13decb74d390ceb8248950abaa54280bd161d54`
