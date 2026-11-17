# Licensing

Aether Quant is licensed under two licenses, by path. `LICENSE` is the GNU Affero General Public License 3.0, which covers everything the library row below does not name. `REUSE.toml` states the same map file by file (https://reuse.software).

| Part | License | Paths |
|---|---|---|
| **The library** | Apache License 2.0 (`LICENSES/Apache-2.0.txt`, with `NOTICE`) | Everything the PyPI package `aether-quant` and the `aether-quant-dashboard` image ship: `aether_quant/` and the packages it re-exports (analyzer, audit, data_pipeline, evaluation, execution, experience, experts, features, inference, liquidity, moe, monitoring, notifications, performance, portfolio, regime, retraining, risk, topology); the top-level modules aq_cli.py, docs_facts.py, generate_backtest_report.py, generate_evaluation_report.py, json_safety.py, performance_probe.py and risk_controls.py; and `webui/`, `notebooks/`, `docs/`, `examples/`, `formal/`, `mkdocs.yml` and `Dockerfile`. |
| **The trading system** | GNU Affero General Public License 3.0 (`LICENSE`, `LICENSES/AGPL-3.0-only.txt`) | Everything else, in particular `main.py`, `train.py` and `train_*.py`, `config.json`, `lean.json`, `ml/` (trained models, weights, generations, research records), `data*/`, `scripts/`, `backtests*/`, `development/`, `Dockerfile.lean` and the forward and research records. |

- **What AGPL-3.0 asks:** commercial use is allowed. Anyone who changes this code and lets others use it, including over a network, offers those users the source of the changed version under the same license.
- **A commercial license** for the parts under AGPL-3.0, without its obligations, is available on request through the repository's GitHub page.
- **Earlier releases keep the terms they shipped under:** releases up to 6.6.4 were entirely PolyForm Noncommercial, and V6.6.5 to V6.6.7 paired the Apache-2.0 library with a PolyForm Noncommercial 1.0.0 trading system.

Copyright 2026 Leon Schwarzkopf (Aether Quant)
