# infrastructure

Docker Compose connects the local building blocks:

- `lean`: Lean runtime / backtest environment
- `redis`: fast temporary in-memory buffer for signals, trades, and raw metrics
- `postgres`: permanent experience database and later single source of truth for retraining

Grafana used to be part of this stack, but was removed — the webui's tracing page (`/tracing`) now displays the same feeds natively, see `development/architecture.md`.

**Naming**: every container in this stack is `aether-quant-<name>` (e.g.
`aether-quant-postgres`, `aether-quant-redis`, `aether-quant-lean-live`) —
distinct from the sibling `aether-vault-*` project's containers on the
same machine. The app (`engine` service) and every worker service
(`experience-worker`, `performance-trigger-worker`, `telegram-worker`,
`paper-readiness-scheduler`, `retraining-worker`, `audit-worker`) all run
from the same
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

## Running Observation Mode

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

**On a memory-constrained machine, start with just `redis` up** (not the
full `postgres`/`experience-worker` stack) for the actual backtest run,
then bring `postgres`/`experience-worker` up afterward to drain the
queued Redis stream — `experience_events` uses a genuine Redis Stream
(`XADD`/consumer-group `XREADGROUP`), so nothing is lost by draining it
after the fact rather than during. Verified directly: running the full
stack concurrently with a real Lean backtest caused repeated out-of-memory
crashes on a 4GB dev machine, each one earlier than the last; redis-only
survived a full run.

**2. Startup order:**

```powershell
docker compose up -d redis postgres experience-worker
```

**A bare `lean backtest .` run's own container cannot reach Redis by
default — and the `docker compose --profile lean` service cannot help,
because it has no working `lean` CLI inside it at all** (verified
directly: it's the bare `quantconnect/lean` engine image, a .NET runtime
with no Python `lean` package — `docker compose run --rm lean lean
backtest .` fails outright, regardless of command/entrypoint overrides).
`lean backtest .` (the Lean CLI on your host, the same one `aq backtest`
uses) spawns its **own**, separate Docker container that isn't joined to
this Compose stack's network, so its `localhost` is its own loopback, not
the host's.

