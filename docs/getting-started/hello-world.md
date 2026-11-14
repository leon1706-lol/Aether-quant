# Hello world

```bash
aq hello            # download fresh bars (Coinbase public candles, no key), about a minute
aq hello --offline  # the sample in the wheel, the same numbers everywhere
aq hello --html report.html --json report.json
```

`aq hello` runs four steps:

1. **Data.** It downloads 11 coins' daily bars, one coin at a time, and caches them under `~/.cache/aether-quant/candles`. Only closed bars are used. Any failure falls back to the bundled sample, with a notice.
2. **The rule.** It runs the project's shipped book, `t3_crypto_trend_blend_x_eos`: long a coin while its trailing return over 20, 60 and 120 sessions is positive (one vote each), vol-scaled and capped, rebalanced every 5 sessions. A decision on session D reads only the bars dated before D.
3. **The backtest.** It runs `aether_quant.backtest.backtest` with the live path's costs: the Coinbase taker fee, 10 bps of slippage and a 0.2% deadband.
4. **The report.** It prints CAGR, volatility, Sharpe, Sortino, drawdown, exposure, turnover and costs, against BTC buy and hold and an equal-weight book. Then come the overfitting checks:
    - the probabilistic Sharpe
    - PBO by CSCV over 8 lookback variants
    - the deflated Sharpe on that grid
    - the Sharpe left after a BHY haircut for the project's <!--fact:research.trials-->217<!--/fact--> trials
    - the minimum track record

From Python:

```python
from aether_quant import hello

report = hello.run(offline=True)
print(hello.render_text(report))
report.strategy.sharpe, report.pbo
```

The shipped book is small: about <!--fact:hello.gross_pct-->11<!--/fact-->% gross on average, so read its Sharpe (<!--fact:hello.sharpe-->0.43<!--/fact--> from <!--fact:hello.start-->2022-01-01<!--/fact--> on the sample) and drawdown, not its total return. Its haircut Sharpe at <!--fact:research.trials-->217<!--/fact--> trials is <!--fact:hello.haircut_sharpe-->0.00<!--/fact-->. That is the honest summary of where the project stands.
