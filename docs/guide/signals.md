# Signals

A signal is a score per name and date, known at that date's close. To evaluate one, build forward targets from prices, then read the daily rank IC: its mean, a HAC t-statistic and a block-bootstrap interval. A mean IC alone hides how noisy it is.

```python
import numpy as np
import pandas as pd
from aether_quant import samples, signals

closes = samples.load_sample_prices().loc["2023-07-13":]
momentum = closes / closes.shift(20) - 1

targets = signals.forward_rank_targets(closes, horizons=(5, 20))
scores = momentum.rename_axis(index="date", columns="ticker").reset_index().melt(id_vars="date", var_name="ticker", value_name="score")
table = targets.merge(scores, on=["date", "ticker"]).dropna(subset=["score", "target_rank_20d"])
report = signals.evaluate_signal(table, score_column="score", splits=("validation",), min_names_per_date=8, bootstrap_draws=200)
h20 = report["splits"]["validation"]["h20"]
print(f"IC {h20['mean_ic']:.3f}, HAC t {h20['hac_t']:.2f}, 95% CI {h20['ci95']}")

decay = signals.ic_decay(momentum, closes, horizons=(1, 5, 20))
quantiles = signals.quantile_returns(momentum, signals.forward_returns(closes, 5), n_quantiles=3)
```

| Function | Answers |
|---|---|
| `forward_returns(prices, h)` | the return from D's close to D+h's close |
| `forward_rank_targets(prices, horizons)` | the long table `evaluate_signal` reads |
| `evaluate_signal(frame, ...)` | IC, HAC t, bootstrap CI and decay, per split and horizon |
| `quantile_returns(scores, fwd)` | the mean forward return of each score quantile |
| `ic_decay(scores, prices, horizons)` | the mean IC at each horizon |
| `factor_spanning(signal_returns, factors)` | is the signal more than known factors (alpha and its HAC t)? |
| `purged_embargoed_folds(dates, ...)` | cross-validation folds that purge overlapping labels |

Before trusting a signal, run the leakage audit (`aether_quant.overfitting.audit_leakage`). It flags features whose single-feature IC is implausibly high, which usually means future data leaked in. See the [signal evaluation tutorial](../tutorials/01_signal_evaluation.ipynb).
