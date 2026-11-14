# Aether Quant

A research toolkit for systematic trading, and the self-adapting trading system built on it.

The **`aether_quant` library** is pure Python on numpy and pandas. It offers:

- signal evaluation with HAC t-statistics and bootstrap intervals
- position sizing, from volatility targeting and fractional Kelly to the live path's bounded sizing
- dollar, sector, beta and factor neutrality
- composable cost models with the fees a live path pays
- a cost-aware `backtest()`
- the overfitting tests: PBO, the probabilistic and deflated Sharpe, the minimum track record and the haircut Sharpe
- pre-registered research rounds and generations that hand over capital by evidence

Every function in it is one the trading system itself uses, so a research result and a live decision come from the same code.

```bash
pip install aether-quant
aq hello
```

That downloads a few years of daily bars for 11 coins from Coinbase's public candles, runs the project's shipped rule through a cost-aware backtest, and prints a report with benchmarks and overfitting checks. It needs no key, no Docker and no Lean. Start with [Hello world](getting-started/hello-world.md), then the [tutorials](tutorials/00_hello_world.ipynb).

!!! warning "No verified edge"
    The shipped book is a long-only crypto trend sleeve, on paper only. No pre-registered test has found a verified edge: <!--fact:research.trials-->217<!--/fact--> trials so far, no survivor, and the holdouts unread. The toolkit is the point. It is how this project judges itself, and how you can judge your own signals.

| | |
|---|---|
| **Install** | [Getting started](getting-started/install.md): the light install, the extras, and the full system |
| **Learn** | [Tutorials](tutorials/00_hello_world.ipynb) (they open in Colab) and the [guide](guide/signals.md) |
| **Look up** | The [API reference](reference/index.md), generated from the code |
| **Go live** | [Paper to live](live/paper-to-live.md): the measured checklist, secrets, accounts, users and the field test |
| **License** | The library is [Apache-2.0](about/license.md); the trading system is PolyForm Noncommercial |
