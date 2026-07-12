<p align="center">
  <img src="development/logo.png" width="220" alt="Aether Quant logo">
</p>

<h1 align="center">Aether Quant</h1>

<p align="center">
  <strong>My state-of-the-art flagship trading model — a dynamic, self-adapting algorithmic trading system built on QuantConnect Lean and PyTorch, engineered to prove that dynamic models belong in dynamic markets.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-FF8C00?style=flat-square&labelColor=1A1A1A&logo=python&logoColor=white" alt="Python 3.10+">
  <!-- AQ:TEST_BADGE_START --><img src="https://img.shields.io/badge/tests-928%2F939%20passing-red?style=flat-square&labelColor=1A1A1A" alt="928 of 939 tests passing"><!-- AQ:TEST_BADGE_END -->
  <img src="https://img.shields.io/pypi/v/aether-quant?style=flat-square&labelColor=1A1A1A&color=FF8C00" alt="PyPI version">
  <img src="https://img.shields.io/badge/docker-ghcr.io%2Faether--quant-2496ED?style=flat-square&labelColor=1A1A1A&logo=docker&logoColor=white" alt="Docker image on GHCR">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/PyTorch-4B5563?style=flat-square&labelColor=1A1A1A&logo=pytorch&logoColor=white" alt="PyTorch">
  <img src="https://img.shields.io/badge/scikit--learn-4B5563?style=flat-square&labelColor=1A1A1A&logo=scikitlearn&logoColor=white" alt="scikit-learn">
  <img src="https://img.shields.io/badge/QuantConnect%20Lean-4B5563?style=flat-square&labelColor=1A1A1A" alt="QuantConnect Lean">
  <img src="https://img.shields.io/badge/FastAPI-4B5563?style=flat-square&labelColor=1A1A1A&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/React-4B5563?style=flat-square&labelColor=1A1A1A&logo=react&logoColor=white" alt="React">
  <img src="https://img.shields.io/badge/TypeScript-4B5563?style=flat-square&labelColor=1A1A1A&logo=typescript&logoColor=white" alt="TypeScript">
  <img src="https://img.shields.io/badge/Redis-4B5563?style=flat-square&labelColor=1A1A1A&logo=redis&logoColor=white" alt="Redis">
  <img src="https://img.shields.io/badge/PostgreSQL-4B5563?style=flat-square&labelColor=1A1A1A&logo=postgresql&logoColor=white" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/GitHub%20Actions-4B5563?style=flat-square&labelColor=1A1A1A&logo=githubactions&logoColor=white" alt="GitHub Actions">
</p>

Aether Quant is not a single static strategy — it's a **dynamic system**: a
Mixture-of-Experts ensemble (bullish/bearish/sideways/volatility specialists)
routed by a learned gating network, a market-regime detector, a 3D market
topology layer that combines a deterministic correlation embedding with a
learned probabilistic overlay, a liquidity/market-impact engine that adjusts
position sizing to real trading conditions, a cross-sectional ranking signal
that sizes each position by its predicted relative strength against the rest
of the trading universe, and a controlled retraining loop that lets the
model itself evolve as markets do — all wired together and validated
end-to-end inside QuantConnect's Lean engine. The thesis this project exists
to test is simple to state and hard to prove: **markets are non-stationary,
so a trading model should be too.** Every subsystem here exists to make the
model adapt — to regime shifts, to changing correlation structure, to
liquidity conditions — rather than to fit one historical window and hope it
generalizes.

## Table of Contents

