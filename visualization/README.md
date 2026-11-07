# visualization

Runtime exports that `main.py` and `train.py` write and `monitoring/api_server.py` serves. Dashboards live in `webui/`.

- **`state.json`:** signals, positions, risk, liquidity, gating and scorecards (`GET /api/state`).
- **`scene.json`, `topology_state.json`:** the Overview and Topology pages.
- **`grafana/`:** JSON and CSV feeds served under `/api/grafana/`. The name is historical; the Tracing page reads them:
  - `equity_curves.csv`, `asset_performance.csv`, `runtime_metrics_snapshot.json`: baseline metrics.
  - `observation_summary.json`, `observation_equity_curve.csv`: Observation Mode.
  - `performance_triggers.json`: this run's non-durable view, inside `/api/state`.
  - `retraining_status.json`: written by `retraining/status_export.py`, the only Postgres-backed file here.
- **`book_history.jsonl`, `book_history/`:** per-rebalance book records from a Lean backtest (`phase_v2.diagnostics.book_history`). `aq evaluate --reconcile-book-history` reads them. Never written in live mode, and a target-weights run has no book.
