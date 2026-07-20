# infrastructure

Docker Compose connects the local V2 building blocks:

- `lean`: Lean runtime / backtest environment
- `redis`: fast temporary in-memory buffer for signals, trades, and raw metrics
- `postgres`: permanent experience database and later single source of truth for retraining

Grafana used to be part of this stack, but was removed in V2-18 — the webui's tracing page (`/tracing`) now displays the same feeds natively, see `development/v2_architecture.md`.

**Naming**: every container in this stack is `aether-quant-<name>` (e.g.
`aether-quant-postgres`, `aether-quant-redis`, `aether-quant-lean-live`) —
distinct from the sibling `aether-vault-*` project's containers on the
same machine. The app (`engine` service) and every worker service
(`experience-worker`, `performance-trigger-worker`, `telegram-worker`,
`paper-readiness-scheduler`, `retraining-worker`) all run from the same
built image, `aether-quant-engine` — one `Dockerfile`, `docker compose
build engine`, no more per-worker Dockerfiles. See
`requirements/README.md` for why this replaced three separate images.

## Data Flow

1. The live or observation loop produces a signal and immediately writes raw metrics to Redis.
2. Redis temporarily stores the events as a stream or queue, e.g. via `XADD` or `LPUSH`.
3. A worker reads from Redis decoupled, e.g. via `XREAD` or `BLPOP`.
4. The worker writes events to PostgreSQL in batches.
5. Controlled retraining uses PostgreSQL as the stable data source.

## Start

```powershell
docker compose up -d redis postgres
```

Lean is deliberately started via a Compose profile so the container doesn't automatically run permanently:

```powershell
docker compose --profile lean up -d
```

## Starting the Experience Worker

Start the worker with Redis and PostgreSQL:

```powershell
docker compose up -d redis postgres experience-worker
docker compose logs -f experience-worker
```

Process a single batch (useful after a backtest):

```powershell
docker compose run --rm experience-worker python -m experience.postgres_worker --once
```

## PostgreSQL — Inspecting Experience Events

```powershell
docker exec -it aether-quant-postgres psql -U aether -d aether_quant
```

```sql
-- Row count
SELECT COUNT(*) FROM experience_events;

-- Last 10 events
SELECT event_id, created_at, ticker, signal, action, confidence
FROM experience_events
ORDER BY created_at DESC LIMIT 10;

-- JSONB query: portfolio_value
SELECT event_id, payload -> 'portfolio' ->> 'total_value' AS portfolio_value
FROM experience_events ORDER BY created_at DESC LIMIT 5;
```

Dead-letter stream in Redis:

```powershell
docker exec -it aether-quant-redis redis-cli XLEN aether:experience:deadletter
docker exec -it aether-quant-redis redis-cli XRANGE aether:experience:deadletter - + COUNT 5
```

## Using Your Own Images

If you have your own Redis, PostgreSQL, or Lean images, set the image names before starting:

```powershell
$env:REDIS_IMAGE="your-redis-image:tag"
$env:POSTGRES_IMAGE="your-postgres-image:tag"
$env:LEAN_IMAGE="your-lean-image:tag"   # defaults to quantconnect/lean:17900, a
                                          # PINNED build (aq_cli.py::PINNED_LEAN_ENGINE_IMAGE,
                                          # development/Problems.md #40) - NOT :latest,
                                          # so it never silently re-pulls the ~42GB
                                          # image against an already-cached one. Override
                                          # here to deliberately move to a newer build.
docker compose --profile lean up -d
```

## Running Observation Mode (V2-15)

Observation Mode runs the algorithm as if live (signals, risk, regime,
topology, liquidity, MoE all stay active), but never places a real order —
every decision is instead replicated in a simulated portfolio
(`experience/simulated_portfolio.py`) and logged to Redis/PostgreSQL as usual.

**1. Enable the mode** — in `config.json`:

```json
"phase_v2": {
  "runtime": {
    "mode": "observation",
    "allow_live_orders": false
  }
}
```

`allow_live_orders` stays `false` — Observation Mode ignores this flag
anyway and always blocks real orders, but it should never accidentally be
`true` for this mode. The committed default is `"backtest"` (unchanged
behavior for `lean backtest .`); switch explicitly to `"observation"` for
Observation Mode and switch it back afterward when running a normal backtest.

**2. Startup order:**

```powershell
docker compose up -d redis postgres experience-worker
lean backtest .
```

