# API reference

`aether_quant` is a facade: each module re-exports the functions the trading system itself uses. Its public surface is pinned in `tests/data/aether_quant_api.json`, and every export is documented and fully annotated (`tests/test_public_docstrings.py`, `scripts/type_completeness.py`).

**By job** (start here):

| Module | What |
|---|---|
| [`aether_quant.signals`](signals.md) | forward targets, the IC report, quantiles, IC decay, factor spanning, purged folds |
| [`aether_quant.sizing`](sizing.md) | Kelly, volatility targeting, the live path's bounded sizing |
| [`aether_quant.neutrality`](neutrality.md) | dollar, sector, beta and factor neutrality |
| [`aether_quant.costs`](costs.md) | composable cost models and the order path's net-edge gate |
| [`aether_quant.backtest`](backtest.md) | `backtest()`, the project's simulators, Lean-exact statistics |
| [`aether_quant.overfitting`](overfitting.md) | PBO, PSR, deflated and haircut Sharpe, minimum track record, placebos |
| [`aether_quant.samples`](samples.md), [`aether_quant.hello`](hello.md) | the bundled sample, and `aq hello` as a call |

**By subsystem**: `risk`, `portfolio`, `execution`, `evaluation`, `research`, `cycle`, `features`, `training`, `data`, `audit`, `regime`, `topology`, `moe`, `liquidity`, `analyzer`, `performance`, `retraining`, `notifications`, `monitoring`, `experience`, `experts`, `inference`, `io` and `formal`, listed in the navigation.
