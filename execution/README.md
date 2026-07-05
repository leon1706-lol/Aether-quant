# execution

Pure, Lean-free order gating and simulated-fill math shared between `main.py`
and its test suite (V2-15, Observation Mode). Owns the
`phase_v2.runtime.mode` -> real-vs-simulated order decision table
(`resolve_order_permission`), the safe-fallback mode normalizer
(`resolve_runtime_mode`), and the hypothetical fill-price/quantity math used
by `experience/simulated_portfolio.py` (`simulate_fill`). No `AlgorithmImports`
or QCAlgorithm dependency, so it is unit-testable without a Lean runtime.

## Paper/live broker readiness (V2-21/V2-22)

- `paper_readiness.py` (pure) — `evaluate_broker_config()` is the single
  entrypoint `main.py` calls regardless of mode; dispatches to
  `evaluate_paper_broker_config()` (Lean's built-in `PaperBrokerage`, no real
  credentials needed — just brokerage/live-data-provider/manual-review
  attestation flags) or `evaluate_live_broker_config()` (also requires real
  credentials and `evaluate_live_risk_posture()` to pass). Also
  `evaluate_observation_readiness()`, which codifies most of
  `development/infrastructure.md`'s "Bereit fuer Paper Trading?" checklist.
- `paper_readiness_io.py` (IO) — fresh, uncached reads of
  `phase_v2.paper_trading` from `config.json`, plus the first
  `mode='observation'`-filtered `experience_events` query.
- `paper_readiness_report.py` — offline report (`aq paper-readiness`) that
  `main.py` can't compute itself (no Postgres connection there); writes
  `visualization/grafana/paper_readiness_report.json`.
- `live_credentials.py` (pure) + `live_credentials_io.py` (IO) — pre-flight
  validation only for real broker credentials (`ib_config.py` or
  `AETHER_IB_*` env vars via `.env.live`). Does not wire Lean itself — Lean
  reads its own `ib-*` fields directly from `lean.json`.
- `runtime_config_io.py` — fresh read of `phase_v2.runtime.mode`, used by
  `retraining/worker.py`'s auto-promote-blocked-in-live-mode safety net
  (V2-22) since that worker is a separate process from `main.py`.

See the Paper Trading Readiness Contract (V2-21) and Live Deployment
Contract (V2-22) in `development/v2_architecture.md` for the full picture.
