# monitoring

Owns V2 monitoring outputs:

- `api_server.py`: FastAPI JSON API serving runtime state to the `webui/` React app
- Grafana exports
- risk and leverage telemetry
- later Telegram alert adapter

Current behavior:

- `api_server.py` serves `GET /api/state`, `/api/scene` and `/api/grafana/*` by reading the same files the dashboards used to read directly (`visualization/state.json`, `visualization/scene.json`, `visualization/grafana/*`)
- the `webui/` React app (`http://localhost:3000`) polls these endpoints every 5 seconds and renders the Overview and Risk pages
- displays annualized volatility, volatility regime, target position weight and leverage factor per asset
- works with Lean backtests and observation mode before broker API keys are available
- run with `uvicorn monitoring.api_server:app --port 8000 --reload`
