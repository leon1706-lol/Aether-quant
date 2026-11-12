# Costs

A cost model answers one question: what does a trade of this size cost, in basis points? Models add up, and the presets are the fees the live path pays. A research cost and a live cost are therefore the same numbers.

```python
from aether_quant import costs

coinbase = costs.coinbase_model()                       # the taker fee plus the simulator's crypto slippage
equity = costs.ib_equity_model()                        # 1.5 bps, $1 minimum, 3 bps slippage, square-root impact
custom = costs.CompositeCostModel((costs.LinearCostModel(commission_bps=2.0, half_spread_bps=1.5), costs.SquareRootImpactModel(eta=0.8)))

print(coinbase.cost_bps(10_000.0))
print(round(custom.cost_bps(2_000_000.0, adv_usd=50_000_000.0, daily_vol=0.025), 1))
print(costs.cost_usd(equity, 25_000.0, adv_usd=1e8, daily_vol=0.015))
```

- **`LinearCostModel`:** commission plus half the spread. A minimum fee applies up to the whole notional, so a dust trade never costs infinite bps.
- **`SquareRootImpactModel`:** `eta * daily_vol * sqrt(trade / ADV)`. When ADV or volatility is unknown it returns zero, so a missing input stays visible rather than becoming a guessed cost.
- **`estimate_round_trip_cost_bps`, `build_net_edge_decision`:** the order path's net-edge gate, which trades only when the expected edge beats the round trip.

No cost model returns a negative or NaN value for any input; a hypothesis property test checks this.
