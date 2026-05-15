# monitoring

Owns V2 monitoring outputs:

- HTML live volatility dashboard feeds
- Grafana exports
- risk and leverage telemetry
- later Telegram alert adapter

The first target is a live HTML volatility dashboard showing position size and leverage decisions.

Current V2-9 behavior:

- `volatility_dashboard.html` reads `visualization/state.json`
- auto-refreshes every 5 seconds
- displays annualized volatility, volatility regime, target position weight and leverage factor per asset
- works with Lean backtests and observation mode before broker API keys are available
