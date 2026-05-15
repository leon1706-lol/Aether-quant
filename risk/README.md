# risk

Owns V2 dynamic risk controls:

- volatility-adjusted position sizing
- leverage caps
- drawdown-aware sizing
- liquidity checks
- market-impact and slippage controls

This package should reuse the existing conservative risk-control behavior and extend it gradually.

Current V2-7 behavior:

- classifies rolling volatility into low, normal and high regimes
- scales target position weight toward a target daily volatility
- reduces exposure in high-volatility regimes
- allows controlled expansion in low-volatility regimes
- emits leverage/sizing telemetry for the future HTML volatility dashboard
