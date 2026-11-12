# Sizing

Three questions, three tools:

- **How big is the whole book?** Volatility targeting.
- **How much would the growth-optimal bet be?** Kelly. Estimation error makes full Kelly far too large, so the default is half Kelly with a gross cap.
- **How big is one position on the live path?** `build_dynamic_position_sizing`: the base weight scaled by confidence, volatility, topology, rank, RL and cost multipliers. It never exceeds its cap and never flips the trade's sign; both properties are proved in Lean 4 (`formal/AetherFormal/PositionSizing.lean`).

```python
import numpy as np
import pandas as pd
from aether_quant import sizing

cov = pd.DataFrame([[4e-4, 1e-4], [1e-4, 9e-4]], index=["BTCUSD", "ETHUSD"], columns=["BTCUSD", "ETHUSD"])
book = sizing.volatility_target_weights({"BTCUSD": 0.6, "ETHUSD": 0.4}, cov, target_annual_vol=0.15, max_leverage=1.0, annualization=365)

half_kelly = sizing.kelly_weights(np.array([0.001, 0.0008]), cov.to_numpy(), fraction=0.5, gross_cap=1.0)
single = sizing.kelly_fraction(mean=0.0005, variance=0.0004)        # 0.5 * mean / variance, capped at 1

decision = sizing.build_dynamic_position_sizing(0.10, 0.8, 0.02, 0.10)
print(book, half_kelly, single, decision.target_weight)
```

Every function sizes a non-finite input to zero and never to a guess. The hypothesis tests check that gross exposure never exceeds its cap, for any input.
