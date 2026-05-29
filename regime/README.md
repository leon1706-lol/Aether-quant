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
- combines trend, volatility, drawdown and optional correlation into `risk_on`, `risk_neutral` or `risk_off`
- emits a `primary_regime` label for later MoE expert routing
- keeps the interface pure and testable so Lean runtime, training and future LLM adapters can reuse it
