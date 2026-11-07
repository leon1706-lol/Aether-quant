<p align="center">
  <img src="development/logo.png" width="220" alt="Aether Quant logo">
</p>

<h1 align="center">Aether Quant</h1>

<p align="center">
  <strong>A self-adapting algorithmic trading system on QuantConnect Lean and PyTorch, and an open toolkit for building, testing and proving your own algorithms.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11-FF8C00?style=flat-square&labelColor=1A1A1A&logo=python&logoColor=white" alt="Python 3.11">
  <img src="https://img.shields.io/badge/%F0%9F%93%84%20license-PolyForm%20Noncommercial%201.0.0-8B5CF6?style=flat-square&labelColor=1A1A1A" alt="License: PolyForm Noncommercial 1.0.0">
  <!-- AQ:TEST_BADGE_START --><img src="https://img.shields.io/badge/tests-4809%2F4809%20passing-brightgreen?style=flat-square&labelColor=1A1A1A" alt="4809 of 4809 tests passing"><!-- AQ:TEST_BADGE_END -->
  <img src="https://img.shields.io/pypi/v/aether-quant?style=flat-square&labelColor=1A1A1A&color=FF8C00&logo=pypi&logoColor=white" alt="PyPI version">
  <img src="https://img.shields.io/badge/docker-ghcr.io%2Faether--quant-2496ED?style=flat-square&labelColor=1A1A1A&logo=docker&logoColor=white" alt="Docker image on GHCR">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/PyTorch-4B5563?style=flat-square&labelColor=1A1A1A&logo=pytorch&logoColor=white" alt="PyTorch">
  <img src="https://img.shields.io/badge/QuantConnect%20Lean-4B5563?style=flat-square&labelColor=1A1A1A&logo=quantconnect&logoColor=white" alt="QuantConnect Lean">
  <img src="https://img.shields.io/badge/Interactive%20Brokers-4B5563?style=flat-square&labelColor=1A1A1A" alt="Interactive Brokers">
  <img src="https://img.shields.io/badge/FastAPI-4B5563?style=flat-square&labelColor=1A1A1A&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/React-4B5563?style=flat-square&labelColor=1A1A1A&logo=react&logoColor=white" alt="React">
  <img src="https://img.shields.io/badge/Redis-4B5563?style=flat-square&labelColor=1A1A1A&logo=redis&logoColor=white" alt="Redis">
  <img src="https://img.shields.io/badge/PostgreSQL-4B5563?style=flat-square&labelColor=1A1A1A&logo=postgresql&logoColor=white" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/GitHub%20Actions-4B5563?style=flat-square&labelColor=1A1A1A&logo=githubactions&logoColor=white" alt="GitHub Actions">
</p>

Aether Quant is not a single static strategy. It's a **dynamic system**. At its core, an ensemble of neural models predicts, for every asset every day, a multi-horizon view of the market: **direction** at 1, 5 and 20 days, expected **return magnitude** and **volatility**, and each asset's **cross-sectional rank**. Predictions come from a **Mixture-of-Experts** ensemble (bullish/bearish/sideways/volatility specialists) routed by a learned gating network, plus a **causal-TCN sequence encoder**, all reading one feature pipeline that folds in a **market-regime detector**, a **3D market topology** layer and a **liquidity/market-impact engine**. A **unified multi-asset-class layer** routes equities, crypto, bonds, futures, options and forex through one portfolio, behind a kill switch, position reconciliation and a hash-chained audit log, while a **controlled retraining loop** and a **research cycle** let generations of models share capital and hand it over as evidence arrives. Everything is wired together and validated end to end inside QuantConnect's Lean engine. The thesis this project exists to test: **markets are non-stationary, so a trading model should be too.**

