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
`monitoring/api_server.py`. The `/api/grafana/` prefix is historical —
Grafana was removed from `docker-compose.yml` in V2-18 and the webui's own
Tracing tab is now the consumer: `TracingPage.tsx` fetches
`/api/grafana/metrics-snapshot`, `/equity-curves`, `/asset-performance`
and `/observation-equity-curve` directly, alongside `/api/neural-network`,
`/api/assets-status` and `/api/audit-log` elsewhere in the app. (This
paragraph previously claimed the webui only ever fetched
`/api/state`/`/api/scene`/`/api/topology`; that stopped being true at
V2-18 — corrected in V4.1.)

`observation_summary.json` and `performance_triggers.json` are served but
have no direct frontend consumer — the latter reaches the UI nested inside
`/api/state` instead. Note also that `metrics_snapshot.json` in this folder
is orphaned: `/api/grafana/metrics-snapshot` serves
`runtime_metrics_snapshot.json`.

- `book_history.jsonl` — V5.2.2 diagnostic, off by default
  (`phase_v2.diagnostics.book_history.enabled`). One JSON line per
  rebalance date, logging the live book's actual selections during a real
  Lean **backtest** (never written in live/paper mode, regardless of the
  config toggle). Reconciled offline against a fresh re-derivation of the
  same raw scores via `aq evaluate --reconcile-book-history` — see
  `portfolio/book_construction.py::build_book_history_record()` and
  `evaluation/rank_signal_calibration.py::reconcile_book_history_date()`.
  Not served by `/api/grafana/` like every other file above — it's a
  standalone diagnostic artifact, not runtime state.
  - V5.2.3 (development/Problems.md #91) adds an opt-in second toggle,
    `phase_v2.diagnostics.book_history.include_full_universe` (also off by
    default, additive to the toggle above): when on, each record also gets
    a `"universe"` key with EVERY symbol that had a bar this rebalance date
    (selected or not) — `raw_rank_score`, `feature_ready`, `reason` (when
    not ready), `trading_eligible`, `security_type`. Exists because the
    V5.2.2 log alone could not show why a symbol was never selected (e.g.
    a whole asset class silently absent from the live book) — only that it
    wasn't. `aq evaluate --reconcile-book-history` always attempts a
    per-`security_type` summary of this data when present, and
    `--replay-hysteresis` switches the reconciliation itself from
    independent-per-date to a walk-forward replay of offline's own
    hysteresis, carried forward the same way the live book's
    `_last_book_allocations` is. Both the reconciliation report and the
    book-spread-calibration report are also surfaced in the webui's
    Evaluation tab via `GET /api/evaluation` (`monitoring/evaluation_state.py`).
