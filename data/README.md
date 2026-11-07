# data

Lean's local market-data folder, in Lean's `securityType/market/resolution/` layout. Gitignored except for `reference/` and placeholders, because market data is too large for a public repo (#10).

- **`equity/usa/`:** bars, plus Lean's `factor_files/` and `map_files/`.
- **`crypto/`, `forex/`, `future/`, `option/`, `index/`:** the other asset classes, per market.
- **`reference/`:** small, tracked files treated as source, such as futures margin specs and dividend schedules. `reference/fred_series/` caches FRED series.
- **`alternative/interest-rate/usa/`:** the risk-free file behind Lean's Sharpe, refreshed by `scripts/refresh_lean_interest_rate.py`.
- **`market-hours/`, `symbol-properties/`:** Lean's own calendars and contract specs.

How it gets populated: [`data_pipeline/README.md`](../data_pipeline/README.md). Local and Codespace copies must be file-for-file identical (AGENTS.md rule 12).
