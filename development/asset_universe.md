# Asset Universe

<!--fact:universe.total-->104<!--/fact--> assets, defined in `config.json`'s `phase1.universe.assets` and shared by training, validation and backtesting. The lists below are generated from that file.

| Class | Count | Tickers |
|---|---|---|
| Equities and broad ETFs | <!--fact:universe.equity-->55<!--/fact--> | <!--fact:universe.list.equity-->AAA, AAPL, ABBV, ABT, ADBE, AIG, AMZN, BA, BAC, BNO, CAT, COST, CRM, CSCO, CVX, DIS, EEM, FB, GE, GOOG, GOOGL, GS, HD, HON, IBM, INTC, IWM, JNJ, JPM, KO, MA, MCD, MRK, MSFT, NKE, NVDA, ORCL, PEP, PFE, PG, QQQ, SBUX, SPY, T, TMO, TXN, UNH, UNP, USO, V, VZ, WFC, WM, WMT, XOM<!--/fact--> |
| Bond ETFs | <!--fact:universe.bond-->22<!--/fact--> | <!--fact:universe.list.bond-->AGG, BIV, BND, BSV, BWX, EMB, GOVT, HYG, IEF, IGIB, IGSB, JNK, LQD, MBB, MUB, SHV, SHY, TIP, TLH, TLT, VCIT, VCSH<!--/fact--> |
| Crypto | <!--fact:universe.crypto-->12<!--/fact--> | <!--fact:universe.list.crypto-->ADAUSD, BCHUSD, BTCUSD, DOGEUSD, EOSUSD, ETCUSD, ETHUSD, LINKUSD, LTCUSD, XLMUSD, XRPUSD, ZECUSD<!--/fact--> |
| Forex | <!--fact:universe.forex-->15<!--/fact--> | <!--fact:universe.list.forex-->AUDJPY, AUDUSD, CADJPY, EURAUD, EURCHF, EURGBP, EURJPY, EURUSD, GBPCAD, GBPJPY, GBPUSD, NZDUSD, USDCAD, USDCHF, USDJPY<!--/fact--> |

## What each class does

- **Crypto:** the shipped book. The long-only sleeve in `ml/target_weights.csv` trades these pairs.
- **Equities:** features for the models, and the benchmark (`SPY`). `BIL` is the T-bill sweep (`phase_v2.cash_sweep`), configured apart from this list.
- **Bonds:** span the duration curve (short to long) and the credit spectrum (Treasury, investment grade, high yield, municipal, emerging, international), so the yield-curve and credit features mean something. They trade through Lean's equity path.
- **Forex:** feature class only. `phase_v2.forex_risk.enabled` is false by rule R-FX6 (#181).
- **Every asset is trading-eligible** by the `asset_quality` rule, which `train.py` re-evaluates on each dataset build (`ml/dataset_manifest.json`).

## Known issues

- **EOSUSD:** Coinbase has delisted it, so the sleeve can't hold it there. It leaves the universe at the broker rebuild (#311).
- **Survivorship:** the crypto list is today's survivors, chosen with hindsight (#301).

## Research-only universes

Never traded, and never in `config.json`:

- **`data_wide/`:** S&P 500 point-in-time members (`wide_manifest.json`).
- **`data_crypto_wide/`:** Binance coins, including delisted ones (`crypto_wide_manifest.json`).

`evaluation/research_cells.py` splits both by name and time, and held-out cells stay unread until a frozen candidate reaches them.
