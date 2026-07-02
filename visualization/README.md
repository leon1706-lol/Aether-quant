# visualization

Shared runtime-state JSON/CSV exports that `monitoring/api_server.py` reads
and serves as a JSON API, and that `main.py`/`train.py` write. No dashboard
code lives here anymore — the React webui (`webui/`) replaced the old
`dashboard.html`/`volatility_dashboard.html`.

- `state.json` — the full runtime state: signals, positions, portfolio,
  risk, liquidity, MoE gating, dashboard scorecards/heatmap, monitoring
  feeds — everything `GET /api/state` returns (merged server-side with
  `grafana/retraining_status.json` since V2-17, see below).
- `scene.json` — 3D market-scene payload for the webui's Overview page.
- `topology_state.json` — 3D topology/cluster state for the webui's
  Topology page (V2-11).
- `grafana/` — Grafana-friendly JSON/CSV feeds, one file per phase's
  dashboard export:
  - `metrics_snapshot.json`, `equity_curves.csv`, `asset_performance.csv` —
    baseline model metrics (Phase 8).
  - `observation_summary.json`, `observation_equity_curve.csv` —
    simulated-portfolio Observation Mode telemetry (V2-15).
  - `performance_triggers.json` — the current run's in-memory (**not**
    durable — see `performance/README.md`) trigger view (V2-16).
  - `retraining_status.json` — active/candidate model version, validation
    status, last trigger, Vault commit, rollback availability (V2-17).
    Written by `retraining/status_export.py`, the only durable-Postgres
    -backed file in this folder (every other file here is written directly
    by `main.py`/`train.py` from in-process state).

Every file here is served under `GET /api/grafana/<name>` by
`monitoring/api_server.py` for external Grafana dashboards; the webui itself
only ever fetches `/api/state`/`/api/scene`/`/api/topology` and reads the
nested fields those already contain.
