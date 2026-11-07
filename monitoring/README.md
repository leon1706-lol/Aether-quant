# monitoring

The read-only FastAPI server (`api_server.py`) behind `webui/`. Start it with `aq api`. Telegram alerts live in `notifications/`.

| Endpoint | Serves |
|---|---|
| `GET /api/health` | Liveness |
| `GET /api/state`, `/api/scene` | Runtime state from `visualization/state.json` and `scene.json`, with risk and leverage telemetry |
| `GET /api/grafana/*` | The Tracing page's exports, including `retraining-status` and `paper-readiness` |
| `GET /api/neural-network` | Each exported network as layers, nodes and edges (`neural_network_state.py`) |
| `GET /api/strategies` | The options strategy registry (`strategy_catalog.py`) |
| `GET /api/evaluation` | `ml/evaluation/*.json` and the newest walk-forward run (`evaluation_state.py`) |
| `GET /api/generations` | `ml/generations/status.json` from `aq cycle status`; empty on a fresh checkout |
| `GET /api/assets-status` | Multi-asset readiness, as `aq assets status` |
| `GET /api/audit-log` | The hash-chained audit trail (`audit/README.md`) |

- **Fails soft:** each section degrades to a "not evaluated" view rather than an error.
- **Stays light:** no torch at import.
- **Polling:** the dashboard polls state every 5 seconds and Tracing every 15. It runs at `:3002` in dev, or `:8001` bundled in the Docker image.