Note: a single `lean backtest .` run (Lean CLI, not a Compose service)
starts its own Docker container without access to the host's
`localhost:6380`. For a real Redis connection during the run, either use
`docker compose --profile lean up -d` (container in the same Compose
network, `AETHER_REDIS_URL=redis://redis:6379/0`) or accept that
`ExperienceQueue` just logs a warning and skips the push when Redis is
unreachable — the trading/simulation itself is never blocked by this, only
the Redis/Postgres events for that run are missing.

**3. PostgreSQL — inspecting observation events:**

```sql
SELECT COUNT(*) FROM experience_events WHERE mode = 'observation';

SELECT event_id, created_at, ticker, signal, action,
       payload -> 'portfolio' ->> 'total_value' AS simulated_equity
FROM experience_events
WHERE mode = 'observation'
ORDER BY created_at DESC LIMIT 10;
```

**4. Open the dashboard:**

```powershell
python -m uvicorn monitoring.api_server:app --port 8001 --reload
cd webui && npm run dev
```

In the webui (`http://localhost:3002`), the new "Observation Mode" panel
(`webui/src/components/monitoring/ObservationPanel.tsx`) shows the yellow
"SIMULATED - NOT REAL TRADES" banner, simulated equity/exposure/drawdown/
turnover, Sharpe, signal distribution, and "Rejected By Reason". The same
data is also available as files under
`visualization/grafana/observation_summary.json` and
`visualization/grafana/observation_equity_curve.csv`, or via the API at
`/api/grafana/observation-summary` and `/api/grafana/observation-equity-curve`.

**5. Ready for paper trading?** Automated since V2-21 instead of a purely
manual checklist — see "Running Paper Trading (V2-21)" below for the full
flow. Short version: `aq paper-readiness` automatically evaluates 4 of the
following 5 points
(`execution/paper_readiness.py::evaluate_observation_readiness()`); only
the last one deliberately remains a manual decision:

- Sufficient observation volume (`count_observations` >= `phase_v2.paper_trading.readiness_thresholds.min_observations`).
- `simulated_max_drawdown` no worse than `max_simulated_drawdown_floor`.
- `rejected_by_reason` doesn't show a dominant rejection cause above
  `max_single_rejection_reason_share` (e.g. constantly
  `liquidity_blocked_insufficient_volume_simulate_instead` for core assets).
- `simulated_sharpe` is above `min_simulated_sharpe`.
- **Stays manual:** reviewing the trade history
  (`SimulatedPortfolioState.trade_log` or the experience events) for
  plausible entry/exit prices — confirmed via
  `phase_v2.paper_trading.manual_review_confirmed`.

## Checking Performance Triggers (V2-16)

The trigger worker watches `experience_events` (not just the current run)
and durably writes detected warnings/retrain candidates into its own
`performance_triggers` table. Phase 16 doesn't retrain anything itself —
`retrain_candidate` is only a flag for Phase 17.

**1. Start the worker** — needs only PostgreSQL, no Redis (the worker reads
`experience_events` but never writes to the Redis stream):

```powershell
docker compose up -d redis postgres performance-trigger-worker
docker compose logs -f performance-trigger-worker
```

**2. Process a single batch** (useful after a backtest):

```powershell
docker compose run --rm performance-trigger-worker python -m performance.trigger_worker --once
```

**3. PostgreSQL — inspecting triggers:**

```sql
SELECT COUNT(*) FROM performance_triggers;

SELECT trigger_type, severity, scope, message, retrain_candidate, created_at
FROM performance_triggers ORDER BY created_at DESC LIMIT 10;

-- Retrain candidates only
SELECT * FROM performance_triggers WHERE retrain_candidate = true ORDER BY created_at DESC;
```

**4. Dashboard:** same `uvicorn`/`npm run dev` startup as Observation Mode.
The new "Performance Triggers" panel
(`webui/src/components/monitoring/PerformanceTriggersPanel.tsx`) sits at
the very top of the right column — retrain-candidate banner, severity
distribution, last trigger, and trigger-type breakdown. The same data
(only the current, in-memory run — not the durable table) is also
available as a file under
`visualization/grafana/performance_triggers.json`, or via the API at
`/api/grafana/performance-triggers`.

## Running Controlled Retraining (V2-17)