The verified, working fix: pass `--extra-docker-config` (a real Lean CLI
flag — JSON in docker-py's `containers.run()` shape) to inject the
compose-published Redis port via Docker Desktop's `host.docker.internal`
DNS name:

```powershell
lean backtest . --image quantconnect/lean:17900 --% --extra-docker-config "{\"environment\": {\"AETHER_REDIS_URL\": \"redis://host.docker.internal:6380/0\"}}"
```

The `--%` stop-parsing token before `--extra-docker-config` and the
backslash-escaped quotes are both load-bearing on Windows PowerShell —
without `--%`, PowerShell's own re-quoting silently strips the embedded
double quotes before Lean's CLI ever sees them, and the JSON fails to
parse. If Redis is unreachable for any reason, `ExperienceQueue` just
logs a warning and skips the push — the trading/simulation itself is
never blocked, only the Redis/Postgres events for that run are missing.

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

**5. Ready for paper trading?** Automated instead of a purely
manual checklist — see "Running Paper Trading" below for the full
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

## Checking Performance Triggers

The trigger worker watches `experience_events` (not just the current run)
and durably writes detected warnings/retrain candidates into its own
`performance_triggers` table. This layer doesn't retrain anything itself —
`retrain_candidate` is only a flag for controlled retraining.

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

## Running Controlled Retraining

`retraining/` reads `retrain_candidate = true` rows from the durable
`performance_triggers` table, trains a candidate model in isolation under
`ml/versions/<version_id>/` when needed, validates/backtests it against the
active model, commits it to Aether-Vault, and only then takes it over (or
rolls it back). The worker **auto-promotes** by default —
`phase_v2.retraining.worker.auto_promote` is `true` — as long as
`phase_v2.runtime.mode` isn't `"live"`: once live trading is active,
`phase_v2.retraining.worker.auto_promote_blocked_in_live_mode` (default
`true`) still forces a manual promotion (see the Live Deployment Contract
in `architecture.md`). Manual promotion is always available via
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

## Running Telegram Alerts

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

## Running the Yahoo Finance Backfill

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

## Running Paper Trading

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

## Running Live Deployment

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

**5. Monitor:** Telegram alerts on `critical` triggers, including
the new `live_order_permission_blocked_trigger` — fires when `mode ==
"live"` but `execution_note`s still show `simulated_*` (check broker
credentials/`allow_live_orders`/risk lock). Model promotion stays forced
manual in this mode
(`phase_v2.retraining.worker.auto_promote_blocked_in_live_mode`, default
`true`) — `aq retrain promote --version-id <uuid>` after review.

## Cloud Training via GitHub Codespaces

**Standing rule: all model training runs here, never locally**, even
though local Docker/Lean work fine — this dev machine's RAM is the
constraint, not a technical requirement. Model training (`aq train` /
`python train.py`, all model artifacts: baseline + 4 experts + multitask
+ sequence + gating + topology + RL sizing) is CPU-bound and
memory-hungry enough that it can take **hours of wall-clock time while
barely consuming CPU-seconds** on a 4GB-RAM dev machine — the process
isn't crashing, it's thrashing (see `development/Problems.md` #50/#52 for
the measured evidence: ~800 CPU-seconds consumed over ~4 hours of
wall-clock). **GitHub Codespaces solves exactly this one problem** — a
free-tier (2-core/8GB) cloud container reachable over SSH, used purely as
disposable training compute. This training Codespace has no Docker; Lean
backtests run on a separate, temporary Docker-in-Docker Codespace since
V6.2.0 (see "Lean on a DinD Codespace" below).

**Before training, sync anything the Codespace doesn't have yet**
(tracked-but-uncommitted changes, or gitignored-but-needed data like a
freshly-exported experience-events dump) via `gh codespace cp`. **After
training, pull the resulting `ml/` artifacts back** the same way. **Stop
the Codespace** (`gh codespace stop`) whenever it isn't actively
training — every core-hour and GB of storage bills the owner's monthly
budget (AGENTS.md rule 13).

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

- **Do not add the `docker-in-docker` feature to this training
  container.** On the `mcr.microsoft.com/devcontainers/python:3.11` image
  it made Codespaces build from an Alpine base (5 A/B rebuilds), and a
  manual `dockerd` fails unprivileged. Lean gets its own container
  instead: `.devcontainer/dind-v1-test/` (`python:3.11-bookworm` +
  `docker-in-docker:2`) works, see "Lean on a DinD Codespace".
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

**Before training**, sync anything the Codespace doesn't have yet
(gitignored-but-needed data, uncommitted source changes):

```powershell
gh codespace cp -c <codespace-name> -r .\ml remote:Aether-quant\ml
```

**For large/many-file transfers** (walk-forward artifact trees, batch
source syncs), `gh codespace cp -r` is unreliable — observed dropping
files silently mid-batch with no non-zero exit code. Archive first, copy
the single tarball, extract locally, and always verify file presence/mtime
afterward:

```powershell
gh codespace ssh -c <codespace-name> -- "cd Aether-quant && tar czf /tmp/aether-quant-ml.tgz ml"
gh codespace cp -c <codespace-name> remote:/tmp/aether-quant-ml.tgz .\aether-quant-ml.tgz
tar -xzf .\aether-quant-ml.tgz
```

`ml/` model artifacts are gitignored (see `.gitignore` — every generated
`ml/*.json`/`.pkl` file, not just the baseline ones), so **no trained
weights or datasets ever need to touch the public GitHub repo** to move
between the Codespace and your local machine — `gh codespace cp` copies
files directly over the same SSH connection, entirely outside git.
`data/` and `ml/datasets/` (raw bars, built training rows) are handled the
same way: copied up once via `gh codespace cp` in the other direction,
never committed.

**`gh codespace cp -r` is unreliable for large or multi-file transfers** —
observed dropping files silently mid-batch (TLS handshake timeouts) with
no non-zero exit code. For anything beyond a handful of small files
(walk-forward run artifacts, a batch of new source files), `tar czf` on
the Codespace, copy the single tarball down with a plain `gh codespace cp`,
extract locally — and always verify file presence/mtime afterward rather
than trusting "no error" from the copy alone. A full six-window walk-forward
run (`aq train --walk-forward --include-multitask --include-sequence
--mode expanding`) takes roughly an hour on the free-tier machine and
produces a multi-gigabyte artifact tree; pull only `walk_forward_summary.json`
day-to-day and fetch the full per-window tree via the tarball approach only
when the individual models are actually needed locally.

### Repeatable sync and retrain (V5.6.0)

```powershell
.\scripts\codespace_sync.ps1 -Mode push                       # one tarball, scp over `gh codespace ssh --config`, sha256-verified
.\scripts\codespace_sync.ps1 -Mode status                     # key-file hashes, local vs Codespace
.\scripts\codespace_sync.ps1 -Mode pull -Candidate <ids...>   # ml/ (minus versions) + the named ml/versions/<id> dirs
.\scripts\codespace_sync.ps1 -Mode stop
```

On the Codespace (`nohup`, log in `ml/retrain_<tag>_{a,b}.log`): `bash scripts/codespace_retrain_a.sh <tag>` (factor-file audit,
dataset + baseline + experts, parity audit, multitask control x2 seeds + four single-change variants, comparison on
VALIDATION IC) then `bash scripts/codespace_retrain_b.sh <tag> <winner>` (sequence, gating, RL sizing with penalty sweep,
resumable walk-forward). Things the first full run taught:

- **The VM reboots roughly hourly** (uptime resets, `/tmp` and background jobs are lost). Everything long must be resumable:
  `python train.py --walk-forward ... --resume-run-id <id>` skips windows with a `window_result.json` (the run id is logged as
  `walk-forward run id: ...`); a killed stage A is finished by running the missing variant and the comparison by hand.
- **Disk is tight (32 GB):** old walk-forward trees hold ~2.2 GB of regenerable `window_*/full_dataset.csv` each; delete those
  (keep models/metrics/summary) before a retrain.
- **`data/` must be identical on both sides** — a push overlays but never deletes. Three FRED CSVs that existed only on the
  Codespace made four model features real in training and 0.0 in every Lean run (Problems #141); `status` plus a file-list diff
  catches that class.
- Windows OpenSSH only for the scripts' `ssh` calls (the Git-Bash `ssh` cannot parse the `gh` ProxyCommand); pipe remote scripts
  through `sed 's/\r$//' | bash -s` (PowerShell adds CRs and a BOM).
- The temporary backtest diagnostics profile must never be pushed: a stale `phase1.windows.backtest` silently changes the dataset
  split. Restore `config.json` byte-for-byte before any push.

### V5.7.0 retrain and the out-of-window holdout

`scripts/codespace_retrain_v570.sh a <tag>` / `b <tag> <winner_group>` replace the V5.6.0 pair: stage A builds the dataset (label
purge, `asset_class_forex`, `fx_carry_3m`, separate forex rank group — all from `config.json`), then trains the multitask control
with **3 seeds** and every variant (single changes incl. weight-decay x4, dropout 0.35, a smaller net) with **2 seeds**;
`compare_training_variants.py --groups` picks on the MEAN full-daily validation IC (HAC t reported) against the control's single-seed
spread, never on the backtest split. Stage B installs the winner, trains sequence / gating / RL, builds the holdout dataset with the
active scaler and runs the resumable walk-forward. The holdout REPORT (`scripts/holdout_report.py`) is run locally, once, after the
choice.

Until V5.8.0 the holdout lived in its own root, `data_holdout/`; since V5.8.0 it is `phase1.windows.holdout` inside `data/`, and
V6.0.0 deleted `data_holdout/` (local and Codespace). `scripts/build_holdout_data.py --apply` now writes to a staging root
(`--root`, default `data_v6_staging`) and `build_holdout_dataset.py` builds any window with the active scaler.

**Operational lessons from the V5.7.0 run (Problems #150, #153):** a Codespace VM can restart mid-run and kills nohup jobs (stage A is
resumable with `RESUME=1`, the walk-forward with `--resume-run-id`); keep remote commands in uploaded `.sh` files, inline quoting through
`ssh` from PowerShell breaks; `codespace_sync.ps1 -Mode trees` (also part of `-Mode status`) compares the `data/` file
lists, and a stray Codespace-only file shows up there. **A pull overwrites the whole of `ml/`** (models, scaler, schema, datasets AND
`expert_models/`): back up all of `ml/` first, and after restoring verify it file-by-file; grep the engine log of the next backtest for
`inference failed` within its first minutes. Check `docker info` before `aq backtest`; Windows can reap background commands when memory is
critically low (the Lean container itself survives).

### V5.8.0 data refresh, Codespace scripts and disk hygiene

**Extending the data window.** `data/` runs through 2026-09-30 for every class, rewritten in full from ONE source (Yahoo,
`auto_adjust=True`) because appending adjusted 2021-26 bars to rows adjusted as of 2021 would put a step at every later
split or spinoff. Procedure (dev PC, nothing touches `data/` until the audit is clean):

1. `python scripts/build_holdout_data.py --root data_v580_staging --start 2013-01-01 --end 2026-10-01 --report-name refresh_report.json --apply`
   (equity/bond/crypto/forex zips + crypto quote zips + the 19 FRED series; `data_pipeline/price_overrides.json` holds
   verified single-bar corrections, `sanitize_ohlc` widens forex high/low to contain open/close).
2. `aq evaluate --audit-data --data-root data_v580_staging` and resolve every flag (the remaining ones are real market
   events: spinoffs, crashes, crypto spikes).
3. Copy a backup of `data/` to `data_backup_pre_v580/`, copy the staged zips and FRED CSVs over `data/`, **delete the
   Lean `factor_files/*.csv` of every ticker whose zip is now Yahoo-adjusted** (a missing file is an identity; a
   sentinel-only file starts the data in 2050, Problems #130), and run `python -m data_pipeline.factor_file_backfill --audit`
   (must report 0).
4. `python scripts/coinbase_listing_dates.py --apply` writes `data/reference/crypto_listing_dates.json` (first public
   Coinbase candle = listing, gaps > 7 days = suspension, a candle series that stops = delisting).

**Codespace session.** `scripts/codespace_sync.ps1 -Mode push` (the push excludes `data_backup_pre_v580`,
`data_v580_staging`, `backtests*`); then `scripts/codespace_prepare_v580.sh` on the Codespace removes the factor files a
push cannot delete, frees the regenerable datasets and writes `data/manifest_v580.json`. `-Mode status` / `-Mode trees`
now also compare a **content digest** (sha256 over every file under `data/{crypto,equity,forex,reference}`), which sees a
rewritten file of the same size. The full test suite runs there with `scripts/codespace_run_tests.sh` (8 GB, Python 3.11 like
CI: 96 s against 11 minutes on the 4 GB dev PC, which cannot hold it); `tests/test_docs_links.py` fails on the Codespace
only because `backtests/README.md` is not pushed. `scripts/codespace_status.sh` prints a running retrain's step markers,
errors, memory and disk. Quote every remote command that contains `"` in a script file: Windows OpenSSH strips double quotes
from inline arguments.

**Disk.** `aq clean ml` lists (dry run) the regenerable bulk of `ml/` — candidate versions that no active metrics file
references, `_backup_*` older than the newest, and with `--strip-walk-forward-datasets` the per-window datasets of kept
walk-forward runs; `--apply` deletes. Each Lean run keeps a code snapshot in `backtests/<run>/code/`; keep `build/` and old
`backtests*` trees out of it.

### V5.8.0 Lean runs on the 4 GB dev PC

- **Window.** `phase1.windows.backtest` stays the dataset split; a longer Lean run sets `runtime.lean_window_override` {"start", "end"} (null = the backtest split), which `risk_controls.resolve_lean_window` reads. `phase1.windows.holdout` (2025-07-01..2026-09-30) is only read by `scripts/build_holdout_dataset.py` and `scripts/holdout_report.py`.
- **State writes.** `phase_v2.diagnostics.state_write` {`every_n_ticks`, `backtest_only_at_shutdown`, `compact_json_in_backtest`} thins the dashboard files in a backtest only (live and paper write every tick; the initialize and shutdown writes are never thinned). The BT1 probe put `write_state` at 580 ms x 1,871 calls, 34% of the run; with 20 ticks and compact JSON BT2 covered 3.25 years in 48 minutes against 53 minutes for BT1's 2 years.
- **Memory.** Docker Desktop plus its WSL VM holds about 1.5 GB; a Lean run starts with ~250 MB free. Quit Docker Desktop (and `wsl --shutdown`) before heavy offline analysis, start it again for the next run, and keep every other app closed during `Initialize()` (90 s limit). `aq backtest`'s launcher can be reaped by the harness under memory pressure; the Lean container keeps running, and the post-run report can be regenerated by hand.
- **WSL hang.** If `WslService` sits in StopPending, the fix is an elevated `taskkill /F /PID <its pid>` (the service restarts), then `wsl --shutdown` and a fresh Docker Desktop start.
- **Evidence order.** engine log (`backtests/<run>/log.txt`: `inference failed`, `numerical precision`, 2050, the known #104 teardown timeout) -> `aq evaluate --audit-backtest --period ...` -> `--audit-fills` -> `--reconcile-features --symbol X --dataset <split dataset>` -> `--reconcile-book-history --replay-hysteresis --hysteresis-survives-veto --dataset ...`. Crypto and forex snapshots are compared per feature group (own-price block = previous dataset row, cross-asset block = the tick's row).

### V6.0.0 Codespace and Lean lessons

- **Heavy offline jobs run on the Codespace.** Scoring the 90k-row backtest + holdout frame for the simulator takes ~1.4 GB, which the 4 GB dev PC cannot give next to its own processes (Claude's memory reaper killed the first local R-CAL run). `scripts/codespace_calibration_v600.sh`, `codespace_research_v600.sh` and `codespace_predict_v600.sh` run R-CAL, the three rule decisions and the BT1 prediction there; ship code with `-Mode push -CodeOnly`, the two Lean run folders (without `code/`) and their book-history files with one `scp`, and pull back only the JSONs.
- **A Codespace job dies with the Codespace (V6.1.0).** S1 stopped silently after ~40 minutes (idle timeout, nobody connected) and `gh codespace list` then showed Shutdown while the job log simply ended. Keep one `gh codespace ssh ... 'while pgrep -f <script>; do sleep 60; done'` open for the whole run and resume with `RESUME=1`.
- **Inline ssh commands**: Windows OpenSSH strips double quotes, so `grep -E "a|b"` splits and `grep` then waits on stdin (the session hangs). Use `grep -e a -e b` without quotes, or an uploaded `.sh`. Never `pkill -f <script>` through ssh: the pattern matches the ssh shell itself.
- **`data_holdout/` is gone** (local and Codespace); the holdout is `phase1.windows.holdout` inside `data/`. `build_holdout_data.py` writes to `--root` (default `data_v6_staging`); `build_holdout_dataset.py --full-splits --write-split-files` builds train / validation / backtest / holdout with the active scaler.
- **Lean over the whole span.** `runtime.lean_window_override` {2023-07-01, 2026-09-30} is BT1's and BT2's window; reset it to null afterwards. The diagnostics that make a run verifiable (`timing_probe`, `crypto_bar_probe` for crypto and forex, feature snapshots for XOM, NVDA, TLT, ETHUSD, BTCUSD, EURUSD, GBPJPY) are on for BT1 only where noted in the Changelog.
- **Teardown smoke:** `lean backtest scripts/lean_teardown_smoke --image <image> --no-update` through `scripts/run_lean_cli_windows.py` (set `MSYS_NO_PATHCONV=1` in Git Bash).

## Config Presets

`phase_v2.presets` holds named bundles of dotted config keys (`moderate`,
`aggressive` — book size, liquidity thresholds, minimum net edge, and
similar) applied atomically via `aq config preset --apply <name>`
(validates every key resolves before writing anything). `aq evaluate
--preset <name>` overlays the same bundle in memory only, so both presets
can be compared against the offline rank-book simulator for free before
either one costs a Lean backtest.

Note that every `aq evaluate` investigation tool (`--reconcile-features`
included, V5.3.5.3) is pure-local Python: it reads
`ml/datasets/*.csv` and a `book_history.jsonl` log directly — no Docker,
no Redis, no Postgres needed. The only thing that ever requires the Lean
Docker stack is producing a new `book_history.jsonl` (i.e., running a real
backtest with `phase_v2.diagnostics.book_history.enabled=true`).

## Connecting Between Containers

Within the Compose network, services use their service names:

- Redis: `redis://redis:6379/0`
- PostgreSQL: `postgresql://aether:aether_dev_password@postgres:5432/aether_quant`

From Windows, you reach the ports by default like this (remapped so they don't collide with the separate Aether-Vault Compose stack):

- Redis: `localhost:6380`
- PostgreSQL: `localhost:5433`
- `engine` (FastAPI + webui bundle): `http://localhost:8001`

## Local Lean Backtest Image (V5.1.11)

`aq backtest` builds and reuses `aether-quant-lean:17900`, a small local
layer over the pinned `quantconnect/lean:17900` engine. Its
`Dockerfile.lean` installs only `requirements/lean-runtime.txt` (currently
the Redis client), keeping runtime dependencies inside the container rather
than asking Lean CLI to create and bind-mount a temporary root
`requirements.txt` from Windows. On Windows, `aq` also launches Lean through
`scripts/run_lean_cli_windows.py`, which makes Lean-created temporary mount
directories readable by Docker Desktop. `aq backtest --image <image>` remains
an explicit escape hatch and bypasses the local-image build.

## Codespace Training Handoff

The complete workflow (create → connect → train → sync artifacts → stop)
lives in "Cloud Training via GitHub Codespaces" above. Summary: sync
needed files up before training, train Python-only inside the Codespace
(Lean runs on the DinD Codespace, not here), pull the entire `ml/` artifact tree
back after (tarball for anything large, verify file presence/mtime), and
`gh codespace stop` immediately when done: compute bills while running,
storage while it exists (AGENTS.md rule 13).



## GitHub Actions (V5.3.9+)

`ci.yml`: python-tests (ubuntu+windows matrix, full offline suite,
coverage.xml artifact, --cov-fail-under=80), python-lint (ruff),
webui-tests (tsc, oxlint, vitest --pool=threads, build), cli-smoke
(editable install + offline battery incl. secrets-check), workflows-lint
(actionlint). `release.yml`: on `v*.*.*` tags -> tag-tests (visibility
only, non-gating by design) -> publish-pypi (Trusted Publisher OIDC) ->
publish-docker (ghcr.io, gha layer cache) -> github-release (auto notes +
Changelog link).

### V5.5.0 additions

Guard jobs (all pinned in `tests/test_ci_workflows.py`): **fast-guards**
(registration, help surface, workflow shape, packaging, docs links, parity
round — minutes, before the coverage matrix finishes), **subsystem-matrix**
(`aq test --<bucket>` once per `_SUBSYSTEM_TEST_FILES` bucket incl. the new
`meta` bucket; the matrix list is asserted equal to the registry),
**wheel-smoke** (`python -m build --wheel`, install into a clean venv, run
`scripts/wheel_smoke.py` from outside the checkout — imports every shipped
module and runs every `aq <sub> --help`), **python-compat** (Python 3.10
byte-compile; `requires-python` is `>=3.10` but every other job runs 3.11),
**docker-checks** (hadolint v2.12.0 errors-only on both Dockerfiles,
`docker compose config -q` incl. `--profile lean`, the webui stage build —
never `Dockerfile.lean`, its 40 GB base does not fit a hosted runner),
**parity-smoke** (the audit / as-live / sleeve / calibration tests plus
`scripts/feature_parity_audit.py --synthetic-only`, which fails when its check
did not actually run), and two **advisory** jobs: **secret-scan** (gitleaks
v8.18.4 on the working tree) and **test-count-drift**
(`scripts/check_test_count_drift.py`, README badge vs `pytest --collect-only`).
Linux jobs install CPU-only torch first; ruff is pinned identically in the
lint job and `requirements-dev.txt`; `.github/dependabot.yml` covers pip, npm
and github-actions weekly; `npm audit` runs advisory in `webui-tests`.
`secret-scan` and the hadolint/compose steps could not be run locally (no
binaries/Docker in the authoring session) — actionlint validates the YAML, but
expect to allowlist a first-run finding.

## Repairing double-adjusted equity factor files (V5.5.0)

Zips written by `yfinance_backfill.py` (`auto_adjust=True`) are already split-
and dividend-adjusted and need **no** Lean factor file - and the file must be
*absent*: a sentinel-only stub makes Lean log `adjust to a later starting date:
[EMB, 12/30/2050]` and serve no data; only the genuine
QuantConnect zips (integer volume column) do. Audit and repair, offline:

```powershell
python -m data_pipeline.factor_file_backfill --audit                          # exit 1 if any file is double-adjusted
python -m data_pipeline.factor_file_backfill --repair-adjusted-zips           # dry run
python -m data_pipeline.factor_file_backfill --repair-adjusted-zips --apply   # REMOVES the files; originals -> data/equity/usa/factor_files_backup_pre_v550/
```

Do **not** follow a repair with a local `aq train --dataset-only`: it refits
the scaler against the shipped model weights. Regenerate the dataset and
retrain together on the Codespace (see "Cloud Training via GitHub Codespaces").
`data/` is gitignored, so the repair is per machine and per Codespace sync.

## Auditing a finished backtest (V5.5.0)

```powershell
aq evaluate --audit-backtest                              # newest backtests/<timestamp>
aq evaluate --audit-backtest --backtest-dir backtests\2026-10-07_09-00-00
aq evaluate --rank-book --as-live --factor-exposure       # the offline side, for comparison
```

Teardown must be judged from the **engine** `log.txt`
(`PythonInitializer.Shutdown(): ended` vs `Operation timed out`), which the
audit parses; the algorithm log never records it.

### V6.1.0 tools

- **Seed ensembles:** `phase_v2.model_ensemble` (off) makes `main.py` and every offline scorer average the raw head outputs of the members in `ml/multitask_ensemble/` and `ml/sequence_ensemble/` (`inference.exported_model.average_head_outputs`); install a winning ensemble by copying the member exports there and flipping the flag, after backing up `ml/` and checking `python scripts/ml_manifest.py`.
- **Timing probe:** `phase_v2.diagnostics.timing_probe` now reports CPU time next to wall time (`cpu_ms`) and an `on_data_total` section: wall >> CPU means the host was busy.
- **Lean Monte Carlo:** `aq evaluate --lean-monte-carlo --backtest-dir <run>` -> `ml/evaluation/monte_carlo_lean.json`, rendered in the README's Monte Carlo block.
- **Bar probe dates:** `phase_v2.diagnostics.crypto_bar_probe.date_ranges` ([[start, end], ...]) logs every bar of the listed forex / crypto symbols inside those dates (Lean's holiday calendar check).
- **Crypto route check:** `aq render-lean-config` warns when crypto is in the universe and the credentials are Interactive Brokers' (Problems.md #192).
- **README Lean run pin:** `python generate_backtest_report.py --backtest-dir backtests/<run>` pins every Lean-reading README block (the run table, the Lean-vs-offline block, the Sharpe comparison) to that run through `ml/evaluation/readme_lean_run.json`; the next plain `aq backtest` clears the pin. Use it when the newest run is not the shipped configuration's (V6.1.0: the rejected cap-0.80 run).
- **Docker cold start:** wait about 10 minutes after `docker info` answers before `aq backtest` on this host; a run started right after Docker Desktop hit Lean's 90 s `Initialize()` limit (`backtests_invalid/2026-10-16_21-09-57_bt2_init_timeout`).

### V6.2.0: Lean on a Docker-in-Docker Codespace, and Codespace lessons

- **Lean host:** Docker Desktop on the 4 GB dev PC could no longer boot its WSL VM inside Docker's time limit
  (`Wsl/Service/CreateInstance/CreateVm/ERROR_TIMEOUT`, ~400 MB free), so V6.2.0's Lean runs ran on a temporary
  4-core / 16 GB Codespace from `.devcontainer/dind-v1-test/` (`python:3.11-bookworm` + `docker-in-docker:2`):
  `gh codespace create -R leon1706-lol/Aether-quant -b main --devcontainer-path .devcontainer/dind-v1-test/devcontainer.json -m standardLinux32gb`.
  Before building the Lean image, move Docker's data root to the local disk (`/tmp`, 118 GB; the workspace
  disk is 32 GB and the image ~20 GB): write `/etc/docker/daemon.json`
  `{"data-root": "/tmp/docker-data", "dns": ["168.63.129.16"]}` (the DNS the feature's daemon uses), kill
  `dockerd`, start `sudo setsid nohup dockerd &`, then `docker build -f Dockerfile.lean -t aether-quant-lean:17900 .`
  and `pip install lean==1.0.227`. `lean backtest . --image aether-quant-lean:17900` needs no login. Push the
  project with `codespace_sync.ps1 -Mode push -Codespace <name>` (full: `data/` and `ml/`) and confirm
  `-Mode status` shows both trees matching (AGENTS.md #12); a `-CodeOnly` push overwrites `config.json`, so copy
  the frozen run config back afterwards. A 3.25-year run takes ~10 minutes there (~2 hours on the dev PC), and the
  engine shut down cleanly in all three runs (no #104 timeout).
- **Idle timeout:** a Codespace stops ~30 minutes after its last ssh session (60 for one created with
  `--idle-timeout 60m`) and takes detached jobs with it. When long-running local shells are not available
  (Claude Code's memory-pressure reaper stopped them on the dev PC), an ssh check every <= 15 minutes keeps it up;
  `scripts/codespace_keepalive.sh` is the one-command holder (`pgrep` patterns through Windows ssh lose their
  quoting). Session scripts resume with `RESUME=1`. `pgrep -f <name>` run through ssh matches its own command line.
- **Two Codespaces:** `codespace_sync.ps1` resolves `-Codespace` by name or display name (fixed for Windows
  PowerShell 5.1's `ConvertFrom-Json` array behaviour, which joined two names).
- **Risk-free file:** `python scripts/refresh_lean_interest_rate.py --apply` keeps Lean's
  `data/alternative/interest-rate/usa/interest-rate.csv` current (FRED DPCREDIT); copy it to every Codespace
  with `gh codespace cp` (a `-CodeOnly` push skips `data/`).
- **CI checkout locally:** `powershell -File scripts/clean_checkout_test.ps1` before handing over a commit.

### Lean on a DinD Codespace (V6.3.0, the standing Lean host)

The recipe above is scripted. The PC drives it, and the Codespace lives only for one phase's runs.

```powershell
.\scripts\codespace_lean_run.ps1 -Create                                   # 4-core / 16 GB, --idle-timeout 30m; prints <name>
.\scripts\codespace_lean_run.ps1 -Codespace <name> -Push -Run ml/evaluation/run_configs/<a>.json,ml/evaluation/run_configs/<b>.json
.\scripts\codespace_lean_run.ps1 -Codespace <name> -Status                 # every <= 10 minutes (also keeps it from idling out)
.\scripts\codespace_lean_run.ps1 -Codespace <name> -Pull -Delete           # run folders + book history, then delete it
aq evaluate --lean-report --backtest-dir backtests/<run>                   # every run-folder tool + the README
```

- **The script on the Codespace:** `scripts/codespace_lean_dind.sh` does the data-root move, builds the image only when it is missing, and pins the Lean CLI. It runs each frozen config in turn over `config.json` and restores the original afterwards. Status lines go to `/tmp/aq_lean/status`, and the Lean CLI log is copied into each run folder as `lean_cli.log`.
- **Budget (AGENTS.md rule 13):**
  - Put every Lean run of a phase in one `-Run` call.
  - Check the engine image (`docker compose build engine`) in the same lifetime, if the PC cannot.
  - `-Delete` right after `-Pull`. The image and disk are billed storage while the Codespace exists, even when stopped.


### V6.4.0: appending data, and the research lifetime

**Extending the data window without moving history.** The shipped `data/` is one Yahoo vintage (`auto_adjust=True`, V5.8.0). A later
full rewrite would rescale every adjusted row with each new dividend, so the window is *appended* instead (Problems #215):

1. `python scripts/data_append_guard.py snapshot --out ml/evaluation/v640/data_before.json --cutoff <last stored date>` hashes the rows
   of every equity / crypto / forex zip and FRED cache up to the cutoff. Back `data/` up first (`data_backups/`, gitignored and excluded from the sync).
2. `python scripts/data_append_refresh.py --end <last close + 1 day> [--apply]` fetches from 14 days before each file's last row,
   multiplies the new rows by old close / new close at the latest common date (1.0 unless a dividend or split intervened; a factor
   further than 5% from 1 is flagged), and merges them behind the stored rows; the FRED caches take only rows dated after the cutoff
   (a late-published earlier date stays out: no dataset row of that day saw it).
3. `python scripts/data_append_guard.py verify --before ... --out ml/evaluation/v640/data_append_guard.json` must report 0 changed
   files; the session script repeats it on the Codespace against the same hashes, which also proves the push.
4. Bump `available_to` of every asset and `phase1.windows.holdout.end`; rebuild the dataset on the Codespace with
   `scripts/build_holdout_dataset.py --full-splits --write-split-files` (the active scaler, no refit). `scripts/compare_datasets.py`
   against the previous dataset must show new rows and newly resolved `target_*` cells only.

**One research lifetime.** `scripts/codespace_session_v640.sh <expected manifest>` (launch with `codespace_start_bg.sh`, `RESUME=1`
continues) runs the guards, the dataset, the legacy input and its 5-seed retrain, candidate IC with the yardstick fixed at 0.034, a
`--smoke` pass of `scripts/v640_research.py` (every stage, one variant, two phases), the real chain (memoised in
`research.memo.json`), the adopted config-only changes, every offline README block and the suite. Push first with a full
`codespace_sync.ps1 -Mode push` (the data changed); after the retrain's artifacts exist use `-CodeOnly`.

**Paper runs.** `diagnostics.book_history.paper_enabled` writes the bounded per-rebalance record in paper mode (backtests keep the full
one, live never logs it); `aq evaluate --paper-check` turns a paper run folder into the protocol's checklist (RUNBOOK "Paper period
protocol"). `diagnostics.book_history.include_probabilities` adds the head probabilities behind each book call; `aq evaluate
--classification-parity` scores them against the offline head.