- [Download](#download)
- [Getting Started](#getting-started)
- [Requirements](#requirements)
- [Architecture](#architecture)
- [Universe Size](#universe-size)
- [Project Structure](#project-structure)
- [Module Documentation](#module-documentation)
- [Development Documentation](#development-documentation)
- [Backtest Results](#backtest-results)
- [Test Suite](#test-suite)
- [CLI Reference](#cli-reference)
- [Release Process](#release-process)
- [Runbook](#runbook)
- [Roadmap](#roadmap)
- [Contributing](#contributing)

---

## Download

If you just want to use Aether Quant rather than develop on it, no local
`pip install -e .` or source checkout is needed — the CLI and backend are
published as ready-to-use releases:

```powershell
pip install aether-quant
docker pull ghcr.io/leon1706-lol/aether-quant:latest
```

`aq --help` is then available immediately (see [CLI Reference](#cli-reference)
below). `aq` checks PyPI at most once every 24h (short timeout, never
blocking) for a newer version and prints a one-line notice if one's
available — disable with `AQ_SKIP_UPDATE_CHECK=1`.

The Docker image is the same one `docker-compose.yml`'s `aether-quant`
service pulls by default (override with the `AETHER_QUANT_IMAGE` env var,
e.g. to use a locally built image instead).

## Getting Started

For local development (this repo cloned, a virtual environment active):

1. Install dependencies:

   ```powershell
   pip install -r requirements/requirements.txt
   pip install -r requirements/requirements-dev.txt   # local dev extras
   ```

2. Refresh the data inventory only:

   ```powershell
   python train.py --init-only
   ```

3. Build the dataset and train the model:

   ```powershell
   python train.py
   ```

   Or build dataset artifacts only, without training:

   ```powershell
   python train.py --dataset-only
   ```

4. Start the webui locally (two processes):

   ```powershell
   uvicorn monitoring.api_server:app --port 8001 --reload
   ```

   ```powershell
   cd webui
   npm install
   npm run dev
   ```

   Then open `http://localhost:3002`.

5. Run a real backtest and refresh this README's [Backtest Results](#backtest-results):

   ```powershell
   pip install -e .   # registers the `aq` command from source
   aq backtest
   ```

## Requirements

- **Python ≥ 3.10** for the training pipeline, `main.py`'s Lean algorithm, the FastAPI monitoring server, and the `aq` CLI.
- **QuantConnect Lean CLI** (`pip install lean`) for running backtests and paper/live trading.
- **Docker & Docker Compose** for the local infrastructure (Redis, PostgreSQL, and the background workers — experience persistence, performance triggers, controlled retraining, Telegram alerts).
- **Node.js** (for the `webui/` React/Vite dashboard).

This repo splits its Python dependencies across several `requirements*.txt`
files (full training stack vs. minimal per-Docker-image installs vs. local
dev extras) rather than one monolithic file. See
**[`requirements/README.md`](requirements/README.md)** for the exact
`pip install` command for every variant and which Dockerfile consumes each one.

## Architecture

Aether Quant runs a daily-bar decision pipeline entirely inside Lean's
`on_data()` callback: features flow through regime detection and 3D topology
modeling, both feed a gating network that routes across four specialized
experts, the central market analyzer combines all of that with the liquidity
engine's sizing input into one categorical action per asset per bar, and
every decision is persisted through a Redis → PostgreSQL experience pipeline
that a controlled retraining loop reads from to evolve the model over time.

#### System Flow

```mermaid
flowchart LR
    A["Lean data folder<br/>stocks, ETFs, bonds, crypto"] --> B["Feature pipeline<br/>train.py<br/>62-dim: price/volume + indicators +<br/>regime + liquidity + topology + peer returns + macro"]
    B --> C["Regime detection<br/>trend, volatility, drawdown, correlation"]
    B --> D["3D topology modeling<br/>market structure and clusters"]
    B -.-> U["Sequence encoder (Phase 2)<br/>causal-TCN, 30-bar window<br/>informational only"]
    B --> V["Multitask heads<br/>baseline + 4 experts<br/>direction + magnitude + volatility"]
    C --> E["Gating network<br/>the manager<br/>blends probability + magnitude/volatility"]
    D --> E
    V --> E
    E --> F["Expert modules"]
    F --> G["Bullish expert"]
    F --> H["Bearish expert"]
    F --> I["Sideways expert"]
    F --> J["Volatility expert"]
    G --> K["Market analyzer<br/>central decision layer"]
    H --> K
    I --> K
    J --> K
    C --> K
    D --> K
    L["Liquidity engine<br/>DDV, participation rate,<br/>slippage estimate"] --> K
    K --> M["Action categorization<br/>trade / simulate / observe<br/>reduce_risk / retrain_candidate"]
    M --> N["Lean order execution<br/>InteractiveBrokersFeeModel"]
    M --> O["Observation / simulation record"]
    N --> P["Redis event stream<br/>temporary low-latency buffer"]
    O --> P
    U -.-> P
    P --> Q["Experience worker<br/>async batch persistence"]
    Q --> R["PostgreSQL experience database<br/>single source of truth"]
    R --> S["Performance triggers<br/>100 observations, drawdown, Sharpe, regime shift"]
    S --> T["Controlled retraining<br/>versioned weights and rollback"]
    T --> E
```

Dashed edges mark the Phase 2 sequence encoder's **informational-only**
path — it's computed every bar and reaches the experience log, but never
the gating network, market analyzer, or position sizing (see
`inference/README.md`'s Phase 2 section).

#### Tech Stack

```mermaid
flowchart TB
    A["Infrastructure"] --> A1["Docker Compose<br/>(Redis, Postgres, aether-quant app)"]
    A --> A2["Lean CLI<br/>(backtest + paper trading)"]
    A --> A3["30-day observation phase before live mode"]
    B["Development"] --> B1["VS Code + Claude Code"]
    B --> B2["GitHub"]
    C["Data and storage"] --> C1["Lean data folder for training/backtesting"]
    C --> C2["Redis temporary event stream"]
    C --> C3["PostgreSQL permanent experience database"]
    D["AI and modeling"] --> D1["PyTorch"]
    D --> D2["scikit-learn"]
    D --> D3["NumPy / Pandas"]
    D --> D4["MoE experts and gating network"]
    D --> D5["Multitask heads (direction/magnitude/<br/>volatility) + causal-TCN sequence encoder"]
    E["Monitoring and UI"] --> E1["React/Vite webui — Tracing dashboard (port 3002 dev / 8001 Docker)"]
    E --> E2["FastAPI JSON API (port 8000)"]
    E --> E3["Telegram alerts (V2-19)<br/>notifications/telegram_worker.py"]
```

These two diagrams are the high-level summary. For the full system —
every per-phase "contract" (Observation Mode, Performance Triggers,
Controlled Retraining, 3D Topology, Liquidity Engine, Paper/Live Deployment,
and more), the module map, and an honest analysis of what would need to
change for this to become a genuinely low-latency/HFT system — see
**[`development/v2_architecture.md`](development/v2_architecture.md)**.

**The baseline model can now predict more than direction.** An optional
multi-task model (`train.py::AetherNetMultiTask`, trained by
`train_multitask.py`) predicts next-day direction, return magnitude and
volatility jointly from one shared trunk — the direction-only baseline and
experts are unchanged and still ship independently. All 4 experts also
have their own optional multitask heads (`train.py::_train_expert_multitask()`),
so `moe/gating.py` blends per-expert magnitude/volatility with a
baseline-scale anchor the same weighted-average way it already blends
direction. `main.py` threads the resulting `predicted_return_magnitude`/
`predicted_volatility` through the market analyzer (informational only,
never changes routing) and, opt-in via
`phase_v2.dynamic_risk.use_predicted_volatility`, into position sizing —
replacing the backward-looking `rolling_volatility_20d` average with an
actual forward-looking forecast for that one calculation.

**Regime, liquidity and topology are now genuine model input features,
not just downstream consumers of its output.** Model input dimensionality
grew from 30 to 48: regime one-hot/confidence/trend/risk score, an
asset-intrinsic liquidity spread/dollar-volume estimate, and cross-asset
topology correlation/risk state are all computed offline
(`train.py::add_regime_features()`/`add_liquidity_features()`/
`build_topology_features_by_date()`) and at runtime
(`main.py::_build_model_input()`, reordered so regime is computed
*before* the model runs) with verified train/runtime parity.

**Multi-horizon direction, cross-sectional ranking, correlated-peer
returns and technical indicators (model input 48 → 59).** A root-cause
investigation found every model — baseline, all 4 experts, the multitask
heads, the sequence encoder — sitting at backtest MCC 0.02-0.07 (noise) on
next-day binary direction, and traced (and fixed) real data bugs
confounding those numbers: an unadjusted-split bug in `train.py`'s own
Lean-zip reader (Lean's live/backtest engine was never affected — see
`development/Problems.md` #24) and a data-feed volume-unit discontinuity
that blew up the sequence model's RMSE 31x (#23). Beyond the fixes,
`AetherNetMultiTaskHorizons`/`AetherNetSequenceMultiTaskHorizons` (new
sibling classes to the originals — experts/baseline/gating stay
1d-direction-only by design) add 4 heads: `direction_5d`/`direction_20d`
(longer-horizon direction) and `rank_5d`/`rank_20d` (per-date
cross-sectional percentile rank of forward return — the most learnable
target this investigation found, maps directly onto a long/short
portfolio, evaluated via rank-IC, `train.py::compute_rank_ic()`, not MCC).
11 new scaled input features: 4 correlated-peer lagged-return features
(`topology/market_topology.py`'s `top_peers`/`top_peer_returns`, a genuine
new information channel from correlation data the model previously only
saw as a compressed scalar) and 7 technical indicators (`features/`
package — RSI, ATR%, Bollinger %B, volume z-score, MACD histogram,
distance-from-52-week-high, cross-sectional momentum rank), all computed
identically offline and at runtime by construction (shared pure
functions, not hand-matched duplicated formulas). All new signals are
visible on `/neural-network` and in `*_training_metrics.json`; see
`development/Changelog.md`'s "Frontier-model edge investigation" entry
for the full build and the real rank-IC results.

**`rank_20d` now sizes positions (opt-in).** A follow-up pass wired the
one Phase-4 signal with a statistically significant full-series result —
`rank_20d`, sequence model mean IC `0.073`/t-stat `4.40` — into an actual
trading decision: `risk/position_sizing.py::rank_sizing_multiplier()`
adds a fourth, bounded, direction-preserving factor to the sizing chain,
scaling an already-approved trade UP toward `max_rank_multiplier` (default
`1.25`) when the model predicts this asset near the top of the universe's
20-day forward-return ranking, and DOWN toward `min_rank_multiplier`
(default `0.75`) near the bottom — never flipping direction, same
convention as the existing `topology_sizing_multiplier()`. **Off by
default** (`phase_v2.dynamic_risk.rank_sizing_enabled: false`): the
signal's non-overlapping-date subsample (28 independent 20-day windows)
was not yet independently significant on its own (t-stat `1.20`), so it
ships wired end-to-end but not promoted to on-by-default until validated
on more out-of-sample data. `direction_5d`/`direction_20d`/`rank_5d`
remain informational-only. See `risk/README.md`'s "Cross-sectional
rank_20d → position sizing" section.

**A causal-TCN sequence encoder (Phase 2) now exists alongside the
flat-MLP trunk**, replacing the "zero temporal structure" limitation the
original root-cause investigation flagged — `train.py::AetherNetSequenceMultiTask`,
trained by `train_sequence.py`, over a rolling 30-bar window of
already-computed model inputs. Informational only this pass
(`main.py::_run_sequence_model()` — not yet wired into any trading
decision); see `inference/README.md`'s Phase 2 section for the new
`_conv1d_causal`/`_multihead_attention`/`_softmax`/`_layernorm_axis`
interpreter primitives (each independently verified against real PyTorch
modules).

See `inference/README.md`, `moe/README.md`, `risk/README.md`,
`regime/README.md`, `liquidity/README.md` and `topology/README.md` for
the full contracts, and `development/Changelog.md`'s "Multi-task
prediction" and "Phase 1 remainder + Phase 2" entries for the complete
writeup.

## Universe Size

The trading universe currently spans **30 assets** — 15 stocks/broad-market
ETFs, 10 fixed-income (bond) ETFs, and 5 crypto pairs — defined in
`config.json`'s `phase1.universe.assets` and shared across training,
validation, and backtesting (`phase1.universe.common_window`: `2014-12-01`
to `2021-03-31`). The bond ETF sleeve (Phase 1 of the 5/10 -> 9/10 roadmap,
see [`development/Changelog.md`](development/Changelog.md)) was added
specifically as a new, genuinely different information channel — not more
of the same equity cross-section — and deliberately spans the duration
curve (short/intermediate/long/aggregate) and credit spectrum
(Treasury/investment-grade/high-yield/municipal/emerging-market) so the
yield-curve-slope and credit-spread macro proxies computed from it
(`features/macro_features.py`) are meaningful. Bond ETFs are registered
with `security_type: "equity"` (they trade through Lean's ordinary equity
subscription path, like every other ETF already in the universe, e.g.
SPY/QQQ/IWM/EEM — not a new Lean security type).

| Ticker | Type | Role |
|---|---|---|
| AAPL | Equity | Trading |
| SPY | Equity | Trading |
| QQQ | Equity | Trading |
| IWM | Equity | Trading |
| EEM | Equity | Trading |
| BAC | Equity | Trading |
| IBM | Equity | Trading |
| AIG | Equity | Trading |
| BNO | Equity | Trading |
| FB | Equity | Trading |
| GOOG | Equity | Trading |
| GOOGL | Equity | Trading |
| USO | Equity | Trading |
| WM | Equity | Trading |
| AAA | Equity | Observation-only (thin history) |
| SHY | Equity (Fixed Income ETF) | Trading — short-duration Treasury (1-3y) |
| IEF | Equity (Fixed Income ETF) | Trading — intermediate-duration Treasury (7-10y) |
| TLT | Equity (Fixed Income ETF) | Trading — long-duration Treasury (20y+) |
| AGG | Equity (Fixed Income ETF) | Trading — broad aggregate bond benchmark |
| LQD | Equity (Fixed Income ETF) | Trading — investment-grade corporate |
| HYG | Equity (Fixed Income ETF) | Trading — high-yield corporate |
| TIP | Equity (Fixed Income ETF) | Trading — inflation-protected (TIPS) |
| MBB | Equity (Fixed Income ETF) | Trading — mortgage-backed |
| EMB | Equity (Fixed Income ETF) | Trading — emerging-market sovereign debt |
| MUB | Equity (Fixed Income ETF) | Trading — municipal |
| BTCUSD | Crypto | Trading |
| ETHUSD | Crypto | Observation-only (thin history) |
| LTCUSD | Crypto | Trading |
| XRPUSD | Crypto | Observation-only (thin history) |
| ADAUSD | Crypto | Observation-only (thin history) |

"Observation-only" assets (Phase 9's `asset_quality` gate) are still fed
through the full model/expert/topology pipeline every bar and visible on
the dashboard, but are never sized into real positions — their real
history is too short relative to the training window to be trusted for
trading decisions (see [`development/Changelog.md`](development/Changelog.md)
for the exact row-count thresholds). This is re-evaluated automatically
every time `train.py` rebuilds the dataset, so an asset can move between
these two roles as more history accumulates.

```mermaid
flowchart TD
    DNN(("Baseline DNN<br/>+ MoE Experts<br/>bullish / bearish /<br/>sideways / volatility"))

    subgraph Equities["Equities (15)"]
        AAPL["AAPL"]
        SPY["SPY"]
        QQQ["QQQ"]
        IWM["IWM"]
        EEM["EEM"]
        BAC["BAC"]
        IBM["IBM"]
        AIG["AIG"]
        BNO["BNO"]
        FB["FB"]
        GOOG["GOOG"]
        GOOGL["GOOGL"]
        USO["USO"]
        WM["WM"]
        AAA["AAA"]
    end

    subgraph FixedIncome["Fixed Income ETFs (10)"]
        SHY["SHY"]
        IEF["IEF"]
        TLT["TLT"]
        AGG["AGG"]
        LQD["LQD"]
        HYG["HYG"]
        TIP["TIP"]
        MBB["MBB"]
        EMB["EMB"]
        MUB["MUB"]
    end

    subgraph Crypto["Crypto (5)"]
        BTCUSD["BTCUSD"]
        ETHUSD["ETHUSD"]
        LTCUSD["LTCUSD"]
        XRPUSD["XRPUSD"]
        ADAUSD["ADAUSD"]
    end

    AAPL --- DNN
    SPY --- DNN
    QQQ --- DNN
    IWM --- DNN
    EEM --- DNN
    BAC --- DNN
    IBM --- DNN
    AIG --- DNN
    BNO --- DNN
    FB --- DNN
    GOOG --- DNN
    GOOGL --- DNN
    USO --- DNN
    WM --- DNN
    AAA --- DNN
    SHY --- DNN
    IEF --- DNN
    TLT --- DNN
    AGG --- DNN
    LQD --- DNN
    HYG --- DNN
    TIP --- DNN
    MBB --- DNN
    EMB --- DNN
    MUB --- DNN
    BTCUSD --- DNN
    ETHUSD --- DNN
    LTCUSD --- DNN
    XRPUSD --- DNN
    ADAUSD --- DNN

    classDef hub fill:#1A1A1A,stroke:#FF8C00,color:#FF8C00,stroke-width:2px;
    classDef trading fill:#FF8C00,stroke:#1A1A1A,color:#1A1A1A,stroke-width:1px;
    classDef observation fill:#3A3A3A,stroke:#FF8C00,color:#FF8C00,stroke-width:1px,stroke-dasharray: 4 2;

    class DNN hub;
    class AAPL,SPY,QQQ,IWM,EEM,BAC,IBM,AIG,BNO,FB,GOOG,GOOGL,USO,WM,SHY,IEF,TLT,AGG,LQD,HYG,TIP,MBB,EMB,MUB,BTCUSD,LTCUSD trading;
    class AAA,ETHUSD,XRPUSD,ADAUSD observation;
```

## Project Structure

```text
aether-quant/
├── .github/                     # CI workflows (tests, webui build, release)
├── development/                 # Architecture docs, changelog, problems log, backtest chart
├── data/                        # Local Lean data folder (equities, crypto)
├── data_pipeline/                # Lean-data contract + Yahoo Finance historical backfill
├── analyzer/                    # Central market analyzer (final per-asset decision layer)
├── moe/                         # Mixture-of-Experts gating network
├── experts/                     # Bullish / bearish / sideways / volatility expert models
├── regime/                      # Market regime detection
├── topology/                    # 3D market topology (deterministic SMACOF + learned overlay)
├── liquidity/                   # Liquidity / market-impact engine
├── risk/                        # Dynamic position sizing, leverage, drawdown controls
├── execution/                   # Order gating, paper/live broker readiness, config caching
├── inference/                   # Vectorized neural-network forward-pass interpreter
├── experience/                  # Redis -> PostgreSQL observation/decision history pipeline
├── performance/                 # Performance trigger system (drawdown, Sharpe, regime-shift, ...)
├── retraining/                  # Controlled retraining: plan/train/validate/backtest/promote
├── monitoring/                  # FastAPI JSON API serving runtime state to the webui
├── notifications/               # Telegram alerting worker
├── visualization/               # Shared runtime-state JSON/CSV exports
├── webui/                       # React/Vite dashboard (Overview, Risk, Topology, Neural Network, Tracing)
├── ml/                          # Model weights, datasets, versioned retraining candidates
├── storage/                     # Reserved for future persistent artifact storage
├── requirements/                # All requirements*.txt variants
├── tests/                       # Full pytest suite (828 tests)
├── backtests/                   # Lean backtest run outputs (gitignored)
├── Aether-quant-Obsidian-Vault/ # Auto-generated code-graph / architecture vault
├── main.py                      # Lean algorithm: inference, signal engine, risk controls
├── train.py                     # Training pipeline: dataset build, model training, validation
├── train_topology.py            # Offline trainer for the learned topology overlay
├── train_gating.py              # Offline trainer for the learned gating blend
├── train_multitask.py           # Offline trainer for the joint direction+magnitude+volatility model
├── train_sequence.py            # Offline trainer for the Phase 2 causal-TCN sequence encoder
├── generate_backtest_report.py  # Regenerates this README's Backtest Results section
├── aq_cli.py                    # `aq` convenience CLI
├── config.json                  # Runtime configuration (phase1 / phase_v2 blocks)
├── lean.json                    # Lean engine + brokerage configuration
├── docker-compose.yml           # Local infrastructure (Lean, Redis, PostgreSQL, workers)
└── pyproject.toml               # Package metadata, `aq` entry point, pytest config
```

## Module Documentation

Every package below has its own README with the full detail on what it owns
and how it's wired in — this table is the index.

| Module | What it owns | Docs |
|---|---|---|
| `analyzer/` | Central market analyzer — the final per-asset action categorization layer | [README](analyzer/README.md) |
| `data/` | Local Lean data-folder format documentation | [README](data/README.md) |
| `data_pipeline/` | Lean-data contract + Yahoo Finance historical backfill | [README](data_pipeline/README.md) |
| `execution/` | Order gating, paper/live broker readiness, config-read caching | [README](execution/README.md) |
| `experience/` | Observation/decision history — Redis buffer + PostgreSQL persistence | [README](experience/README.md) |
| `experts/` | Bullish, bearish, sideways, and volatility expert models | [README](experts/README.md) |
| `inference/` | Vectorized forward-pass interpreter for the exported neural networks | [README](inference/README.md) |
| `liquidity/` | Liquidity and market-impact engine | [README](liquidity/README.md) |
| `ml/` | Model & dataset artifacts, including versioned retraining candidates | [README](ml/README.md) |
| `moe/` | Mixture-of-Experts gating network | [README](moe/README.md) |
| `monitoring/` | FastAPI JSON API serving runtime state to the webui | [README](monitoring/README.md) |
| `notifications/` | Telegram alerting worker | [README](notifications/README.md) |
| `performance/` | Performance trigger system (14 trigger functions) | [README](performance/README.md) |
| `regime/` | Market regime detection | [README](regime/README.md) |
| `requirements/` | All `requirements*.txt` variants and what consumes each | [README](requirements/README.md) |
| `retraining/` | Controlled retraining — plan/train/validate/backtest/commit/promote/rollback | [README](retraining/README.md) |
| `risk/` | Dynamic position sizing, leverage caps, drawdown-aware sizing | [README](risk/README.md) |
| `storage/` | Reserved placeholder for future persistent artifact storage | [README](storage/README.md) |
| `tests/` | Pytest suite conventions (828 tests) | [README](tests/README.md) |
| `topology/` | 3D market topology — deterministic SMACOF embedding + learned overlay | [README](topology/README.md) |
| `visualization/` | Shared runtime-state JSON/CSV exports | [README](visualization/README.md) |
| `webui/` | React/Vite dashboard (Overview, Risk, Topology, Neural Network, Tracing) | [README](webui/README.md) |
| `Aether-quant-Obsidian-Vault/` | Auto-generated Obsidian vault mirroring the repo's architecture/code graph | [README](Aether-quant-Obsidian-Vault/README.md) |

## Development Documentation

| Document | Contents |
|---|---|
| [`development/README.md`](development/README.md) | Index of this folder |
| [`development/v2_architecture.md`](development/v2_architecture.md) | The full V2 system architecture: process-flow and tech-stack diagrams, the module map, per-phase "contract" sections, and the HFT-readiness analysis |
| [`development/infrastructure.md`](development/infrastructure.md) | Docker Compose runbook — start commands for every service, SQL inspection snippets, port reference |
| [`development/Changelog.md`](development/Changelog.md) | Detailed, append-only, per-phase build history — what was built, when, and why |
| [`development/Problems.md`](development/Problems.md) | Append-only audit log of bugs and infrastructure issues, each with a severity rating and fixed/open status |

## Backtest Results

<!-- AQ:BACKTEST_START -->
![Backtest equity curve](development/backtest_equity_chart.png)

| Metric | Value |
|---|---|
| Backtest window | 2018-04-01 to 2021-04-02 |
| Sharpe Ratio | -0.758 |
| Net Profit | -4.847% |
| Compounding Annual Return | -1.640% |
| Drawdown | 12.300% |
| Total Orders | 36 |
| Win Rate | 25% |
| Last updated | 2026-07-08 13:10 UTC (auto-generated by `aq backtest`) |
<!-- AQ:BACKTEST_END -->

<details>
<summary><strong>Full Lean statistics</strong> (Sharpe, Sortino, Alpha/Beta, fees, capacity, and everything else Lean reports)</summary>

<!-- AQ:BACKTEST_FULL_STATS_START -->
| Metric | Value |
|---|---|
| Total Orders | 36 |
| Average Win | 0.38% |
| Average Loss | -0.67% |
| Compounding Annual Return | -1.640% |
| Drawdown | 12.300% |
| Expectancy | -0.609 |
| Start Equity | 100000.00 |
| End Equity | 95153.40 |
| Net Profit | -4.847% |
| Sharpe Ratio | -0.758 |
| Sortino Ratio | -0.363 |
| Probabilistic Sharpe Ratio | 0.006% |
| Loss Rate | 75% |
| Win Rate | 25% |
| Profit-Loss Ratio | 0.56 |
| Alpha | -0.034 |
| Beta | 0.047 |
| Annual Standard Deviation | 0.038 |
| Annual Variance | 0.001 |
| Information Ratio | -0.786 |
| Tracking Error | 0.182 |
| Treynor Ratio | -0.603 |
| Total Fees | $25.59 |
| Estimated Strategy Capacity | $2300000.00 |
| Lowest Capacity Asset | BNO UN3IMQ2JU1YD |
| Portfolio Turnover | 0.14% |
| Drawdown Recovery | 32 |
<!-- AQ:BACKTEST_FULL_STATS_END -->

</details>

This section is regenerated automatically every time you run `aq backtest`
(see [`generate_backtest_report.py`](generate_backtest_report.py)) — it
always reflects your most recent successful Lean backtest, reading directly
from Lean's own result JSON (strategy equity curve, its native SPY benchmark
series, and the full statistics block), so it never goes stale as long as
you keep backtesting. Both the chart image and every statistic above are
overwritten on each run — there is no manual step and nothing here can go
stale relative to your last `aq backtest`.

**What this backtest does *not* prove:** a bare `lean backtest .` run
exercises the full inference stack (baseline model, all 4 experts, MoE
gating, regime, topology, liquidity) every bar, but it does **not**
exercise the controlled retraining loop — the "learning while trading"
half of this system's thesis. That loop is a decoupled, asynchronous
pipeline (`main.py` → Redis → experience-worker → Postgres →
performance-trigger-worker → retraining-worker), and a bare backtest run
outside the Docker Compose network can't even reach Redis — events are
dropped with a warning, so nothing reaches Postgres, no performance
trigger can fire, and no retraining ever runs (see
`development/infrastructure.md`). Exercising retraining for real requires
the full Compose stack up (`docker compose up -d redis postgres
experience-worker performance-trigger-worker retraining-worker`) with the
backtest run inside that network, plus an actual trigger condition being
met during the run.

**If `phase_v2.backtest.bypass_safety_gates` is `true`:** this backtest
also does not represent live/paper-deployable behavior. That flag (default
`false`) disables the sticky total-drawdown lock and the regime detector's
drawdown-driven `risk_off` override — both real, designed safety behavior
in live/paper mode — purely to generate enough trade volume for
statistically meaningful backtest metrics (see `development/Problems.md`
#18). A backtest run with this flag set shows the underlying model's
signal quality across more market conditions, not what this system would
have actually done if deployed — in live/paper mode, both gates would have
genuinely halted trading exactly as designed.

## Test Suite

828 tests, one file per source module, run via:

```powershell
aq test
```

which — like the backtest chart above — automatically keeps the badge at
the top of this README in sync with the real pass count every time you run
it. See [`tests/README.md`](tests/README.md) for the suite's conventions.

## CLI Reference

The easiest way to get the `aq` command is straight from PyPI (see
[Download](#download) above) — no source checkout needed:

```powershell
pip install aether-quant
```

For local development (this repo cloned, a virtual environment active),
`pip install -e .` registers the same `aq` command directly from source
instead, without waiting on a PyPI release:

```powershell
pip install -e .
```

Either way, `aq --help` gives the full command list. Every command except
`aq trade-lock` and `aq fetch` is a thin `subprocess` wrapper around a
command already documented elsewhere in this README:

#### `aq train`
```text
aq train [--dataset-only|--init-only|--experts-only|--gating-only|--multitask-only|--sequence-only]
```
Runs `train.py`: builds the dataset and trains the baseline + expert
models. `--gating-only` trains just the learned gating blend
(`train_gating.py`) and installs it straight into active `ml/`,
mirroring what `--experts-only` already does for the expert models — see
`moe/README.md`. `--multitask-only` does the same for the joint
direction+magnitude+volatility model (`train_multitask.py`) — see
`inference/README.md`/`risk/README.md`. `--sequence-only` does the same
for the Phase 2 causal-TCN sequence encoder (`train_sequence.py`) — see
`inference/README.md`.

#### `aq test`
```text
aq test
```
Runs the pytest suite and refreshes this README's test badge.

#### `aq backtest`
```text
aq backtest
```
Runs `lean backtest .` and refreshes this README's [Backtest Results](#backtest-results) section.

#### `aq report`
```text
aq report <backtest-folder> <result-id>
```
Generates Lean's own HTML backtest report (trade blotter, standard Lean
charts) at `backtests/<backtest-folder>/report.html`.

#### `aq api`
```text
aq api
```
Starts the FastAPI monitoring server on `:8001`.

#### `aq webui`
```text
aq webui
```
Starts the webui dev server (`npm run dev`).

#### `aq docker`
```text
aq docker up [--lean|--all]
aq docker build
```
`up` starts local infrastructure (default: Redis + PostgreSQL only).
`build` rebuilds the `aether-quant` app image.

#### `aq config`
```text
aq config [get <dotted.key>|set <dotted.key> <value>|keys [<dotted.prefix>]]
```
Reads or edits `config.json` directly, no manual file editing needed.
Bare `aq config` pretty-prints the whole file; `aq config keys
[<dotted.prefix>]` lists every leaf key path (handy for finding the right
key in a deeply nested file); `aq config get <dotted.key>` prints one
value (scalar, or a whole nested section as JSON); `aq config set
<dotted.key> <value>` writes it — the value is parsed as JSON first (so
`true`/`123`/`0.5`/`["a","b"]` become their real types automatically),
falling back to a plain string otherwise. Every `set` backs up the
previous file to `config.json.bak` first and prints old → new so a
mistake is immediately visible; changing a value's type (e.g. bool →
string) prints a warning but still writes it, since this command
intentionally gives full access to every key, not just a safe subset.

#### `aq lean`
```text
aq lean [get <dotted.key>|set <dotted.key> <value>|keys [<dotted.prefix>]]
```
The exact same `get`/`set`/`keys` tool as `aq config`, just pointed at
`lean.json` (the QuantConnect Lean CLI's own config file — broker
credentials, environments, data providers) instead. `aq lean set
ib-trading-mode live`, `aq lean keys environments.live-paper`, etc.

#### `aq retrain`
```text
aq retrain <plan|train|validate|backtest|commit|promote|rollback|status> [...]
```
Dispatches to `python -m retraining.orchestrator <stage> ...` for a
single manual pipeline stage.

#### `aq trade-lock`
```text
aq trade-lock --on|--off|--auto|--status
```
Manually overrides `main.py`'s sticky total-drawdown trade lock (see
`development/v2_architecture.md`'s Manual Trade-Lock Override Contract).
`--off` deliberately clears an otherwise-permanent lock; `--auto` returns
to fully automatic behavior.

#### `aq fetch`
```text
aq fetch <crypto|stock> --ticker <TICKER> --start <YYYY-MM-DD> --end <YYYY-MM-DD> [--apply]
```
Fetches historical OHLCV from Yahoo Finance for a ticker that isn't in
`config.json` yet, formats it into Lean's zip/CSV convention, and writes
it to the right spot under `data/` (`data/crypto/coinbase/daily/<ticker>_trade.zip`
or `data/equity/usa/daily/<ticker>.zip`). On `--apply`, it also appends a
new asset block to `config.json`'s `phase1.universe.assets[]` — no manual
editing needed. Dry run by default (no `--apply`): reports what would
happen, writes nothing. Never runs `train.py` itself — once applied, run
`python train.py --dataset-only` (then `python train.py` when ready)
yourself to actually train on the new ticker. `crypto`/`stock` today; a
`derivative` asset class is planned for V3.

#### `aq status`
```text
aq status
```
Shows `git status`.

## Release Process

A release is exactly one manual step — deliberately no automatic release on
every push to `main`, only on an explicitly pushed version tag
(`.github/workflows/release.yml`, triggered on `push: tags: ["v*.*.*"]`):

```powershell
git tag v0.1.0
git push origin v0.1.0
```

This then automatically runs (no manual version bump anywhere in the repo —
`pyproject.toml` reads the version straight from the tag via
`setuptools-scm`):

1. The test suite (`pytest`) — a failure blocks the release entirely.
2. PyPI publishing via Trusted Publishing (OIDC) — no PyPI token is stored as a GitHub secret.
3. Docker image build and push to `ghcr.io/leon1706-lol/aether-quant`, tagged with the version number and `:latest`.

**One-time manual setup, before the first tag is ever pushed** (can't be
done from here):

- Create a "Trusted Publisher" on pypi.org for this project (pointing at `leon1706-lol/Aether-quant` + the `release.yml` workflow file).
- After the very first tag push: check the **Packages** tab of this repo to see whether the new `aether-quant` package is private, and switch it to public if needed so `docker pull` works for everyone.

## Runbook

Everyday local commands.

Activate the virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Rebuild training artifacts:

```powershell
python train.py
```

Rebuild only the dataset/scaler/manifest:

```powershell
python train.py --dataset-only
```

Run the tests:

```powershell
pytest tests/
```

Recommended full workflow:

```powershell
python train.py
pytest tests/
aq backtest
aq report <backtest-folder> <result-id>
git status
```

Start a Lean backtest from the project folder:

```powershell
lean backtest .
```

Find a finished backtest:

```powershell
Get-ChildItem .\backtests\<backtest-folder>\*-summary.json
```

Generate the official Lean HTML report:

```powershell
lean report --backtest-results .\backtests\<backtest-folder>\<result-id>.json --report-destination .\backtests\<backtest-folder>\report.html --overwrite
```

Start the webui locally (API server and frontend, two terminals):

```powershell
uvicorn monitoring.api_server:app --port 8001 --reload
```

```powershell
cd webui
npm run dev
```

Then:

```text
http://localhost:3002          (Overview)
http://localhost:3002/risk     (Risk)
```

Check git status before a commit:

```powershell
git status
```

## Roadmap

### V1 — ✅ Finished

The first universe was deliberately small and mixed:

- `AAPL`
- `SPY`
- `QQQ`
- `BTCUSD`

Shared V1 data coverage:

- Start: `2014-12-01`
- End: `2018-08-13`
- Resolution: `Daily`

First windows:

- Training: `2014-12-01` to `2017-06-30`
- Validation: `2017-07-01` to `2017-12-31`
- Backtest: `2018-01-01` to `2018-08-13`

First target definition:

- Target type: next day's direction
- Label: `1` if the next close-to-close return is positive, else `0`

First feature ideas:

- 1d, 5d, and 20d returns
- 5d and 20d volatility
- 5d and 20d momentum
- Daily range and open-close range
- Volume change

Detailed phase results (Phase 2 through Phase 10, Phase V2-1 through Phase
V2-15, Visualization Unification) live in
[`development/Changelog.md`](development/Changelog.md) to keep this README short.

### V3 — 🔜 Incoming Soon

`development/v2_architecture.md`'s own "Why This Is Not HFT, And What It
Would Take" analysis is the honest starting point for what V3 needs to
close — not marketing aspiration, but a concrete gap list the system's own
architecture docs already identify:

- **Tick/L1-L2 market data pipeline** — replacing the daily Lean zip files with a genuinely higher-frequency data source and storage layer.
- **A shorter-horizon model** — a new model operating at sub-second/tick granularity with a much shorter prediction horizon, not a retrained version of today's daily classifier.
- **Real slippage- and latency-aware execution** — an actual fill simulator and limit-order support, replacing today's `SetHoldings`/`Liquidate` market orders with no slippage model wired to fills.
- **A low-latency, event-driven runtime** — replacing the daily-bar `on_data()` callback and the 30s+ polling background workers with something closer to a real-time event loop.
- **Real broker/exchange connectivity beyond paper trading** — building on the credential/readiness groundwork V2-21/V2-22 already laid.
- **Continuous / online retraining** — moving beyond today's offline, cooldown-gated batch retraining pipeline.
- Further out: an expanded asset universe, multi-timeframe ensembles, and reinforcement-learning-based position sizing/execution.

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit your changes following the existing module structure (see [`development/Changelog.md`](development/Changelog.md) for this project's development history)
4. Open a Pull Request

---

<div align="center">
  <sub>Aether Quant</sub>
</div>
