# analyzer

The final per-asset decision on the model book's path. `market_analyzer.py` combines gating, regime, topology, liquidity and risk-lock state into one action: `observe`, `simulate`, `trade`, `reduce_risk` or `retrain_candidate`.

- **Pure and explainable:** deterministic, with a `reasons` list.
- **Only `trade` orders:** `main.py` calls `_apply_signal` only then, and all five actions reach the dashboard.
- **Not on the shipped path:** target weights skip it.

## Decision order

1. **Hard safety (priorities 0-6):** exit preservation, trade lock, `risk_off`, elevated or isolated topology, thin liquidity, confidence. These are gates, never averaged. Every signal passes them, a book short included. `phase_v2.topology.elevated_veto_applies_to_book_members` (default true) can let a book member skip the elevated-volatility veto.
2. **Net-edge cost gate (6.5):** an entry whose expected edge doesn't clear its round-trip cost becomes `simulate`. It never blocks an exit, and an uncalibrated cost model is a no-op.
3. **Trade gate and simulate-or-observe (7-8):** on raw confidence, or on `compute_signal_quality_score()` (model 0.45, regime 0.20, topology 0.20, liquidity 0.15) when `phase_v2.market_analyzer.use_composite_signal_score` is true. The score is always computed for the dashboard.

## Deliberately deterministic

- **The learned topology overlay** only resizes approved trades (`risk/position_sizing.py`) and informs retrain triggers.
- **`retrain_candidate`** here is a stateless fallback; the real signal is `performance/triggers.py`.
- **Predicted magnitude and volatility** are informational here. They reach sizing only through `phase_v2.dynamic_risk.use_predicted_volatility`.
