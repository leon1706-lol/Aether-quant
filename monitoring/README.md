# monitoring

The FastAPI server (`api_server.py`) behind `webui/`. Start it with `aq api`, or the demo image with `aq webui --docker`. It reads, apart from one audited write route. Telegram alerts live in `notifications/`.

| Endpoint | Serves |
|---|---|
| `GET /api/health` | Liveness, `demo` and `auth` (always open) |
| `GET /api/auth/whoami` | The signed-in user, role and accounts |
| `GET /api/accounts` | Each account's mode, broker, lock and readiness (`?account=` on the state routes) |
| `GET /api/readiness` | The paper-to-live scorecard (`aq live-readiness`) |
| `POST /api/accounts/{id}/trade-lock` | `{"locked": true}` (operator) or `false` (admin), audited in `state/api_actions.jsonl` |
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
- **Users (`auth.py` pure, `auth_io.py`, #350):**
  - Roles are viewer, operator and admin. Tokens are stored as salted PBKDF2-SHA256 hashes, and each user has an account scope; `aq users` manages them.
  - With a users file (`state/users.json` or `AQ_USERS_FILE`), every `/api` route but health needs `Authorization: Bearer <token>`.
  - Without one, reads stay open and nothing can write.
  - `authorize` is proved in `formal/AetherFormal/Authorize.lean`.
- **Demo (`demo/`, #344):** deterministic data from `scripts/build_dashboard_demo.py`. `AQ_DASHBOARD_ROOT` points the API at any tree, and `AQ_DASHBOARD_DEMO=1` shows the banner. The `dashboard` Docker target serves it on `:8000`.