`retraining/` reads `retrain_candidate = true` rows from the durable
`performance_triggers` table, trains a candidate model in isolation under
`ml/versions/<version_id>/` when needed, validates/backtests it against the
active model, commits it to Aether-Vault, and only then takes it over (or
rolls it back). Since V2-22 the worker **auto-promotes** by default —
`phase_v2.retraining.worker.auto_promote` is `true` — as long as
`phase_v2.runtime.mode` isn't `"live"`: once live trading is active,
`phase_v2.retraining.worker.auto_promote_blocked_in_live_mode` (default
`true`) still forces a manual promotion (see the Live Deployment Contract
in `v2_architecture.md`). Manual promotion is always available via
`python -m retraining.orchestrator promote --version-id <uuid>`.

**1. Start the worker** (needs only PostgreSQL, no Redis — but unlike
`experience-worker`/`performance-trigger-worker`, the image needs the full
training stack, since `train()` invokes `train.py --candidate` via subprocess):

```powershell
docker compose up -d postgres retraining-worker
docker compose logs -f retraining-worker
```

**2. Process a single cycle** (useful after a backtest or for manual testing):

```powershell
docker compose run --rm retraining-worker python -m retraining.worker --once
```

**3. Run individual stages manually/staged** — independent of whether the
worker is running (carry `retraining_id`/`version_id` over from the
previous step). `train_topology`/`train_gating`/`train_multitask`/
`train_sequence` are each independently best-effort — a failure in any one
of them is logged and swallowed, never rejects the primary candidate — and
individually toggle-able via `config.json`'s
`phase_v2.retraining.{topology_training,gating_training,multitask_training,sequence_training}.enabled`:

```powershell
python -m retraining.orchestrator plan
python -m retraining.orchestrator train --retraining-id <id> --version-id <uuid>
python -m retraining.orchestrator train_topology --retraining-id <id> --version-id <uuid>
python -m retraining.orchestrator train_gating --retraining-id <id> --version-id <uuid>
python -m retraining.orchestrator train_multitask --retraining-id <id> --version-id <uuid>
python -m retraining.orchestrator train_sequence --retraining-id <id> --version-id <uuid>
python -m retraining.orchestrator validate --retraining-id <id> --version-id <uuid>
python -m retraining.orchestrator backtest --retraining-id <id> --version-id <uuid>
python -m retraining.orchestrator commit --retraining-id <id> --version-id <uuid>
python -m retraining.orchestrator promote --version-id <uuid>
python -m retraining.orchestrator rollback --to-version-id <uuid>
python -m retraining.orchestrator status
```

Note: `ml/expert_models/<name>/multitask_model.json` (the per-expert
multitask heads) is not part of this candidate/rollback system —
`retraining/artifacts.py` doesn't track it, so expert model promotion
follows its own separate, pre-existing path. Only the baseline-scale
`multitask_model.json`/`sequence_model.json` are versioned/rolled-back
through `commit`/`promote`/`rollback` here (`OPTIONAL_MULTITASK_FILES`/
`OPTIONAL_SEQUENCE_FILES` in `retraining/artifacts.py`).

