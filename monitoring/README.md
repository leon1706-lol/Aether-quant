# monitoring

Owns V2 monitoring outputs:

- `api_server.py`: FastAPI JSON API serving runtime state to the `webui/` React app
- `/api/grafana/*` exports, now rendered by the webui's own Tracing page (V2-18 removed the Grafana service that used to be their only consumer)
- risk and leverage telemetry

Telegram alerting (V2-19) lives in its own `notifications/` package, not
here — it polls Postgres directly (same pattern as `retraining/`, which also
never goes through this API), not `monitoring/api_server.py`.

Current behavior:

- `api_server.py` serves `GET /api/state`, `/api/scene` and `/api/grafana/*` (including `/api/grafana/retraining-status`) by reading the same files the dashboards used to read directly (`visualization/state.json`, `visualization/scene.json`, `visualization/grafana/*`) — `/api/state` additionally merges `visualization/grafana/retraining_status.json` server-side, since `main.py` never connects to Postgres and cannot compute that view itself the way it approximates `performance_triggers` in-memory
- `GET /api/neural-network` is a thin wrapper around `neural_network_state.py::build_neural_network_state()`, which reads the JSON weight exports for the baseline model, the 4 MoE experts, and the gating network too (`ml/gating_model.json`, degrades to `status="not_trained"` when absent). Reshapes each into a layer/node/edge summary for the webui's `/neural-network` 3D diagram. Only `topology/learned_topology.py`'s KMeans cluster prototypes stay excluded (not a layered network).
- `GET /api/strategies` is a thin wrapper around `strategy_catalog.py::build_strategy_catalog()`, which reads `portfolio/options_strategy.py`'s `MULTI_LEG_STRATEGY_REGISTRY` (43 static entries) - computed fresh on every request, same "cheap local read, not worth caching" precedent as `/api/assets-status`. Backs the webui's `/options-strategy` page.
- `GET /api/evaluation` wraps `evaluation_state.py::build_evaluation_state()`, reading `ml/evaluation/*.json` (`aq evaluate`'s rank-book/capacity/stress/ablation/Monte-Carlo/benchmark-comparison reports) and the newest walk-forward summary — each section degrades independently to `{"status": "not_evaluated"}` rather than raising, so a partial evaluation run still returns something useful.
- `GET /api/health` (liveness), `GET /api/audit-log` (the hash-chained audit trail, `audit/README.md`) and `GET /api/grafana/paper-readiness` round out the read-only surface.
- the `webui/` React app (`http://localhost:3002` via `npm run dev`, or `http://localhost:8001` bundled inside the Docker `aether-quant` container) polls `/api/state`/`/api/scene`/`/api/topology` every 5 seconds for the Overview/Risk/Topology pages, and polls `/api/grafana/*` every 15 seconds for the Tracing page
- displays annualized volatility, volatility regime, target position weight and leverage factor per asset
- works with Lean backtests and observation mode before broker API keys are available
- run with `uvicorn monitoring.api_server:app --port 8001 --reload`
