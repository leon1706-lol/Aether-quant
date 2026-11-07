# regime

Quantitative market-regime detection: pure, testable, and used by Lean and training alike.

- **Trend:** bullish, bearish or sideways, from 5- and 20-day momentum.
- **Volatility:** low, normal or high, from rolling daily volatility.
- **Risk:** `risk_on`, `risk_neutral` or `risk_off`, combining trend, volatility, drawdown and the asset's cluster correlation.
- **`primary_regime`:** the label behind expert routing.

## A model input, not just a label

- **Dataset:** `train.py::add_regime_features()` builds 9 one-hot columns (`regime_trend_*`, `regime_volatility_*`, `regime_risk_*`) and 3 scaled ones (`regime_signal_confidence`, `_trend_score`, `_risk_score`), after topology, so a correlated crash can reach `risk_off`.
- **Naming:** `regime_signal_*` avoids colliding with the expert datasets' `regime_*` annotations.
- **Runtime:** `main.py::_build_model_input()` computes the regime before any model, so the model and the rest of the system see one value.
- **Drawdown-free:** `build_model_input_regime_vector()` pins portfolio drawdown at 0.0, because a dataset has no account state. Parity needs the same at runtime (#173).
