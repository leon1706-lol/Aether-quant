# regime

Owns market-regime detection:

- bullish / bearish / sideways state
- high / low volatility state
- risk-on / risk-off state
- later LLM regime-vector adapters

The first implementation should stay quantitative and offline-friendly.

Current V2-6 behavior:

- detects trend state from 5-day and 20-day momentum
- classifies volatility from rolling daily volatility
- combines trend, volatility, drawdown and correlation into `risk_on`, `risk_neutral` or `risk_off` — `average_correlation` was a dead input until this session's static/dynamic audit found `main.py` never actually passed a real value (always the `0.0` default, making the correlation-gated risk_off branch unreachable in practice); `main.py` now passes `topology_by_symbol[symbol]["correlation_strength"]` (the asset's real mean peer correlation within its topology cluster, already computed once per bar before the per-symbol loop), so this input is genuinely live
- emits a `primary_regime` label for later MoE expert routing
- keeps the interface pure and testable so Lean runtime, training and future LLM adapters can reuse it

## Genuine model input feature (Phase 1 remainder)

Regime is no longer just a downstream consumer of the model's own
prediction — it is now a genuine *input* the model itself sees, alongside
liquidity and topology (`liquidity/README.md`, `topology/README.md`).

- `train.py::add_regime_features()` calls `build_market_regime_vector()`
  row-wise on each historical row's own already-engineered momentum/
  volatility columns (`portfolio_drawdown=0.0`/`average_correlation=0.0` —
  the same honest offline simplification `train_gating.py` already
  established; no live portfolio/topology state exists at dataset-build
  time). Adds 9 one-hot columns (`regime_trend_bullish/bearish/sideways`,
  `regime_volatility_low/normal/high`, `regime_risk_on/off/neutral`,
  unscaled model inputs, same treatment as asset-context one-hots) plus 3
  continuous columns — `regime_signal_confidence`/`regime_signal_trend_score`/
  `regime_signal_risk_score` (StandardScaler-scaled, part of
  `phase1.features.input_set`).
- **Named `regime_signal_*`, not `regime_*`** — deliberately, to avoid a
  real naming collision found during development: `experts/expert_datasets.py::annotate_dataset_with_regimes()`
  already writes `regime_confidence`/`regime_trend_score`/`regime_risk_score`
  columns (a separate, pre-existing regime-annotation pass used only for
  expert dataset *filtering*, computed later in the pipeline). The
  collision was functionally harmless to model training (expert training
  reads the already-scaled columns, frozen before the collision) but a
  landmine for anyone changing `phase_v2.regime_detection.*` thresholds
  later, since only one of the two computations reads them from config.
- `main.py::_build_model_input()` computes `regime_payload` *before*
  running any model now (previously computed only after, purely for
  downstream gating/analyzer consumption) — the same regime one-hot/
  confidence/trend_score/risk_score values feed the model as input AND
  get reused (not recomputed) for gating/analyzer/dashboard, so what the
  model saw and what the rest of the system sees are always identical.
- Model input dimensionality grew from 30 to 48 as a result of this plus
  liquidity/topology's new features together — baseline, all 4 experts,
  gating and the multitask model all needed retraining. See
  `development/Changelog.md`'s "Phase 1 remainder + Phase 2" entry for
  the full writeup, including a real train/runtime parity bug found and
  fixed along the way (in `liquidity/`, not here).
