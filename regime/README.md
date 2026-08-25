# regime

Owns market-regime detection:

- bullish / bearish / sideways state
- high / low volatility state
- risk-on / risk-off state
- later LLM regime-vector adapters

The implementation is quantitative and offline-friendly.

Current behavior:

- detects trend state from 5-day and 20-day momentum
- classifies volatility from rolling daily volatility
- combines trend, volatility, drawdown and correlation into `risk_on`, `risk_neutral` or `risk_off` — `average_correlation` is genuinely live: `main.py` passes `topology_by_symbol[symbol]["correlation_strength"]` (the asset's real mean peer correlation within its topology cluster, computed once per bar before the per-symbol loop)
- emits a `primary_regime` label for MoE expert routing
- keeps the interface pure and testable so Lean runtime, training and future LLM adapters can reuse it

## Genuine model input feature

Regime is not just a downstream consumer of the model's own
prediction — it is also a genuine *input* the model itself sees, alongside
liquidity and topology (`liquidity/README.md`, `topology/README.md`).

- `train.py::add_regime_features()` calls `build_market_regime_vector()`
  row-wise on each historical row's own already-engineered momentum/
  volatility columns (`portfolio_drawdown=0.0` — no live portfolio
  state exists at dataset-build time). `average_correlation` reads each row's
  own real `topology_correlation_strength` (the asset's mean pairwise
  correlation within its topology cluster on that date) instead of a
  constant — `add_regime_features()` runs *after* `build_topology_features_by_date()`
  in `train.py::build_feature_dataset()`'s pipeline, and
  `train_gating.py::build_gating_training_rows()` applies the identical fix.
  This makes `classify_risk_regime()`'s "correlated crash → risk_off" rule
  reachable in offline training (see `development/Problems.md` #71 for the
  measured effect). Adds 9 one-hot columns
  (`regime_trend_bullish/bearish/sideways`,
  `regime_volatility_low/normal/high`, `regime_risk_on/off/neutral`,
  unscaled model inputs, same treatment as asset-context one-hots) plus 3
  continuous columns — `regime_signal_confidence`/`regime_signal_trend_score`/
  `regime_signal_risk_score` (StandardScaler-scaled, part of
  `phase1.features.input_set`).
- **Named `regime_signal_*`, not `regime_*`** — deliberately:
  `experts/expert_datasets.py::annotate_dataset_with_regimes()` already
  writes `regime_confidence`/`regime_trend_score`/`regime_risk_score`
  columns (a separate regime-annotation pass used only for
  expert dataset *filtering*); the prefix avoids a real naming collision.
- `main.py::_build_model_input()` computes `regime_payload` *before*
  running any model — the same regime one-hot/
  confidence/trend_score/risk_score values feed the model as input AND
  get reused (not recomputed) for gating/analyzer/dashboard, so what the
  model saw and what the rest of the system sees are always identical.
