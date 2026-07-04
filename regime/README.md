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
