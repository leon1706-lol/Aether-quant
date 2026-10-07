# Project Structure

`Dockerfile.lean` is the project-local Lean engine layer used by `aq backtest`;
it installs only Lean-runtime dependencies from `requirements/lean-runtime.txt`.

The repository is organized as a set of single-responsibility Python packages
(one concern per folder, each with its own README), a handful of top-level
entry-point scripts (`main.py` for the Lean algorithm, `train*.py` for the
offline trainers, `aq_cli.py` for the CLI), and the runtime config
(`config.json` / `lean.json`). The full per-module index, with a one-line
description and a link to each package's own README, is in the root README's
[Module Documentation](../README.md#module-documentation) table.

```text
aether-quant/
├── .devcontainer/                 # Codespaces / Dev Container definition (+ README)
├── .githooks/                     # Opt-in pre-commit secret-scan hook (+ README)
├── .github/                       # CI workflows (tests, guards, wheel smoke, webui build, release) + Dependabot
├── development/                   # Architecture docs, changelog, problems log, backtest chart
├── data/                        # Local Lean data folder (equities, crypto, bonds, Forex)
├── data_pipeline/                # Lean-data contract + Yahoo Finance / FRED (bond + alt-data) / IB historical backfill
├── analyzer/                    # Central market analyzer (final per-asset decision layer)
├── moe/                         # Mixture-of-Experts gating network
├── experts/                     # Bullish / bearish / sideways / volatility expert models
├── features/                    # Shared feature-computation functions (train.py + main.py parity)
├── evaluation/                  # Offline, cost-aware rank-book simulation (net Sharpe, capacity, ablation) + V5.5.0 as-live parity, backtest audit, volatility calibration
├── portfolio/                   # Stage-2 cross-sectional long/short book construction + neutrality + options sizing + V5.5.0 legacy-signal sleeve
├── regime/                      # Market regime detection
├── topology/                    # 3D market topology (deterministic SMACOF + learned overlay)
├── liquidity/                   # Liquidity / market-impact engine
├── risk/                        # Dynamic position sizing, leverage, drawdown controls
├── execution/                   # Order gating, paper/live broker readiness, config caching
├── inference/                   # Vectorized neural-network forward-pass interpreter
├── cpp_inference_ext/           # Optional C++/pybind11 accelerator (builds the "cpp_inference" module)
├── experience/                  # Redis -> PostgreSQL observation/decision history pipeline
├── audit/                       # Tamper-evident hash-chained audit log (Redis -> PostgreSQL)
├── performance/                 # Performance trigger system (drawdown, Sharpe, regime-shift, ...)
├── retraining/                  # Controlled retraining: plan/train/validate/backtest/promote
├── monitoring/                  # FastAPI JSON API serving runtime state to the webui
├── notifications/               # Telegram alerting worker
├── visualization/               # Shared runtime-state JSON/CSV exports
├── webui/                       # React/Vite dashboard (Overview, Risk, Topology, Neural Network, Tracing)
├── ml/                          # Model weights, datasets, versioned retraining candidates
├── storage/                     # Reserved for future persistent artifact storage
├── scripts/                     # Standalone dev tooling (profile_inference.py, wheel_smoke.py, check_test_count_drift.py, feature_parity_audit.py)
├── requirements/                # All requirements*.txt variants
├── tests/                       # Full pytest suite (one file per source module)
├── backtests/                   # Lean backtest run outputs (gitignored)
├── Aether-quant-Obsidian-Vault/ # Auto-generated code-graph / architecture vault
├── main.py                      # Lean algorithm: inference, signal engine, risk controls
├── train.py                     # Training pipeline: dataset build, model training, validation
├── train_topology.py            # Offline trainer for the learned topology overlay
├── train_gating.py              # Offline trainer for the learned gating blend
├── train_multitask.py           # Offline trainer for the joint direction+magnitude+volatility model
├── train_sequence.py            # Offline trainer for the causal-TCN sequence encoder
├── train_rl_sizing.py           # Offline trainer for the RL sizing overlay (contextual bandit, default off)
├── train_strategy_selector.py   # Offline trainer for the options strategy-selector model (dormant until options trade)
├── generate_backtest_report.py  # Regenerates the README's Backtest Results section
├── generate_evaluation_report.py # Regenerates the README's evaluation sections (Monte Carlo chart, benchmarks, ...)
├── risk_controls.py             # Pure position-scaling / exit-tracking / forex-units helpers (+ V5.5.0 cooldown exemption, pending-quantity projection, exit adoption)
├── performance_probe.py         # V5.5.0 stdlib-only timing probe + Lean teardown diagnostics/cleanup experiment
├── todo.md                      # Owner's live objectives canvas (read first; rewritten as objectives change)
├── aq_cli.py                    # `aq` convenience CLI
├── config.json                  # Runtime configuration (phase1 / phase_v2 blocks)
├── lean.json                    # Lean engine + brokerage configuration
├── docker-compose.yml           # Local infrastructure (Lean, Redis, PostgreSQL, workers)
├── Dockerfile                   # Consolidated app/worker image (`aether-quant-engine`)
├── Dockerfile.lean              # Project-local Lean engine layer used by `aq backtest`
├── RUNBOOK.md                   # Incident procedures (Symptoms -> Diagnosis -> Resolution)
├── REPRODUCIBILITY.md           # Exact re-run recipe for the published numbers
└── pyproject.toml               # Package metadata, `aq` entry point, pytest/ruff/coverage config
```
