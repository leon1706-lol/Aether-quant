# Overfitting

Every backtest is the winner of some search. These tests ask how much of its result survives that search.

```python
import numpy as np
from aether_quant import overfitting

rng = np.random.default_rng(0)
variants = rng.normal(0.0003, 0.01, size=(1600, 16))         # 16 configurations, no real edge
print("PBO", overfitting.pbo(variants, blocks=8)["pbo"])      # near 0.5 or above: picking the best is no better than chance

best = variants[:, variants.mean(axis=0).argmax()]
trials = [float(v.mean() / v.std() * np.sqrt(252)) for v in variants.T]
print("DSR", overfitting.deflated_sharpe_ratio(best, trials)["value"])
print("min track record (years)", overfitting.minimum_track_record_length(best) / 252)
print(overfitting.haircut_sharpe(sharpe=1.0, n_obs=252 * 5, num_trials=50, method="bhy"))
```

| Test | Question |
|---|---|
| `pbo` / `probability_of_backtest_overfitting` | CSCV: how often does the in-sample best land below the median out of sample? |
| `probabilistic_sharpe_ratio` | how likely the true Sharpe beats a benchmark, given skew and kurtosis |
| `deflated_sharpe_ratio`, `deflated_sharpe_from_inputs` | the same, against the best Sharpe expected from N trials |
| `minimum_track_record_length` | how many observations the Sharpe needs to beat a target at a confidence (Bailey & López de Prado 2012) |
| `haircut_sharpe` | the Sharpe left after Bonferroni, Holm or BHY for N trials (Harvey & Liu 2015) |
| `placebo_p_value` | the share of time-shifted placebos at least as good |
| `audit_leakage` | features that read the future |
| `selection_gate` | the pre-registered bar a research round's trials must clear |

The project keeps a once-only holdout ledger. A research round writes each holdout read before the read happens, and refuses a second read of the same cell (proved in Lean 4, `HoldoutOnce.lean`). See the [overfitting tutorial](../tutorials/03_overfitting_tests.ipynb).
