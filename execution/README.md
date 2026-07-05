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