A real end-to-end cycle exercising all of the above against live
PostgreSQL/Aether-Vault is something you run yourself in your own
environment (step 1 above gets the stack up) — `tests/test_retraining_orchestrator.py`
covers each stage (including `train_multitask`/`train_sequence` and their
artifacts surviving `commit()`'s hashing) against a mocked subprocess/DB,
which is the level of verification this repo keeps in its own test suite.

**4. Turn retraining off entirely** (without touching the container) — in
`config.json`:

```json
"phase_v2": {
  "retraining": {
    "enabled": false
  }
}
```

**5. PostgreSQL — inspecting model versions and retraining events:**

```sql
SELECT model_version_id, status, aether_vault_commit, created_at FROM model_versions ORDER BY created_at DESC;

SELECT retraining_id, status, reason, candidate_version_id, created_at FROM retraining_events ORDER BY created_at DESC LIMIT 10;
```

**6. Dashboard:** same `uvicorn`/`npm run dev` startup as Observation Mode.
The new "Retraining Status" panel
(`webui/src/components/monitoring/RetrainingStatusPanel.tsx`) sits
directly below the Performance Triggers panel — active/candidate version,
validation status, vault commit short hash, last trigger, and rollback
availability. Unlike `performance_triggers`, there is no in-memory
approximation from `main.py` here (it never holds its own Postgres
connection) — `visualization/grafana/retraining_status.json` is the only
source, written by `retraining/status_export.py` and merged in via
`/api/grafana/retraining-status` or server-side into `/api/state`.

## Running Telegram Alerts (V2-19)

`notifications/telegram_worker.py` sends Telegram messages for two
channels: every `performance_triggers` row from
`phase_v2.telegram.min_severity_for_trigger_alert` up (not just drawdown —
risk lock, regime shift, liquidity, Sharpe/win-rate/confidence, and
topology triggers come along automatically), plus a session summary per
trading day (`event_type="session_summary"` in `experience_events`, pushed
by `main.py` on session rollover).

**1. Set the bot token/chat ID** — `.env` (see `.env.compose.example`):

```
AETHER_TELEGRAM_BOT_TOKEN=<your-bot-token>
AETHER_TELEGRAM_CHAT_ID=<your-chat-id>
```

Without these two values, the worker keeps running as a safe no-op (every
`send_message()` returns `False`, logs a WARNING, blocks nothing).

**2. Start the worker** (needs only PostgreSQL, no Redis):

```powershell
docker compose up -d postgres telegram-worker
docker compose logs -f telegram-worker
```

**3. Process a single batch:**

```powershell
docker compose run --rm telegram-worker python -m notifications.telegram_worker --once
```

**4. PostgreSQL — inspecting watermarks:**

```sql
SELECT * FROM telegram_alert_watermark;
```

**5. Turn alerts off entirely** (without touching the container) — in
`config.json`:

```json
"phase_v2": {
  "telegram": {
    "enabled": false
  }
}
```

## Running the Yahoo Finance Backfill (V2-19.5)

`data_pipeline/yfinance_backfill.py` is a manual offline script — not a
Docker service, never runs automatically. `yfinance` must be installed
locally (`pip install -r requirements/requirements-dev.txt`).

```powershell
# Dry run - writes nothing, only shows the plan
python -m data_pipeline.yfinance_backfill --tickers ETHUSD LTCUSD

# Actually write
python -m data_pipeline.yfinance_backfill --tickers ETHUSD LTCUSD --apply
```

`config.json`'s `available_from`/`available_to` are **never** changed
automatically by this — the script only prints the suggested new values at
the end; these must be entered by hand for
`train.py::build_asset_quality()` to actually count the extra history.

## Running Paper Trading (V2-21)

The target architecture is Lean's built-in `PaperBrokerage` (`lean.json`'s
`live-paper` environment) — **no** real IBKR paper account needed. The
only external dependency is a live market-data feed.

**1. Check the prerequisite — live market-data access:**

Either a QuantConnect cloud login (`lean login`, then `lean whoami` to
confirm) or a self-configured provider (e.g. fill in `iex-cloud-api-key`
or `polygon-api-key` in `lean.json` and set `data-queue-handler` in
`lean.json`'s `live-paper` environment accordingly). This can't be checked
automatically (a QC login lives outside this repo) — confirm by hand, then
set `phase_v2.paper_trading.live_data_provider_configured` to `true` in
`config.json`.

**2. Run the readiness report:**

```powershell
aq paper-readiness
```

Checks `phase_v2.paper_trading`'s broker configuration (brokerage set,
live data provider confirmed, manual review confirmed) and evaluates
Observation Mode data (`count_observations`, `simulated_sharpe`,
`simulated_max_drawdown`, dominant `rejected_by_reason`) against
`phase_v2.paper_trading.readiness_thresholds`. Exit code `1` while not
ready — the result is also available at
`visualization/grafana/paper_readiness_report.json`,
`/api/grafana/paper-readiness`, and the "Paper Trading Readiness" webui panel.

