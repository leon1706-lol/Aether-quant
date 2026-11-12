# Neutrality

A dollar-neutral book can still carry a market bet when its names have different betas. The toolkit removes each exposure separately:

```python
import pandas as pd
from aether_quant import neutrality

raw = {"AAA": 0.3, "BBB": 0.3, "CCC": -0.3, "DDD": -0.3}
book, steps = neutrality.apply_book_neutrality(
    raw, sector_by_symbol={"AAA": "tech", "BBB": "energy", "CCC": "tech", "DDD": "energy"},
    dollar_neutral=True, sector_neutral=True, gross_exposure_cap=1.0, max_weight_per_name=0.2, sector_max_net_weight=0.05,
)
betas = {"AAA": 1.4, "BBB": 0.8, "CCC": 1.0, "DDD": 0.9}
hedged = neutrality.beta_neutralize(book, betas)                 # the smallest change that zeroes net beta
print(steps["steps_applied"], round(neutrality.net_beta(hedged, betas), 12))

exposures = pd.DataFrame({"size": [1.0, -0.5, 0.2, 0.3], "value": [0.1, 0.4, -0.2, -0.3]}, index=list(raw))
pure = neutrality.factor_neutralize(pd.Series(raw), exposures)   # zero exposure to every listed factor
```

| Function | Removes |
|---|---|
| `apply_book_neutrality` | dollar and sector exposure, per-name and sector caps, gross cap (proved shrink-only and sign-preserving in Lean 4) |
| `beta_neutralize(weights, betas, hedge=None)` | net beta, by projection or through a hedge instrument |
| `factor_neutralize(weights, exposures)` | every column of `exposures`, by least squares |
| `estimate_betas(returns, market)` | OLS betas over a trailing window, NaN when too short |
| `sector_relative_scores`, `residualise_signal` | sector or factor effects from the scores, before weights exist |
