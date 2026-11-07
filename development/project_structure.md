# Project Structure

Each folder has one concern and its own README. Module index: the root README's [Module Documentation](../README.md#module-documentation).

```text
aether-quant/
├── aether_quant/        # The library: a facade over every subsystem
├── examples/            # Runnable library tours
├── formal/              # Lean 4 proofs of the safety-critical functions
├── main.py              # The Lean algorithm
├── aq_cli.py            # The `aq` CLI
├── docs_facts.py        # Numbers the docs quote, read from their sources
├── risk_controls.py     # Position-scaling, drawdown and exit helpers
├── json_safety.py       # Finite-safe JSON
├── performance_probe.py # Opt-in timing and teardown probes
├── train.py, train_*.py # Dataset build and trainers
├── generate_backtest_report.py, generate_evaluation_report.py  # Generated doc blocks
│
├── risk/                # Sizing, kill switch, asset-class routing
├── portfolio/           # Target weights, book construction, sleeves, options
├── execution/           # Order gate, cost model, reconciliation, readiness
├── analyzer/            # The final per-asset action
├── features/            # Feature functions shared by training and runtime
├── inference/           # The numpy forward pass
├── cpp_inference_ext/   # Optional C++ accelerator
├── moe/, experts/       # Gating and the four experts
├── regime/, topology/, liquidity/  # Market state
│
├── evaluation/          # Simulators, audits, statistics, the research cycle
├── retraining/          # Candidate gates, promotion, rollback
├── performance/         # Performance triggers
├── experience/, audit/  # Redis-to-Postgres history; the hash-chained log
├── monitoring/, webui/, visualization/, notifications/  # API, dashboard, exports, alerts
├── data_pipeline/       # Backfills and research sources
│
├── data/                # Lean data (gitignored)
├── ml/                  # Models and evidence; ml/generations/ is tracked
├── backtests/           # Lean run output (gitignored)
├── storage/             # Reserved
│
├── tests/               # The pytest suite
├── scripts/             # Hand-run tools
├── requirements/        # Dependency sets
├── development/         # Records and design docs
├── Aether-quant-Obsidian-Vault/  # Generated code graph (gitignored)
├── .github/, .devcontainer/, .githooks/
│
├── config.json, lean.json       # Runtime and Lean config
├── pyproject.toml               # Package, pytest, ruff, coverage
├── docker-compose.yml, Dockerfile, Dockerfile.lean
├── README.md, AGENTS.md, CONTRIBUTING.md, RUNBOOK.md, REPRODUCIBILITY.md, SECURITY.md, CODE_OF_CONDUCT.md
└── todo.md                      # The owner's current objectives
```
