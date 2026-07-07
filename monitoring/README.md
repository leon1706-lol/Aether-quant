# monitoring

Owns V2 monitoring outputs:

- `api_server.py`: FastAPI JSON API serving runtime state to the `webui/` React app
- `/api/grafana/*` exports, now rendered by the webui's own Tracing page (V2-18 removed the Grafana service that used to be their only consumer)
- risk and leverage telemetry

Telegram alerting (V2-19) lives in its own `notifications/` package, not
here — it polls Postgres directly (same pattern as `retraining/`, which also
never goes through this API), not `monitoring/api_server.py`.

Current behavior:

- `api_server.py` serves `GET /api/state`, `/api/scene` and `/api/grafana/*` (including `/api/grafana/retraining-status`, V2-17) by reading the same files the dashboards used to read directly (`visualization/state.json`, `visualization/scene.json`, `visualization/grafana/*`) — `/api/state` additionally merges `visualization/grafana/retraining_status.json` server-side, since `main.py` never connects to Postgres and cannot compute that view itself the way it approximates `performance_triggers` in-memory
- `GET /api/neural-network` (V2-20) is a thin wrapper around `neural_network_state.py::build_neural_network_state()`, which reads the JSON weight exports for the baseline model, the 4 MoE experts, and — now that `moe/gating.py` can optionally have a learned model — the gating network too (`ml/gating_model.json`, degrades to `status="not_trained"` when absent). Reshapes each into a layer/node/edge summary for the webui's `/neural-network` 3D diagram. Only `topology/learned_topology.py`'s KMeans cluster prototypes stay excluded (not a layered network).
- the `webui/` React app (`http://localhost:3002` via `npm run dev`, or `http://localhost:8001` bundled inside the Docker `aether-quant` container) polls `/api/state`/`/api/scene`/`/api/topology` every 5 seconds for the Overview/Risk/Topology pages, and polls `/api/grafana/*` every 15 seconds for the Tracing page (V2-18)
- displays annualized volatility, volatility regime, target position weight and leverage factor per asset
- works with Lean backtests and observation mode before broker API keys are available
- run with `uvicorn monitoring.api_server:app --port 8001 --reload`
