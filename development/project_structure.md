# Project Structure

The repository is organized as a set of single-responsibility Python packages
(one concern per folder, each with its own README), a handful of top-level
entry-point scripts (`main.py` for the Lean algorithm, `train*.py` for the
offline trainers, `aq_cli.py` for the CLI), and the runtime config
(`config.json` / `lean.json`). The full per-module index, with a one-line
description and a link to each package's own README, is in the root README's
[Module Documentation](../README.md#module-documentation) table.

```text
aether-quant/
├── .github/                     # CI workflows (tests, webui build, release)
├── development/                 # Architecture docs, changelog, problems log, backtest chart
├── data/                        # Local Lean data folder (equities, crypto)
├── data_pipeline/                # Lean-data contract + Yahoo Finance historical backfill
├── analyzer/                    # Central market analyzer (final per-asset decision layer)
├── moe/                         # Mixture-of-Experts gating network
├── experts/                     # Bullish / bearish / sideways / volatility expert models
├── features/                    # Shared feature-computation functions (train.py + main.py parity)
├── portfolio/                   # Stage-2 cross-sectional long/short book construction + options sizing
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
├── scripts/                     # Standalone dev tooling (e.g. profile_inference.py)
├── requirements/                # All requirements*.txt variants
├── tests/                       # Full pytest suite (one file per source module)
├── backtests/                   # Lean backtest run outputs (gitignored)
├── Aether-quant-Obsidian-Vault/ # Auto-generated code-graph / architecture vault
├── main.py                      # Lean algorithm: inference, signal engine, risk controls
├── train.py                     # Training pipeline: dataset build, model training, validation
├── train_topology.py            # Offline trainer for the learned topology overlay
├── train_gating.py              # Offline trainer for the learned gating blend
├── train_multitask.py           # Offline trainer for the joint direction+magnitude+volatility model
├── train_sequence.py            # Offline trainer for the Phase 2 causal-TCN sequence encoder
├── generate_backtest_report.py  # Regenerates the README's Backtest Results section
├── aq_cli.py                    # `aq` convenience CLI
├── config.json                  # Runtime configuration (phase1 / phase_v2 blocks)
├── lean.json                    # Lean engine + brokerage configuration
├── docker-compose.yml           # Local infrastructure (Lean, Redis, PostgreSQL, workers)
└── pyproject.toml               # Package metadata, `aq` entry point, pytest config
```
