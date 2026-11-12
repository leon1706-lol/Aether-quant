# Safety

The live path's safety functions are pure, tested, and the most critical of them are proved in Lean 4 and checked against their models on thousands of generated cases (`aq prove`, `tests/test_formal_differential_*`).

```python
from aether_quant import execution, risk

print(execution.resolve_order_permission("observation", True, True, True))   # observation never trades
print(execution.resolve_order_permission("paper", True, True, False))        # a tripped lock stops paper and live
decision = risk.evaluate_kill_switch({"recent_bar_returns": [-0.01] * 60, "drawdown_velocity_pct_per_bar": 0.0}, {"enabled": True, "evaluation_bars": 60, "min_rolling_sharpe": 0.0})
print(decision.tripped, decision.triggers)
report = execution.reconcile_positions({"BTCUSD": 0.10}, {"BTCUSD": 0.18}, weight_tolerance=0.01, value_tolerance_usd=50.0, portfolio_value=1e5, max_tolerated_drift=0.05)
print(report.breach, report.max_abs_weight_drift)
```

| Function | Guarantee |
|---|---|
| `resolve_order_permission` | observation and unknown modes never trade; a risk lock blocks paper and live (`OrderGate.lean`) |
| `evaluate_kill_switch` | a disabled switch never trips; it trips exactly when a trigger fires (`KillSwitch.lean`) |
| `reconcile_positions` | every name is matched, drifted, orphaned or missing, never two at once (`Reconciliation.lean`) |
| `cap_target_weight`, `assess_drawdown_lock` | a weight never exceeds its cap or flips; the drawdown lock is monotone (`RiskControls.lean`) |
| `apply_risk_overrides` | an account's overrides only tighten the config (`AccountOverrides.lean`) |
| `monitoring.auth.authorize` | never above a user's role or outside their accounts (`Authorize.lean`) |
| `verify_chain` | a tampered payload or a deleted row is detected (`HashChain.lean`) |