**3. After manually reviewing the trade history** (the one point
`aq paper-readiness` deliberately doesn't automate) — in `config.json`:

```json
"phase_v2": {
  "runtime": { "mode": "paper", "allow_live_orders": true },
  "paper_trading": {
    "live_data_provider_configured": true,
    "manual_review_confirmed": true
  }
}
```

**4. Start the paper session** (its own, continuously running service,
unlike the existing `lean` service, which only provides `sleep infinity`
for ad-hoc backtests):

```powershell
docker compose up -d redis postgres experience-worker
docker compose --profile lean-live up -d
docker compose logs -f aether-quant-lean-live
```

**Caution:** `lean live deploy`'s exact CLI flags were not verified against
an installed Lean CLI in this session (`docker-compose.yml`'s `lean-live`
service assumes `lean live deploy . --environment
${LEAN_LIVE_ENVIRONMENT:-live-paper}`) — check `lean live deploy --help`
once before production use.

## Running Live Deployment (V2-22)

Purely structural — this phase didn't set up or test any real broker
credentials. Flow once a real IBKR (or other Lean-supported) live account
is available:

**1. Confirm the paper track record** — `aq paper-readiness` should have
consistently reported "ready" over a meaningful period before real capital
is involved.

**2. Store credentials** — two equivalent ways
(`execution/live_credentials_io.py::load_live_credentials()` tries both,
`ib_config.py` first):

```powershell
# Way A: .env.live (copied from .env.live.example, never commit)
cp .env.live.example .env.live
# fill in AETHER_IB_ACCOUNT / AETHER_IB_USER_NAME / AETHER_IB_PASSWORD

# Way B: ib_config.py in the repo root (gitignored)
# IB_ACCOUNT = "..."; IB_USER_NAME = "..."; IB_PASSWORD = "..."; IB_TRADING_MODE = "live"
```

This is pure preflight validation for `execution/paper_readiness.py`'s
`evaluate_live_broker_config()`. Lean itself additionally needs the fields
in its own config (`ib-account`, `ib-user-name`, `ib-password`,
`ib-trading-mode`), since Lean never reads `config.json`/`.env.live` — but
**do not hand-edit them into `lean.json`**: that file is tracked in git (so
everyone who clones gets the working config structure), and a populated
secret field there is one `git add` away from publishing a live broker
password. Lean also does **not** expand `${ENV_VAR}` inside `lean.json` —
the literal string would be sent to the broker. Instead render a gitignored
copy with the secrets filled in:

```powershell
aq render-lean-config      # .env.live + AETHER_* env vars -> lean.live.json
```

That reads the same `AETHER_*` vars as above (see `.env.live.example` for
the full list, including the `AETHER_POLYGON_API_KEY` /
`AETHER_IEX_CLOUD_API_KEY` data-feed keys) and overlays them onto the empty
tracked `lean.json`, writing `lean.live.json` (gitignored). It prints only
which *fields* were filled, never the values. Deploy against it:

```powershell
lean live deploy --lean-config lean.live.json ...
```

`aq backtest` is unaffected and keeps using the plain, all-empty `lean.json`
— backtests need no credentials. See `execution/lean_config_render.py`.

**Enable the secret-commit guard once per clone** (opt-in, so a fresh
checkout is never surprised by a hook):

```powershell
git config core.hooksPath .githooks
```

`.githooks/pre-commit` then runs `aq secrets-check`, which fails the commit
if `lean.json` has a populated secret field or a real `.env` is tracked. Run
it by hand anytime with `aq secrets-check`.

**2b. Set a real database password.** The `aether_dev_password` default is
published in this repo, so live mode **refuses to start** while the Postgres
DSN still contains it (`execution/live_credentials.py::postgres_dsn_is_live_safe`,
enforced via `evaluate_live_broker_config()` → reason
`live_broker_config_unsafe_db_password`). Set `POSTGRES_PASSWORD` in `.env`
before going live. Note the compose DB/Redis ports are published on
`127.0.0.1` only, so they are reachable from this host but never from the
LAN — containers still reach them internally as `redis:6379`/`postgres:5432`.

**3. Set the live risk ceiling** — in `config.json`:

```json
"phase_v2": {
  "live": {
    "max_allowed_daily_drawdown_pct": 0.05,
    "max_allowed_total_drawdown_pct": 0.15
  }
}
```

`main.py`'s actual `max_daily_drawdown_pct`/`max_total_drawdown_pct`
(`phase6.risk`) must stay below these, otherwise
`evaluate_live_risk_posture()` permanently blocks the broker check.

**4. Switch over and start:**

```powershell
# config.json: phase_v2.runtime.mode = "live"
$env:LEAN_LIVE_ENVIRONMENT = "live-interactive"
docker compose --profile lean-live up -d
docker compose logs -f aether-quant-lean-live
```

**5. Monitor:** Telegram (V2-19) alerts on `critical` triggers, including
the new `live_order_permission_blocked_trigger` — fires when `mode ==
"live"` but `execution_note`s still show `simulated_*` (check broker
credentials/`allow_live_orders`/risk lock). Model promotion stays forced
manual in this mode
(`phase_v2.retraining.worker.auto_promote_blocked_in_live_mode`, default
`true`) — `aq retrain promote --version-id <uuid>` after review.

## Cloud Training via GitHub Codespaces

Model training (`aq train` / `python train.py`, all 8 model artifacts:
baseline + 4 experts + multitask + sequence + gating) is CPU-bound and
memory-hungry enough that it can take **hours of wall-clock time while
barely consuming CPU-seconds** on a 4GB-RAM dev machine — the process
isn't crashing, it's thrashing (see `development/Problems.md` #50/#52 for
the measured evidence: ~800 CPU-seconds consumed over ~4 hours of
wall-clock). **GitHub Codespaces solves exactly this one problem** — a
free-tier (2-core/8GB) cloud container reachable over SSH, used purely as
disposable training compute. It does **not** replace local Lean
backtesting (see the limitation below).

**One-time setup** — `.devcontainer/devcontainer.json` at the repo root:

```json
{
    "name": "Aether Quant",
    "image": "mcr.microsoft.com/devcontainers/python:3.11",
    "features": {
        "ghcr.io/devcontainers/features/sshd:1": {
            "version": "latest"
        }
    },
    "hostRequirements": {
        "cpus": 2,
        "memory": "8gb"
    },
    "postCreateCommand": "pip install torch --index-url https://download.pytorch.org/whl/cpu && pip install -r requirements/requirements.txt && pip install -r requirements/requirements-dev.txt"
}
```

Two non-obvious gotchas this config exists to avoid:

- **Do not add the `docker-in-docker` feature.** Both v1 and v2 of that
  feature silently make Codespaces build from an **Alpine** base instead
  of the `image` field above, regardless of what's specified — confirmed
  via 5 systematic A/B rebuild tests (see `development/Problems.md`, the
  Codespaces entry). The practical consequence: **Lean/Docker backtests
  cannot run inside a Codespace at all** — even manually installing
  `docker.io` and starting `dockerd` fails (`iptables: Permission denied`,
  `mount overlay: operation not permitted`), because Codespaces containers
  are unprivileged by default and only that broken feature grants the
  needed capabilities. Training (pure Python/PyTorch, no Docker) is
  entirely unaffected by this and is the only heavy task this workflow
  offloads.
- **`sshd` feature is required** for `gh codespace ssh` specifically (VS
  Code's own tunnel-based Remote-Explorer connection doesn't need it, but
  the `gh` CLI's SSH path does — the base Debian image has no SSH server).
- Bare `pip install torch` resolves the CUDA build on Linux, which then
  fails to import at all on a GPU-less Codespace
  (`OSError: libtorch_global_deps.so: cannot open shared object file`);
  the explicit `--index-url .../whl/cpu` avoids it.

**Workflow, once the Codespace exists:**

```powershell
# Create (only once; reuse the same Codespace afterward)
gh codespace create --repo <owner>/Aether-quant --branch main --machine basicLinux32gb

# Connect
gh codespace ssh -c <codespace-name>

# Inside the Codespace: run training exactly like locally
cd Aether-quant
python train.py                 # or python train.py --multitask-only, etc.

# Back on your local machine: pull the trained artifacts down
gh codespace cp -e "remote:Aether-quant/ml/*.json" ./ml/ -c <codespace-name>

# When done training, stop billing (Codespaces only bills while running)
gh codespace stop -c <codespace-name>
```

`ml/` model artifacts are gitignored (see `.gitignore` — every generated
`ml/*.json`/`.pkl` file, not just the baseline ones), so **no trained
weights or datasets ever need to touch the public GitHub repo** to move
between the Codespace and your local machine — `gh codespace cp` copies
files directly over the same SSH connection, entirely outside git.
`data/` and `ml/datasets/` (raw bars, built training rows) are handled the
same way: copied up once via `gh codespace cp` in the other direction,
never committed.

## Connecting Between Containers

Within the Compose network, services use their service names:

- Redis: `redis://redis:6379/0`
- PostgreSQL: `postgresql://aether:aether_dev_password@postgres:5432/aether_quant`

From Windows, you reach the ports by default like this (remapped since
V2-17 so they don't collide with the separate Aether-Vault Compose stack):

- Redis: `localhost:6380`
- PostgreSQL: `localhost:5433`
- `engine` (FastAPI + webui bundle): `http://localhost:8001`