Proving that thesis is only half the purpose. Aether Quant is also meant to help build the next algorithm, whoever writes it. The [`aether_quant` library](#the-aether_quant-library) and the [`aq` CLI](#cli-reference) work on any signal, not just this project's, and offer the same tools it judges itself by: position sizing, book construction, order gates, a cost-aware simulator, pre-registered research with counted trials and once-only holdouts, overfitting tests, Lean-exact statistics, and generations that hand over gradually. The safety-critical functions behind them are proved in Lean 4 and tested against those proofs.

The book trading today is simpler than the stack around it: a long-only crypto trend sleeve, on paper only. It is labelled *improved, not verified*, because no pre-registered test has found a verified edge yet.

<!-- AQ:STATUS_START -->
| Lean Sharpe | Net profit | Max drawdown | Sharpe without T-bill carry | Alpha t | Deflated Sharpe |
|---|---|---|---|---|---|
| 0.63 | 33.850% | 7.83% | 0.72 | 0.13 | 4.01% |

_Lean run `2026-11-04_18-10-49`, 2023-07-01 to 2026-11-02, computed 2026-11-07 12:22 UTC. Details: [Backtest Statistics](#backtest-statistics)._
<!-- AQ:STATUS_END -->

## Known Limitations

- **No demonstrated edge.** The sleeve is mostly crypto exposure, and almost all of its result came before mid-2025. See [Alpha by Period](#alpha-by-period).
- **Nothing has survived selection.** All 46 pre-registered trials of the last three rounds failed, so the holdouts stay unread. See [Research Record](#research-record).
- **Hindsight in the universe.** The 12 coins are today's survivors. The same rule scored Sharpe -0.06 on coins no rule had read (#301), and Coinbase has delisted EOS (#311).
- **Paper only, and no broker yet.** Interactive Brokers cannot fill this sleeve, and the crypto venue (Coinbase assumed) needs an API key (#192). See RUNBOOK "When the keys arrive".
- **IB is unverified end to end.** Connection, live futures margin and all <!--fact:options.structures-->43<!--/fact--> option structures have only met Lean's samples, never a real Gateway. Futures and options stay data-empty until a key is connected (`aq ib status`).
- **Safety is not field-tested.** The kill switch, reconciliation and auto-rollback have run in unit tests and Lean backtests, never against a live broker and Postgres.
- **Packages lag the repo.** PyPI and the Docker image are at the last release tag (5.4.x), before the library existed. Install from source for now.

## Table of Contents

- [Known Limitations](#known-limitations)
- [The `aether_quant` Library](#the-aether_quant-library)
- [Download](#download)
- [Getting Started](#getting-started)
- [Requirements](#requirements)
- [Architecture](#architecture)
- [Universe Size](#universe-size)
- [Project Structure](#project-structure)
- [Module Documentation](#module-documentation)
- [Development Documentation](#development-documentation)
- [Open Source Files](#open-source-files)
- [Backtest Statistics](#backtest-statistics)
  - [Overview](#overview)
  - [Benchmarks](#benchmarks)
  - [Alpha by Period](#alpha-by-period)
  - [General Characteristics](#general-characteristics)
  - [Performance](#performance)
  - [Runs and Drawdowns](#runs-and-drawdowns)
  - [Implementation Shortfall](#implementation-shortfall)
  - [Return/Risk Efficiency](#returnrisk-efficiency)
  - [Attribution](#attribution)
  - [Robustness](#robustness): [Monte Carlo](#monte-carlo-simulation)
  - [Research Record](#research-record)
  - [Disclaimer](#disclaimer)
  - Retired model book: [Classification Scores](development/research_results.md#direction-heads), [Walk-Forward](development/research_results.md#walk-forward), [Lean vs Offline Books](development/research_results.md#lean-vs-offline), [Offline Evaluation](development/research_results.md#offline-evaluation), [As-Live Book](development/research_results.md#as-live-book), [Benchmarks](development/research_results.md#benchmarks), [Cross-Checks](development/research_results.md#cross-checks), [Research and Audit](development/research_results.md#rule-chains)
- [Test Suite](#test-suite)
- [CLI Reference](#cli-reference)
  - [`aq train`](#aq-train)
  - [`aq test`](#aq-test)
  - [`aq backtest`](#aq-backtest)
  - [`aq profile`](#aq-profile)
  - [`aq report`](#aq-report)
  - [`aq cycle`](#aq-cycle)
  - [`aq api`](#aq-api)
  - [`aq webui`](#aq-webui)
  - [`aq docker`](#aq-docker)
  - [`aq config`](#aq-config)
  - [`aq lean`](#aq-lean)
  - [`aq docs`](#aq-docs)
  - [`aq retrain`](#aq-retrain)
  - [`aq paper-readiness`](#aq-paper-readiness)
  - [`aq trade-lock`](#aq-trade-lock)
  - [`aq kill-switch`](#aq-kill-switch)
  - [`aq clean`](#aq-clean)
  - [`aq evaluate`](#aq-evaluate)
  - [`aq research`](#aq-research)
  - [`aq prove`](#aq-prove)
  - [`aq fetch`](#aq-fetch)
  - [`aq backfill`](#aq-backfill)
  - [`aq ib`](#aq-ib)
  - [`aq assets`](#aq-assets)
  - [`aq render-lean-config`](#aq-render-lean-config)
  - [`aq secrets-check`](#aq-secrets-check)
  - [`aq audit-log`](#aq-audit-log)
  - [`aq status`](#aq-status)
- [Release Process](#release-process)
- [Roadmap](#roadmap)

---

## The `aether_quant` Library

One importable package over the same pure functions the live algorithm and the research chain call: <!--fact:library.names-->690<!--/fact--> public names across <!--fact:library.modules-->24<!--/fact--> modules.

```powershell
pip install "aether-quant[research] @ git+https://github.com/leon1706-lol/Aether-quant"
# from a clone: pip install -e .[research]
```

Score your own signal, build a constrained book, gate an order and test for overfitting:

<!-- Executed by tests/test_readme_library_example.py -->
```python
import numpy as np
import pandas as pd

from aether_quant import execution, portfolio, research, risk

# Your signal: one score per ticker per date, next to the realised rank it should predict
rng = np.random.default_rng(0)
rows = []
for date in pd.date_range("2024-01-01", periods=120, freq="B").strftime("%Y-%m-%d"):
    future = rng.normal(size=30)
    ranks = pd.Series(future).rank(pct=True).to_numpy()
    for i in range(30):
        rows.append({"date": date, "ticker": f"T{i}", "split": "validation", "my_score": 0.3 * future[i] + rng.normal(),
                     "target_rank_5d": ranks[i], "target_rank_20d": ranks[i]})
frame = pd.DataFrame(rows)

# 1. The report this project judges its own models by: rank IC, HAC t, bootstrap interval
report = research.evaluate_signal(frame, score_column="my_score", splits=("validation",), bootstrap_draws=200)
h20 = report["splits"]["validation"]["h20"]
print(f"IC {h20['mean_ic']:.3f}, HAC t {h20['hac_t']:.1f}")

# 2. A market-neutral book: per-name and sector caps, dollar neutrality, gross cap
weights, _ = portfolio.apply_book_neutrality(
    {"AAA": 0.20, "BBB": 0.10, "CCC": -0.15, "DDD": -0.05},
    sector_by_symbol={"AAA": "tech", "BBB": "tech", "CCC": "energy", "DDD": "tech"},
    dollar_neutral=True, sector_neutral=True, gross_exposure_cap=0.5, max_weight_per_name=0.12, sector_max_net_weight=0.15,
)

# 3. Sizing never flips a trade or exceeds its cap; a tripped risk lock stops the order
sized = risk.build_dynamic_position_sizing(-0.3, 0.9, 0.02, 0.10)
allowed, reason = execution.resolve_order_permission("paper", True, True, False)
print(round(sized.target_weight, 4), allowed, reason)

# 4. How likely is the best of your variants just the luckiest? (daily returns, one column per variant)
trial_returns = rng.normal(0, 0.01, size=(400, 8))
print("PBO:", research.probability_of_backtest_overfitting(trial_returns, blocks=8)["pbo"])
```

How it works:

- **A facade, not a copy.** Every name is re-exported from the module `main.py` and the offline tools already use, so a library result and a live decision come from the same code.
- **Light to import.** No torch, Lean, Redis, Postgres or web stack. Optional extras load only when called.
- **Modules map to jobs:**
  - `risk`, `portfolio`, `execution`: sizing, kill switch, book construction, HRP, order gates, cost model, reconciliation.
  - `features`, `training`, `data`: indicators, cross-sectional ranks, purged folds, data parsers.
  - `evaluation`, `research`: simulators, Monte Carlo, Lean-exact statistics, deflated Sharpe, PBO, factor spanning, leakage audits.
  - `cycle`: pre-registered rounds, generation shares, decay detection, retraining preflight.
  - `audit`, `formal`, `io`: the hash chain, Lean 4 proof cases, finite-safe JSON.
- **Stable surface.** The public names are pinned in `tests/data/aether_quant_api.json`, so a change is always deliberate.

Runnable tours: [`examples/aether_quant_quickstart.py`](examples/aether_quant_quickstart.py), [`examples/aether_quant_cycle.py`](examples/aether_quant_cycle.py). Full module list: [`aether_quant/README.md`](aether_quant/README.md).

## Download

The published release, behind the repo for now (see [Known Limitations](#known-limitations)):

```powershell
pip install aether-quant
docker pull ghcr.io/leon1706-lol/aether-quant:latest
```

For the library, install from git as shown [above](#the-aether_quant-library).

## Getting Started

From a clone, with a virtual environment active:

```powershell
pip install -r requirements/requirements.txt
pip install -r requirements/requirements-dev.txt
pip install -e .                # registers the `aq` command
aq --help
aq test                         # the suite, without Redis, Postgres or IB
aq evaluate --lean-report       # refresh the statistics from a finished run
aq cycle status                 # what is due today
```

- **Dashboard:** run `aq api` (port 8001), then `npm install` in `webui/` and `aq webui` (port 3002).
- **Training:** `aq train`, `aq cycle retrain`. See [`RUNBOOK.md`](RUNBOOK.md).

## Requirements

- **Python <!--fact:python.ci-->3.11<!--/fact-->**, which CI runs. Package metadata says <!--fact:python.requires-->>=3.10<!--/fact-->, but `evaluation/lean_statistics.py` needs 3.11 (#326).
- **For backtests:** Docker and the Lean CLI (`pip install lean`). The first run pulls the pinned engine image, <!--fact:lean.engine-->quantconnect/lean:17900<!--/fact-->, about 40 GB.
- **For the infrastructure:** Docker Compose (Redis, Postgres, workers). Everything degrades gracefully without it.
- **For the dashboard:** Node.js.
- **For retraining:** 14 GB of RAM, or the training Codespace through the GitHub CLI (`gh`).

Dependency sets are listed in [`requirements/README.md`](requirements/README.md).

## Architecture

Every decision runs daily inside Lean's `on_data()`. A config flag picks what drives the book:

- **Target weights (shipped):** `phase_v2.target_weights` reads `ml/target_weights.csv`, produced by a rule or by blended generations, and an offline twin tracks it at a daily correlation above 0.99.
- **Model book (trained, not trading):** the ensemble's rank heads drive a dollar- and sector-neutral long/short book. It has failed the pre-registered bar every time.

```mermaid
flowchart LR
    D["Lean data<br/>equities, bonds, crypto, forex"] --> F["Feature pipeline<br/>regime, liquidity, topology, macro"]
    F --> M["Models<br/>4 experts + gating,<br/>multitask, sequence"]
    M -. "model book" .-> B["Book construction<br/>neutrality, sizing, costs"]
    W["Target weights<br/>rule or blended generations"] -- "shipped" --> B
    B --> G["Safety gates<br/>kill switch, order gate,<br/>reconciliation"]
    G --> L["Lean orders"]
    L --> R["Redis, then PostgreSQL<br/>experience and audit log"]
    R --> T["Performance triggers"]
    T --> C["Controlled retraining<br/>validate, promote, roll back"]
    C --> M
    Q["Research cycle<br/>rounds, generations, decay"] --> W
    C --> Q
```

**Models** (one shared feature code path for training and runtime)

- **Baseline + 4 experts:** bullish, bearish, sideways and volatility specialists, routed by a learned gating network.
- **Multitask:** a shared trunk with direction, magnitude, volatility and rank heads, including residualised ranks that measure skill rather than beta.
- **Sequence:** a causal-TCN over a 30-bar window.
- **Ranking objective:** trained directly on soft-Spearman or ListNet over whole dates.

**Risk and execution**

- **Sizing:** bounded and direction-preserving, scaled down when expected edge does not clear round-trip cost.
- **Controls:** an automated kill switch, reconciliation against broker holdings, a drawdown lock and an opt-in auto-rollback.
- **Asset classes:** one router for equities, crypto, bonds, forex, futures and options.

**Research cycle** (`aq cycle`)

- **Rounds:** rules are hashed before any score, trials go in a ledger, and a holdout read happens once.
- **Generations:** up to four share a book, each one's share computed from its record and moving smoothly.
- **Admission:** a candidate must earn its share (R-ADMIT1); real money is always the owner's manual action.
- **Off by default:** `ml/generations/policy.json` has `enabled: false`, and nothing in Lean reads it.

**Stack:** Lean CLI, Docker Compose, Redis, PostgreSQL, PyTorch, NumPy/pandas, FastAPI, React/Vite, Telegram alerts, GitHub Actions, Codespaces. Full contracts: [`development/architecture.md`](development/architecture.md).

## Universe Size

<!--fact:universe.total-->104<!--/fact--> assets in `config.json`: <!--fact:universe.equity-->55<!--/fact--> equities and broad ETFs, <!--fact:universe.bond-->22<!--/fact--> bond ETFs, <!--fact:universe.crypto-->12<!--/fact--> crypto pairs, <!--fact:universe.forex-->15<!--/fact--> forex pairs. The shipped book trades the crypto pairs; the rest feed the models.

| Split | Dates |
|---|---|
| Training | <!--fact:windows.training-->2014-12-01 to 2021-12-31<!--/fact--> |
| Validation | <!--fact:windows.validation-->2022-01-01 to 2023-06-30<!--/fact--> |
| Backtest | <!--fact:windows.backtest-->2023-07-01 to 2025-06-30<!--/fact--> |
| Holdout | <!--fact:windows.holdout-->2025-07-01 to 2026-11-02<!--/fact--> |

Tickers and roles: [`development/asset_universe.md`](development/asset_universe.md).

## Project Structure

Single-responsibility Python packages, each with its own README, a few top-level entry points (`main.py` for the Lean algorithm, `train*.py` for the trainers, `aq_cli.py` for the CLI) and the runtime config (`config.json`, `lean.json`). The annotated tree is in [`development/project_structure.md`](development/project_structure.md).

## Module Documentation

| Area | Module | What it owns |
|---|---|---|
| Library | [`aether_quant/`](aether_quant/README.md) | The importable facade over every subsystem |
| Library | [`formal/`](formal/README.md) | Lean 4 proofs of the safety-critical functions (`aq prove`) |
| Trading | [`risk/`](risk/README.md) | Position sizing, leverage, kill switch, asset-class routing |
| Trading | [`portfolio/`](portfolio/README.md) | Book construction, HRP, sleeves, target weights, options |
| Trading | [`execution/`](execution/README.md) | Order gate, cost model, reconciliation, paper readiness |
| Trading | [`analyzer/`](analyzer/README.md) | The final per-asset action layer |
| Models | [`features/`](features/README.md) | Feature functions shared by training and runtime |
| Models | [`inference/`](inference/README.md) · [`cpp_inference_ext/`](cpp_inference_ext/README.md) | The numpy forward pass · its optional C++ accelerator |
| Models | [`moe/`](moe/README.md) · [`experts/`](experts/README.md) | The gating network · the four expert models |
| Models | [`regime/`](regime/README.md) · [`topology/`](topology/README.md) · [`liquidity/`](liquidity/README.md) | Regime detection · market topology · market impact |
| Models | [`ml/`](ml/README.md) | Weights, datasets, candidates, generations |
| Research | [`evaluation/`](evaluation/README.md) | Simulators, audits, statistics, the research cycle |
| Research | [`retraining/`](retraining/README.md) · [`performance/`](performance/README.md) | Controlled retraining and rollback · performance triggers |
| Research | [`backtests/`](backtests/README.md) | Lean run output (gitignored) |
| Data | [`data/`](data/README.md) · [`data_pipeline/`](data_pipeline/README.md) | The Lean data layout · backfills and bar synthesis |
| Ops | [`experience/`](experience/README.md) · [`audit/`](audit/README.md) | Redis-to-Postgres decision history · the hash-chained audit log |
| Ops | [`monitoring/`](monitoring/README.md) · [`webui/`](webui/README.md) · [`visualization/`](visualization/README.md) | FastAPI · the React dashboard · runtime state exports |
| Ops | [`notifications/`](notifications/README.md) | Telegram alerts |
| Tooling | [`tests/`](tests/README.md) · [`scripts/`](scripts/README.md) · [`requirements/`](requirements/README.md) | The suite · dev and research scripts · dependency sets |

## Development Documentation

| Document | Contents |
|---|---|
| [`development/architecture.md`](development/architecture.md) | Subsystem contracts and the offline/live parity contract |
| [`development/infrastructure.md`](development/infrastructure.md) | Docker, ports, Codespaces, database inspection |
| [`development/research_results.md`](development/research_results.md) | Generated results of the retired model book and past rule chains |
| [`development/project_structure.md`](development/project_structure.md) | The directory tree |
| [`development/asset_universe.md`](development/asset_universe.md) | The tickers |
| [`development/Changelog.md`](development/Changelog.md) | Build history |
| [`development/Problems.md`](development/Problems.md) | Bug log |
| [`development/backups/`](development/backups/README.md) | Full text from before each condensing pass |

## Open Source Files

| File | Purpose |
|---|---|
| [`LICENSE`](LICENSE) | PolyForm Noncommercial 1.0.0 |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Setup and conventions for people |
| [`AGENTS.md`](AGENTS.md) | Setup and conventions for AI agents |
| [`RUNBOOK.md`](RUNBOOK.md) | Everyday commands, incidents, the research cycle, what to do when keys arrive |
| [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md) | How to reproduce every published number |
| [`SECURITY.md`](SECURITY.md) | Reporting a vulnerability |
| [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) | Community conduct |
| [`todo.md`](todo.md) | The owner's current objectives |

## Backtest Statistics

The shipped book's numbers from the real Lean engine. Every table is generated, never hand-edited: `aq backtest` or `aq evaluate --lean-report --backtest-dir backtests/<run>` refreshes them.

- **Portfolio** is the whole Lean run. **Strategy** is that run without its T-bill sweep, because idle-cash carry is not alpha.
- The current code reproduces the pinned run order for order. No newer run is needed until the book changes.
- Results of the retired model book live in [`development/research_results.md`](development/research_results.md).

### Overview

<!-- AQ:BACKTEST_START -->
![Backtest equity curve](development/backtest_equity_chart.png)

| Metric | Value |
|---|---|
| Backtest window | 2023-07-01 to 2026-11-02 |
| Sharpe Ratio | 0.633 |
| Net Profit | 33.850% |
| Compounding Annual Return | 9.100% |
| Drawdown | 7.800% |
| Total Orders | 1012 |
| Win Rate | 61% |
| Last updated | 2026-11-07 10:54 UTC (auto-generated by `aq backtest`) |
<!-- AQ:BACKTEST_END -->

### Benchmarks

<!-- AQ:BTSTATS_BENCHMARKS_START -->
| Series | Total return | Annual return | Volatility | Sharpe | Max drawdown |
|---|---|---|---|---|---|
| **Portfolio** (with the T-bill sweep) | +34.25% | +9.26% | 7.68% | 1.19 | 7.83% |
| **Strategy** (without the sweep) | +18.95% | +5.36% | 7.68% | 0.72 | 9.88% |
| SPY | +76.55% | +18.64% | 14.91% | 1.22 | 18.76% |
| 60/40 SPY/AGG, rebalanced daily | +48.09% | +12.53% | 9.63% | 1.27 | 11.27% |
| Bitcoin, buy and hold | +157.01% | +32.83% | 46.20% | 0.84 | 53.06% |
| The book's 12 coins, equal weight | +107.25% | +24.50% | 65.38% | 0.66 | 61.95% |

_Run `2026-11-04_18-10-49` · computed 2026-11-07 12:22 UTC · same sessions to the last equity close, no risk-free rate_
<!-- AQ:BTSTATS_BENCHMARKS_END -->

### Alpha by Period

<!-- AQ:ALPHA_START -->
| Period | Dates | Sharpe | 95% interval | Alpha per year | Alpha t | Deflated Sharpe |
|---|---|---|---|---|---|---|
| Whole run | 2023-07-02 to 2026-11-04 | 0.72 | -0.46 to 1.90 | +0.37% | 0.13 | 4.01% |
| First half | 2023-07-02 to 2025-06-30 | 1.15 | -0.48 to 2.73 | -0.69% | -0.18 | 22.89% |
| Second half | 2025-07-01 to 2026-11-02 | 0.06 | -1.58 to 1.66 | +2.43% | 0.64 | 3.18% |
| Long run, same rule | 2014-12-02 to 2026-11-04 | 0.91 | 0.26 to 1.51 | +1.30% | 0.83 | 0.42% |

**Proof of alpha (R-ALPHA1): not demonstrated** (full-window alpha t < 2.0; deflated Sharpe < 0.95).

_Run `2026-11-04_18-10-49` · computed 2026-11-07 10:55 UTC · alpha against SPY / AGG / BTCUSD with a Newey-West t · deflated over 192 ledger trials_
<!-- AQ:ALPHA_END -->

### General Characteristics

<!-- AQ:BTSTATS_GENERAL_START -->
| Metric | Portfolio | Strategy | Note |
|---|---|---|---|
| Time range | 2023-07-01 to 2026-11-02 |  |  |
| Years | 3.35 |  |  |
| Average AUM | $121,732 |  |  |
| Capacity (Lean estimate) | $37,000,000 |  | lowest-capacity asset XLMUSD 2XR |
| Leverage, mean (gross exposure / NAV) | 0.96x | 0.11x |  |
| Leverage, max | 1.04x | 0.20x |  |
| Maximum dollar position | — | $7,463 | BCHUSD on 2026-01-03 |
| Ratio of longs (share of bets) | — | 100.00% |  |
| Longs : shorts (bets) | — | 126 : 0 |  |
| Frequency of bets (per year) | — | 37.6 |  |
| Average holding period (days, notional-weighted) | — | 32.0 |  |
| Annualized turnover (traded notional / AUM) | 2.79x | 2.36x |  |
| Correlation to underlying (SPY, daily) | 0.293 | 0.294 |  |
| Start equity | $100,000 |  |  |
| End equity | $133,850 |  |  |
| Total orders | 1,012 |  |  |
| Lean portfolio turnover (daily mean) | 0.790% |  |  |

_Run `2026-11-04_18-10-49` · computed 2026-11-07 12:22 UTC_
<!-- AQ:BTSTATS_GENERAL_END -->

### Performance

<!-- AQ:BTSTATS_PERFORMANCE_START -->
| Metric | Portfolio | Strategy |
|---|---|---|
| PnL | +$33,850 | +$19,351 |
| PnL from the T-bill sweep (carry) | +$14,499 |  |
| PnL from long positions (closed bets, net of fees) | — | +$19,388 |
| PnL from short positions (closed bets, net of fees) | — | +$0 |
| Annualized rate of return | +9.10% | +5.43% |
| Hit ratio (closed bets net of fees) | — | 48.82% |
| Average return from hits | — | +39.96% |
| Average return from misses | — | -16.09% |
| Time-weighted return (no external flows: the chained return) | +33.85% | +19.35% |
| Net profit (Lean) | 33.850% |  |
| Win rate / loss rate (Lean, all trades) | 61% / 39% |  |
| Average win / average loss (Lean) | 0.13% / -0.11% |  |
| Profit-loss ratio (Lean) | 1.16 |  |
| Expectancy (Lean) | 0.329 |  |
| Unrealized at the end (Lean) | +$12,331 |  |

_Run `2026-11-04_18-10-49` · computed 2026-11-07 12:22 UTC_
<!-- AQ:BTSTATS_PERFORMANCE_END -->

### Runs and Drawdowns

<!-- AQ:BTSTATS_RUNS_START -->
| Metric | Portfolio | Strategy |
|---|---|---|
| HHI of positive returns | 0.002 | 0.002 |
| HHI of negative returns | 0.002 | 0.002 |
| HHI of time between bets (bets per month) | — | 0.032 |
| 95-percentile drawdown | 4.67% | 7.13% |
| 95-percentile time under water (days) | 229.1 | 240.5 |
| Maximum drawdown | 7.83% | 10.82% |
| Longest time under water (days) | 393 | 393 |
| Drawdown episodes | 32 | 26 |
| Drawdown (Lean) | 7.800% |  |
| Drawdown recovery (Lean, days) | 243 |  |
| Maximum drawdown duration (Lean) | 159.00:00:00 |  |

_Run `2026-11-04_18-10-49` · computed 2026-11-07 12:22 UTC_
<!-- AQ:BTSTATS_RUNS_END -->

### Implementation Shortfall

<!-- AQ:BTSTATS_SHORTFALL_START -->
| Metric | Portfolio | Strategy |
|---|---|---|
| Traded notional | $1,138,044 | $961,478 |
| Broker fees | $7,753 | $7,692 |
| Broker fees per turnover (bps of traded notional) | 68.1 bps | 80.0 bps |
| Average slippage per turnover (bps vs the bar's open) | 8.6 bps | 10.0 bps |
| Dollar performance per turnover (bps) | 297.4 bps | 201.3 bps |
| Return on execution costs (net PnL / (fees + slippage)) | 3.88x | 2.24x |
| Total fees (Lean) | $7,753 |  |

_Run `2026-11-04_18-10-49` · computed 2026-11-07 12:22 UTC_
<!-- AQ:BTSTATS_SHORTFALL_END -->

### Return/Risk Efficiency

<!-- AQ:BTSTATS_EFFICIENCY_START -->
| Metric | Portfolio | Strategy | Note |
|---|---|---|---|
| Annualized Sharpe ratio (Lean: risk-free rate subtracted) | 0.633 |  |  |
| Annualized Sharpe ratio (no risk-free rate) | 1.204 | 0.720 |  |
| Information ratio vs SPY | -0.625 | -0.874 |  |
| Information ratio (Lean) | -0.715 |  |  |
| Probabilistic Sharpe ratio (P[true Sharpe > 0]) | 98.76% | 90.85% |  |
| Probabilistic Sharpe ratio (Lean, vs its benchmark) | 21.770% |  |  |
| Deflated Sharpe ratio | 26.45% | 6.40% | 173 registered trials, expected best Sharpe 1.54 |
| Sortino ratio (Lean) | 0.973 |  |  |
| Alpha / beta (Lean) | 0.025 / 0.147 |  |  |
| Annual standard deviation (Lean) | 0.075 |  |  |
| Annual variance (Lean) | 0.0060 |  |  |
| Tracking error (Lean) | 0.146 |  |  |
| Treynor ratio (Lean) | 0.322 |  |  |
| Sharpe, Lean formula (shipped rate file/365) | 0.633 |  |  |

_Run `2026-11-04_18-10-49` · computed 2026-11-07 12:22 UTC_
<!-- AQ:BTSTATS_EFFICIENCY_END -->

### Attribution

<!-- AQ:BTSTATS_ATTRIBUTION_START -->
| Class | Net PnL | Return on AUM (annual) | Volatility (annual) | Sharpe | Max drawdown (on AUM) | Risk share | Fees |
|---|---|---|---|---|---|---|---|
| cash_sweep | +$14,499 | +3.56% | 0.28% | 12.86 | 0.30% | 0.27% | $61 |
| crypto | +$19,353 | +4.75% | 7.48% | 0.72 | 11.36% | 99.73% | $7,692 |
| unattributed (Lean minus rebuilt) | -$1 | | | | | | |

_Run `2026-11-04_18-10-49` · computed 2026-11-07 12:22 UTC_
<!-- AQ:BTSTATS_ATTRIBUTION_END -->

### Robustness

#### Monte Carlo Simulation

<!-- AQ:MONTECARLO_START -->
![Monte Carlo equity curves](development/monte_carlo_equity_curves.png)

| Metric | p5 | p50 | p95 |
|---|---|---|---|
| Final return | 4.410409% | 32.631471% | 78.613024% |
| Annualized Sharpe | 0.21697 | 1.176288 | 2.203949 |
| Max drawdown | 5.024% | 7.980479% | 13.315981% |
| P(negative total return): **0.028** |||

_1000 block-bootstrapped histories (block 20 days, seed 42) of Lean run `2026-11-04_18-10-49`'s 1222 daily returns, 2023-07-01 to 2026-11-02. The run itself returned 33.85%; computed 2026-11-07 11:00 UTC (rendered 2026-11-07 12:22 UTC)._
<!-- AQ:MONTECARLO_END -->

<details>
<summary><strong>Full distribution</strong></summary>

<!-- AQ:MONTECARLO_FULL_STATS_START -->
Deeper distribution statistics across all Monte Carlo runs:

**Final total return (%)**

| p5 | p25 | p50 | p75 | p95 |
|---|---|---|---|---|
| 4.410409 | 19.770973 | 32.631471 | 47.866705 | 78.613024 |

**Annualized Sharpe**

| p5 | p25 | p50 | p75 | p95 |
|---|---|---|---|---|
| 0.21697 | 0.77705 | 1.176288 | 1.565803 | 2.203949 |

**Max drawdown (%)**

| p5 | p25 | p50 | p75 | p95 |
|---|---|---|---|---|
| 5.024 | 6.358014 | 7.980479 | 9.887616 | 13.315981 |

- Best run total return: **142.5662%**
- Worst run total return: **-12.8344%**
- Probability of a negative total return: **0.028**
- Config: n_runs=1000, method=`block`, block_size=20d, seed=42 (pinned - the section only changes when underlying results change)

The red line in the chart above is the element-wise AVERAGE of all run equity curves; faint blue lines are the individual bootstrap histories.
<!-- AQ:MONTECARLO_FULL_STATS_END -->

</details>

### Research Record

Each search used rules written before any score. Details are in [`development/Problems.md`](development/Problems.md).

| Search | Trials | Survivors | Nearest result | Entry |
|---|---|---|---|---|
| Candidate pool, strict bar | 38 selection trials | 0; overfitting probability 0.53 ended verification | The installed sleeve, Lean Sharpe 0.63, by fallback rule R-LEAN19 | #279 |
| Round 1: fundamentals, insiders, short volume, funding, point-in-time retrain, wide crypto | 28 | 0 | The sleeve itself scored -0.06 on unread coins | #300, #301 |
| Round 2 | 8 | 0 | Sharpe 0.57 | #310 |
| Round 3: pooled books, composites, published signs, quarterly accruals | 10 | 0 | Sharpe 0.58, second half 0.29 | #315 |

### Disclaimer

- **Only the Lean backtest counts as ground truth.** Offline numbers are estimates.
- **Capacity is theoretical.** It is a participation cap on historical volume, never tested against real fills at size.
- **A backtest is not a forecast.** The record since the data freeze is the real test: `aq cycle status`, [`forward/` on the `forward-ledger` branch](https://github.com/leon1706-lol/Aether-quant/tree/forward-ledger/forward).

## Test Suite

<!-- AQ:TEST_COUNT_START -->4816<!-- AQ:TEST_COUNT_END --> tests, one file per source module. `aq test` runs them and refreshes the badge above. Conventions: [`tests/README.md`](tests/README.md).

## CLI Reference

`aq --help` lists <!--fact:aq.commands-->28<!--/fact--> commands, and `aq <command> --help` gives every flag. Dry run is the default wherever a command writes data or config.

#### `aq train`
```text
aq train [--dataset-only|--init-only|--experts-only|--gating-only|--multitask-only|--sequence-only|--topology-only|--strategy-selector-only|--rl-sizing-only]
aq train --walk-forward [--step-days N] [--mode rolling|expanding] [--include-multitask] [--include-sequence] [--metrics M] [--resume-run-id ID]
aq train [--seed N] [--ranking-objective mse|soft_spearman|listnet]
```
Builds the dataset and trains the models into `ml/`.

- **No flag:** trains everything.
- **`--*-only`:** one piece. `--topology-only` and `--strategy-selector-only` need outcome events in Postgres and skip cleanly without them.
- **`--walk-forward`:** one diagnostic run per window, never touches the active models.

#### `aq test`
```text
aq test [--ruff] [--parallel] [--lean|--full]
aq test [--cli] [--risk] [--portfolio] [--features] [--data-pipeline] [--webui] [--ml] [--retraining] [--notifications] [--storage] [--live] [--audit] [--evaluation] [--formal] [--meta]
```
Runs pytest and refreshes the badge on a full run.

- **`--ruff`:** lint first and fail fast.
- **`--parallel`:** xdist. Don't use it on a low-memory machine, because each worker imports torch.
- **`--lean`, `--full`:** add the real Lean integration test, over an hour.
- **Subsystem flags:** run only those test files; they combine.

#### `aq backtest`
```text
aq backtest [--image IMAGE]
```
Runs `lean backtest .` and refreshes [Backtest Statistics](#backtest-statistics). Needs Docker.

- **`--image`:** use another engine image instead of the pinned local build.

#### `aq profile`
```text
aq profile [--iterations N] [--sort cumulative] [--batched] [--symbols-per-bar N] [--parallel] [--pool-workers N] [--no-gc] [--bucket-report]
aq profile [--regime] [--topology] [--topology-cached] [--learned-topology] [--liquidity] [--gating] [--analyzer] [--indicators] [--options]
```
Profiles the per-bar hot path without a backtest: a `pstats` breakdown plus p50/p95/p99 latency.

- **No subsystem flag:** the inference path. `--batched` profiles the production path, `--parallel` benchmarks a process pool.
- **Subsystem flags:** those pure functions; they combine.

#### `aq report`
```text
aq report <backtest-folder> <result-id>
```
Writes Lean's own HTML report to `backtests/<backtest-folder>/report.html`.

#### `aq cycle`
```text
aq cycle status [--ledger-file F]
aq cycle research {rules|score|placebo|gate|pbo|freeze|hold|report} --round R [--draft D] [--only T...] [--draws N] [--force] [--trial T] [--digest H]
aq cycle daily [--ledger-file F] [--dry-run]
aq cycle decide --generation G --weights W --ledger-file F --session D
aq cycle retrain --host {local,codespace} [--procedure P] [--smoke] [--dry-run] [--if-due]
aq cycle promote --generation G --to {shadow,ramping,active,fading,winding_down,retired,rejected} [--ledger-file F]
aq cycle schedule {show|install} [--platform {windows,linux}] [--host {local,codespace}] [--dry-run]
```
The research cycle: rounds, generations, decay and retraining.

- **`status`:** what is due today.
- **`retrain --host local`:** refuses under 14 GB of RAM; `--smoke` proves the plumbing anywhere.
- **`promote`:** follows R-ADMIT1 and never touches a broker setting.

#### `aq api`
```text
aq api
```
Starts the FastAPI monitoring server on port 8001.

#### `aq webui`
```text
aq webui
```
Starts the dashboard dev server.

#### `aq docker`
```text
aq docker up [--lean|--all]
aq docker build
```
`up` starts Redis and PostgreSQL by default. `build` rebuilds the app image.

#### `aq config`
```text
aq config [get <key>|set <key> <value>|keys [<prefix>]]
aq config preset --list|--show <name>|--apply <name> [--dry-run]
```
Reads and edits `config.json` by dotted key. `set` parses JSON values and keeps a backup; `preset` applies a named bundle after validating every key.

#### `aq lean`
```text
aq lean [get <key>|set <key> <value>|keys [<prefix>]]
```
The same tool for `lean.json`.

#### `aq docs`
```text
aq docs sync [--check]
```
Refreshes every marked fact in the docs from its source (`docs_facts.py`). `--check` changes nothing and exits 1 on drift, which is how CI catches stale numbers.

#### `aq retrain`
```text
aq retrain <plan|train|train_topology|train_gating|train_multitask|train_sequence|train_strategy_selector|validate|backtest|commit|promote|rollback|auto-rollback|status> [...]
```
Runs one stage of the controlled retraining pipeline by hand.

- **`train`:** a candidate in isolation, never the active files.
- **`validate`, `backtest`:** candidate against active.
- **`promote`, `rollback --to-version-id <id>`:** switch the active model.
- **`auto-rollback --status`:** a read-only check of whether the active model would roll back.

#### `aq paper-readiness`
```text
aq paper-readiness
```
The check to run before switching to paper: broker config and observation-mode health.

#### `aq trade-lock`
```text
aq trade-lock --on|--off|--auto|--status
```
Overrides the sticky drawdown lock. `--off` deliberately clears it.

#### `aq kill-switch`
```text
aq kill-switch --arm|--disarm|--auto|--status
aq kill-switch --history [--limit N]
```
Overrides the kill switch through the same file as the trade lock, so the two can't disagree. `--history` reads past trips from the audit log (needs `AETHER_POSTGRES_DSN`).

#### `aq clean`
```text
aq clean ml [--keep-versions N] [--keep-backups N] [--strip-walk-forward-datasets] [--apply] [--json]
```
Lists what can be removed from `ml/`. Active models are never listed, and nothing is deleted without `--apply`.

#### `aq evaluate`
```text
aq evaluate <flag> [--backtest-dir backtests/<run>] [--json]
```
Offline evaluation and audits. Every Lean-reading flag uses `--backtest-dir`, else the README pin, else the newest finished run. Each writes `ml/evaluation/<name>.json`.

**A finished Lean run**

| Flag | What it does |
|---|---|
| `--lean-report` | Runs every tool below that a run supports, then refreshes the README |
| `--backtest-stats` | The tables in [Backtest Statistics](#backtest-statistics) |
| `--alpha-proof [--data-dir DIR]` | Alpha, Sharpe interval and deflated Sharpe per period |
| `--lean-monte-carlo` | Block bootstrap of the run's daily returns |
| `--lean-stats [--interest-rate-file F] [--trading-days N]` | Lean's Sharpe, Sortino and PSR, replicated exactly |
| `--audit-backtest [--period START..END] [--book-run-index N] [--max-open-sessions N]` | Order-level audit; run it after every backtest |
| `--audit-fills` | Fills against the data's open: cost or price gap |
| `--attribute-lean [--book-history-file PATH]` | P&L per asset class and component |
| `--classification-parity` | Logged probabilities against the offline head |
| `--paper-check [--reference-dir R] [--start D] [--end D]` | A paper run against a reference run's bands |
| `--forward-ledger [--ledger-branch B] [--ledger-file F]` | Verifies the forward record's hash chain and judges each rule |

**The offline book** (the retired rank book)

| Flag | What it does |
|---|---|
| `--rank-book [--model M] [--head H] [--split S]` | Net and gross Sharpe, turnover, cost drag |
| `--as-live` | The same book through the live path's decision functions |
| `--all` | `--rank-book`, `--capacity`, `--stress`, `--calibrate-edge`, `--benchmarks`, `--monte-carlo`, `--classification` |
| `--capacity` · `--stress` | Participation-capped capacity · 1x, 2x, 3x costs |
| `--benchmarks` | Naive and public baselines on the same split |
| `--monte-carlo [--mc-runs N] [--mc-block-size B] [--mc-seed S] [--mc-method block\|iid]` | Bootstrap of the book's returns |
| `--classification` | Direction-head accuracy, F1, log-loss |
| `--ablation [--variants a,b,c]` | Each mechanism switched off in turn |
| `--factor-exposure` | Loadings on SPY and momentum, residual Sharpe |
| `--preset NAME` | A config preset in memory only |
| `--walk-forward-summary [--run-id ID]` | Print a finished walk-forward run |

**Research and audits**

| Flag | What it does |
|---|---|
| `--pbo [--trial-returns PATH]` | Probability of backtest overfitting |
| `--factor-spanning --signal CSV` | What a signal adds over plain factors |
| `--ic-by-class` · `--audit-gates` | Within- and between-class IC · the rolling-IC gate's vetoes |
| `--audit-leakage` · `--overfit-report` | Label and feature leakage · IC kept out of sample |
| `--audit-features [--permutation]` · `--audit-heads` | Feature quality · each head against its gate |
| `--audit-data [--data-root PATH]` | Every universe zip, plus a hash manifest |
| `--calibrate-sim-lean --calibration-file PATH` | Simulator-to-Lean gap, by mechanism |

**Calibration and replay** (print a value, write nothing to config)

| Flag | What it does |
|---|---|
| `--calibrate-edge` | `edge_bps_per_rank_unit` for the net-edge gate |
| `--calibrate-book-spread [--book-spread-percentile P]` | The minimum rank spread |
| `--calibrate-confidence-threshold [--confidence-threshold-percentile P]` | The minimum confidence |
| `--calibrate-rolling-ic-floor [--rolling-ic-floor-percentile P]` | The rolling-IC floor |
| `--calibrate-volatility-threshold [--volatility-threshold-percentile P]` | Per-class elevated volatility |
| `--replay-kill-switch` · `--replay-rolling-ic-gate` | Day-by-day offline replays |
| `--simulate-limit-fills [--limit-fill-offset-sweep 0.5,1.0,2.0]` | How often limit orders would fill |
| `--reconcile-book-history [--book-history-path P] [--replay-hysteresis] [--hysteresis-survives-veto] [--reconcile-run-index N \| --reconcile-all-runs]` | Lean's book against an offline re-derivation |
| `--reconcile-features --symbol TICKER` | One symbol's live features against the dataset |

Shared by the flags above: `--dataset PATH`, `--split S`, `--json`.

#### `aq research`
```text
aq research --signal CSV [--dataset PATH] [--horizons 5,20] [--out PATH]
```
Scores any `date,ticker,score` CSV: rank IC, t-stats, bootstrap interval, era stability and decay. The same report judges this project's models.

#### `aq prove`
```text
aq prove [--module NAME] [--regen-cases] [--check-sorry]
```
Builds the Lean 4 proofs in [`formal/`](formal/README.md) (needs elan and the Mathlib cache).

- **`--regen-cases`:** regenerate the differential cases; run it after any spec edit.
- **`--check-sorry`:** scan for unfinished proofs, no Lean install needed.

#### `aq fetch`
```text
aq fetch <crypto|stock> --ticker T --start D --end D [--apply]
aq fetch futures --ticker T --start D --end D --expiry D [--contract-month YYYYMM] [--family-ticker ROOT] [--apply]
aq fetch options --ticker T --start D --end D --expiry D --strike K --right <call|put> [--family-ticker ROOT] [--apply]
```
Backfills one new ticker and, with `--apply`, registers it in `config.json`. Crypto and stocks come from Yahoo Finance, futures and options from Interactive Brokers.

#### `aq backfill`
```text
aq backfill <dividends|fred|yfinance> [--apply] [--tickers T ...] [--series S ...] [--quotes]
```
Refreshes one data source across the whole universe: dividend schedules, FRED series, or thin Lean zips. `--quotes` derives a missing crypto quote zip. Never touches `config.json`.

#### `aq ib`
```text
aq ib status
```
Interactive Brokers readiness: disabled, missing credentials, or reachable. Credentials live in `lean.json` (`aq lean set ib-account <ACCOUNT>`).

#### `aq assets`
```text
aq assets status
```
Multi-asset readiness at a glance: IB, futures and options flags, margin specs, FRED coverage.

#### `aq render-lean-config`
```text
aq render-lean-config [--base lean.json] [--out lean.live.json] [--env-file .env.live]
```
Renders the gitignored `lean.live.json` from `AETHER_*` variables, for Lean's `--lean-config`. Prints field names only, never secrets.

#### `aq secrets-check`
```text
aq secrets-check
```
Exits non-zero if a secret is about to be committed. Backs `.githooks/pre-commit`.

#### `aq audit-log`
```text
aq audit-log [--event-type order_placement|credential_load|live_mode_transition] [--since YYYY-MM-DD] [--limit N] [--verify]
```
Queries the tamper-evident audit log (needs `AETHER_POSTGRES_DSN`). `--verify` walks the whole hash chain and reports the first broken link.

#### `aq status`
```text
aq status
```
Shows `git status`.

## Release Process

A release happens only on a pushed version tag:

```powershell
git tag v6.6.2
git push origin v6.6.2
```

The tag sets the version through `setuptools-scm`, then `.github/workflows/release.yml`:

- runs the test suite, and a failure blocks the release;
- publishes to PyPI through Trusted Publishing, with no stored token;
- pushes the Docker image to `ghcr.io/leon1706-lol/aether-quant`.

## Roadmap

History lives in [`development/Changelog.md`](development/Changelog.md); current objectives are in [`todo.md`](todo.md).

- **Interactive Brokers and a crypto venue:** verify end to end, then run the paper period (`aq evaluate --paper-check`).
- **Forward records:** judge the sleeve and any shadow generation at 60 and 252 sessions (`aq cycle status`).
- **A candidate that passes selection:** the unread holdouts back one frozen candidate, once.
- **Later, HFT:** tick data, short-horizon models and low-latency execution would be a second system alongside this one, not a change to it. See `development/architecture.md`.

---

<p align="center">
  Built by <strong>Leon Schwarzkopf</strong>, <a href="mailto:leonschwarzkopf08@gmail.com">leonschwarzkopf08@gmail.com</a>
</p>
