# Backtesting

`backtest()` runs any weights over any prices, with costs, in unit accounting.

- A decision row dated D sizes each order at D's close.
- With `fill="next_open"` the order fills at the next row's open; with `fill="close"` it fills at D's close.
- Between decisions the units are held and the weights drift.

That is the convention of the project's own target-weights simulator. A test holds the two to the same daily returns, within share rounding (about 5e-9).

```python
import pandas as pd
from aether_quant import backtest, costs, samples

closes = samples.load_sample_prices().loc["2024-01-01":]
opens = samples.load_sample_prices("open").loc[closes.index]
trend = (closes / closes.shift(60) - 1 > 0).astype(float)
weights = trend.div(trend.sum(axis=1).clip(lower=1), axis=0).where(pd.Series(range(len(trend)), index=trend.index) % 7 == 0)

result = backtest.backtest(weights, closes, opens=opens, cost_model=costs.coinbase_model(), periods_per_year=365, min_weight_change=0.002)
print(result.report(title="60-day trend, weekly"))
stats = result.stats()
frame = result.to_frame()
```

| | |
|---|---|
| `weights` | dates x tickers; a row of NaN is "no decision", a NaN cell is 0 |
| `rebalance_every=k` | acts on every k-th decision row |
| `min_weight_change` | the live path's deadband; a zero target always closes the name |
| `adv_usd`, `daily_vol` | inputs for a cost model that needs them (square-root impact) |
| `.stats()` | CAGR, volatility, Sharpe, Sortino and PSR by Lean's formulas, drawdown, Calmar, turnover, cost drag |

For the project's own books, `simulate_target_weights` and `simulate_rank_book` model more of the live path: financing, the T-bill sweep, lot sizes, the drawdown lock and the rank book's slots. `lean_statistics` reproduces the statistics Lean prints.
