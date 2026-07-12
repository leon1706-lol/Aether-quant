# execution

Pure, Lean-free order gating and simulated-fill math shared between `main.py`
and its test suite (V2-15, Observation Mode). Owns the
`phase_v2.runtime.mode` -> real-vs-simulated order decision table
(`resolve_order_permission`), the safe-fallback mode normalizer
(`resolve_runtime_mode`), and the hypothetical fill-price/quantity math used
by `experience/simulated_portfolio.py` (`simulate_fill`). No `AlgorithmImports`
or QCAlgorithm dependency, so it is unit-testable without a Lean runtime.

## Config-read caching (latency-optimization pass, post-V2-23)

`config_cache.py::read_cached(config_path, loader)` — a shared, mtime-gated
cache used by `paper_readiness_io.py::read_paper_trading_config()` and
`runtime_config_io.py::read_runtime_mode()` below (plus
`risk/manual_override.py::read_manual_trade_lock_override()`, outside this
package but following the same pattern). All three read `config.json` far
more often than the file actually changes — once per bar in a Lean
backtest, once per poll-loop iteration in `retraining/worker.py` — so this
avoids a redundant `open()`+`json.load()` on every call while still picking
up an edit as soon as the file's mtime changes.

**Cache key is `(config_path, loader)`, not just `config_path`** — several
distinct readers share the same `config.json` path within the same bar
(`main.py::_refresh_risk_state()` calls the manual-override reader and the
paper-trading reader back-to-back). An earlier path-only cache let one
reader's cached value leak into another's result, caught only by the real
`lean backtest .` integration test, not by unit tests — see
`development/Problems.md` #13 and `tests/test_config_cache.py`'s
`test_two_different_loaders_on_the_same_path_do_not_collide`.

## Paper/live broker readiness (V2-21/V2-22)

- `paper_readiness.py` (pure) — `evaluate_broker_config()` is the single
  entrypoint `main.py` calls regardless of mode; dispatches to
  `evaluate_paper_broker_config()` (Lean's built-in `PaperBrokerage`, no real
  credentials needed — just brokerage/live-data-provider/manual-review
  attestation flags) or `evaluate_live_broker_config()` (also requires real
  credentials and `evaluate_live_risk_posture()` to pass). Also
  `evaluate_observation_readiness()`, which codifies most of
  `development/infrastructure.md`'s "Bereit fuer Paper Trading?" checklist.
- `paper_readiness_io.py` (IO) — mtime-cached reads (see above) of
  `phase_v2.paper_trading` from `config.json`, plus the first
  `mode='observation'`-filtered `experience_events` query.
- `paper_readiness_report.py` — offline report (`aq paper-readiness`) that
  `main.py` can't compute itself (no Postgres connection there); writes
  `visualization/grafana/paper_readiness_report.json`.
- `live_credentials.py` (pure) + `live_credentials_io.py` (IO) — pre-flight
  validation only for real broker credentials (`ib_config.py` or
  `AETHER_IB_*` env vars via `.env.live`). Does not wire Lean itself — Lean
  reads its own `ib-*` fields directly from `lean.json`.
- `runtime_config_io.py` — mtime-cached read (see above) of
  `phase_v2.runtime.mode`, used by `retraining/worker.py`'s
  auto-promote-blocked-in-live-mode safety net (V2-22) since that worker is
  a separate process from `main.py`.

See the Paper Trading Readiness Contract (V2-21) and Live Deployment
Contract (V2-22) in `development/v2_architecture.md` for the full picture.

## Scheduled readiness reporting (Phase 7 of the 5/10 -> 9/10 roadmap)

`paper_readiness_report.py`'s evaluation logic and dashboard wiring were
already correct and already dashboard-visible before this pass —
`monitoring/api_server.py` already merges
`visualization/grafana/paper_readiness_report.json` into `/api/state`,
with a dedicated `get_paper_readiness()` endpoint. The one real gap: the
report only ever regenerated when a human ran `aq paper-readiness` by
hand, so the dashboard tile could silently go stale between manual runs.

`paper_readiness_scheduler.py::PaperReadinessScheduler` closes that gap —
a periodic loop around the exact same `build_paper_readiness_view()`/
`write_paper_readiness_file()` calls, mirroring
`performance/trigger_worker.py::TriggerWorker`'s shape (sync-only, DSN via
`AETHER_POSTGRES_DSN`, `--once` CLI flag, `_pg_conn` injection for tests).
Run it as its own small process/Docker service
(`python -m execution.paper_readiness_scheduler --poll-interval 3600`) —
deliberately **not** folded into `retraining/worker.py`'s poll loop, which
has a different cadence and responsibility. Purely additive reporting: it
never touches `phase_v2.paper_trading`'s config flags or changes
`main.py`'s order-routing behavior in any way.

## Activating real paper-trading fills — manual step

Everything in this package today (`experience/simulated_portfolio.py`'s
`enter_long()`/`exit()`/`liquidate_all()`, called from ~15 sites in
`main.py` — order application, exposure/position-count accounting, PnL
snapshots) is a **synthetic** fill model (`execution/order_gate.py::simulate_fill()`),
never a real Lean `PaperBrokerage` fill event. Switching the fill *source*
from simulated to real is a distinct, deliberately unbuilt follow-up
("Phase 7b") — not attempted by this roadmap pass, per the user's explicit
scope boundary. The rest of the pipeline (experience store, triggers,
retraining, `performance/rank_ic_monitor.py`) is designed to need no
change when that happens — only the fill *source* changes, the schema
that receives it stays the same.

**The "distinct, clearly-marked manual step" this requires already
exists — it is the existing config flags, not new code.**
`execution/paper_readiness.py::evaluate_paper_broker_config()` already
blocks activation until a human deliberately sets, in `config.json`:

- `phase_v2.paper_trading.live_data_provider_configured: true`
- `phase_v2.paper_trading.manual_review_confirmed: true`

Neither flag is touched by anything in this roadmap — both stay `false`
until a human flips them outside of any automated process, and
`aq paper-readiness`/`PaperReadinessScheduler` will keep reporting
`ready: false` (via `blocking_reasons`) until they do. When "Phase 7b"
(real fills) is eventually built, it will introduce its own additional
flag with the same manual-flip contract — never auto-enabled.
