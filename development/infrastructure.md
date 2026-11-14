# Infrastructure

How to run the services, move work to Codespaces, run Lean and keep data honest. Procedures for incidents are in [`RUNBOOK.md`](../RUNBOOK.md).

## Docker Compose

Two images come from one `Dockerfile`:

- **`engine`:** the default and last target. It runs the app and every worker (`docker compose build engine`) and installs CPU torch.
- **`dashboard`:** a light target (V6.6.5, #344). It holds only the wheel's `[dashboard]` extra, the built UI and `monitoring/demo/`, runs as a non-root user and has a healthcheck. Use `docker build --target dashboard -t aether-quant-dashboard .`, then `aq webui --docker`.

Containers are named `aether-quant-<name>`, distinct from the sibling `aether-vault-*` project.

| Service | Needs | Does |
|---|---|---|
| `redis`, `postgres` | | Buffer and permanent store |
| `engine` | | FastAPI and the bundled dashboard |
| `experience-worker` | Redis, Postgres | Drains decisions to Postgres |
| `audit-worker` | Redis, Postgres | Drains and chains the audit log |
| `performance-trigger-worker` | Postgres | Evaluates triggers |
| `retraining-worker` | Postgres, training stack | Controlled retraining |
| `telegram-worker` | Postgres | Alerts |
| `paper-readiness-scheduler` | Postgres | Keeps the readiness report fresh |
| `lean`, `lean-live` | Profiles | Engine containers. `lean-live` passes `--lean-config ${LEAN_LIVE_CONFIG}` and `AQ_ACCOUNT` (`aq live up --account`) |
| `dashboard` | Profile `dashboard` | The demo dashboard on `127.0.0.1:${AQ_DASHBOARD_PORT:-8080}` |

```powershell
docker compose up -d redis postgres                         # aq docker up
docker compose up -d redis postgres experience-worker
docker compose run --rm experience-worker python -m experience.postgres_worker --once   # one batch, after a backtest
docker compose logs -f experience-worker
```

- **Your own images:** set `REDIS_IMAGE`, `POSTGRES_IMAGE` or `LEAN_IMAGE`. Lean is pinned, not `:latest`, so it never silently re-pulls about 42 GB (#40).
- **Inside the network:** `redis://redis:6379/0`, `postgresql://aether:aether_dev_password@postgres:5432/aether_quant`.
- **From the host:** Redis `localhost:6380`, Postgres `localhost:5433`, `engine` `http://localhost:8001`. They're remapped so they don't collide with Aether-Vault.
- **Bound to localhost:** the engine publishes on `${AETHER_QUANT_BIND:-127.0.0.1}`. Set `0.0.0.0` only with API users configured (#350).
- **Docker secrets:** `docker compose -f docker-compose.yml -f docker-compose.secrets.yml up -d`. It reads `secrets/postgres_password` and `secrets/postgres_dsn` (gitignored) into `POSTGRES_PASSWORD_FILE` and `AETHER_POSTGRES_DSN_FILE` (#348).
- **Backups:** `python scripts/backup_postgres.py --docker` runs `pg_dump` in the `postgres` container and keeps 14 dumps in `state/backups/` (RUNBOOK "Backups").
- **Low memory:** run only `redis` during a backtest, and drain to Postgres afterwards. It is a real stream, so nothing is lost; the full stack beside Lean ran out of memory on the 4 GB PC.

## Inspecting Postgres

```powershell
docker exec -it aether-quant-postgres psql -U aether -d aether_quant
docker exec -it aether-quant-redis redis-cli XLEN aether:experience:deadletter
```

```sql
SELECT event_id, created_at, ticker, signal, action, confidence FROM experience_events ORDER BY created_at DESC LIMIT 10;
SELECT event_id, payload -> 'portfolio' ->> 'total_value' AS equity FROM experience_events WHERE mode = 'observation' ORDER BY created_at DESC LIMIT 5;
SELECT trigger_type, severity, retrain_candidate, created_at FROM performance_triggers ORDER BY created_at DESC LIMIT 20;
SELECT model_version_id, status, aether_vault_commit, created_at FROM model_versions ORDER BY created_at DESC LIMIT 10;
SELECT retraining_id, candidate_version_id, status, reason, created_at FROM retraining_events ORDER BY created_at DESC LIMIT 20;
SELECT channel, last_created_at FROM telegram_alert_watermark;
```

## Observation mode

Everything runs as if live, but no real order is placed: decisions go to a simulated portfolio and on to Redis and Postgres.

1. Set `phase_v2.runtime.mode` to `observation`, with `allow_live_orders` false. Switch back afterwards; the committed default is `backtest`.
2. `docker compose up -d redis postgres experience-worker`.
3. A bare `lean backtest .` container can't reach Redis, so inject it. The `--%` is load-bearing on PowerShell:

```powershell
lean backtest . --image quantconnect/lean:17900 --% --extra-docker-config "{\"environment\": {\"AETHER_REDIS_URL\": \"redis://host.docker.internal:6380/0\"}}"
```

If Redis is unreachable, the push is skipped with a warning and trading carries on. The "Observation Mode" panel shows the results.

## Paper

Lean's built-in `PaperBrokerage` (`lean.json`, `live-paper`) needs no IB paper account, only a live data feed: `lean login`, or a provider key. Confirm it by hand, then set `phase_v2.paper_trading.live_data_provider_configured`.

`scripts/lean_smoke/live_plumbing.sh` (V6.6.4) runs `main.py` itself in `live-paper` from the engine image with a `FakeDataQueue` and the native Redis and Postgres of `scripts/field_services.sh`: no login, key or broker. It proves the algorithm starts live, stays up while Redis and then Postgres are stopped under it, restarts, and that the audit chain verifies; it proves no order, kill-switch trip or reconciliation, which need a feed that moves the way a market does (`ml/evaluation/v664/live_plumbing.json` lists what it does not prove). A stopped DinD Codespace loses its `/tmp`, including the Lean image: the first start after a stop rebuilds it (about 8 minutes).

`aq paper-readiness` checks broker config and observation health: enough observations, drawdown and Sharpe floors, no dominant rejection. It exits 1 until ready. Reviewing the trade history stays manual (`phase_v2.paper_trading.manual_review_confirmed`). Then set `phase_v2.runtime.mode` to `paper` and `allow_live_orders` to true. The checklist: [`RUNBOOK.md`](../RUNBOOK.md#deploy-checklist-paper-first).

## Live

Structural only: no real broker credentials have ever been used.

1. A consistent paper record first.
2. Credentials, by one of two ways: `.env.live` (from `.env.live.example`), or a gitignored `ib_config.py`.
3. Never hand-edit secrets into the tracked `lean.json`, and Lean doesn't expand `${VAR}` there. Render a gitignored copy:

```powershell
aq render-lean-config                                  # prints field names, never values
lean live deploy --lean-config lean.live.json ...
```

Enable the guard once per clone: `git config core.hooksPath .githooks`.

## Retraining, triggers and alerts

```powershell
docker compose up -d postgres retraining-worker
docker compose run --rm retraining-worker python -m retraining.worker --once
aq retrain plan
aq retrain train --retraining-id <id> --version-id <uuid>
aq retrain promote --version-id <uuid>
aq retrain rollback --to-version-id <uuid>
```

- **Turn off:** `phase_v2.retraining.enabled` false. Stages toggle through `phase_v2.retraining.{topology_training,gating_training,multitask_training,sequence_training}.enabled`.
- **Not versioned here:** per-expert multitask heads (`ml/expert_models/<name>/multitask_model.json`).
- **Triggers:** `docker compose up -d redis postgres performance-trigger-worker`, or `... run --rm performance-trigger-worker python -m performance.trigger_worker --once`.
- **Telegram:** set `AETHER_TELEGRAM_BOT_TOKEN` and `AETHER_TELEGRAM_CHAT_ID` in `.env`. Without them the worker is a safe no-op. `phase_v2.telegram.enabled` turns it off.

## Codespaces

They bill the owner's budget (AGENTS.md rule 13): on only while a job runs. `gh codespace list` at the start and end of every session.

**The training Codespace** (`aq-Training-Ground-Fixed`, 4 cores / 16 GB, kept stopped)

```powershell
gh codespace create -R leon1706-lol/Aether-quant -b main --devcontainer-path .devcontainer/devcontainer.json -m standardLinux32gb --idle-timeout 30m
.\scripts\codespace_sync.ps1 -Mode push                       # one tarball over ssh, hash-verified; -CodeOnly skips data/ and ml/
.\scripts\codespace_sync.ps1 -Mode status                     # key files, and data/ trees by content digest
.\scripts\codespace_sync.ps1 -Mode pull -Candidate <ids...>   # back up ml/ first: a pull overwrites it
.\scripts\codespace_sync.ps1 -Mode stop
```

Use `sshd`, CPU torch (`--index-url .../whl/cpu`, because the CUDA build fails to import), and no `docker-in-docker` on this container.

**Lean on a DinD Codespace** (temporary, deleted when its runs are pulled)

```powershell
.\scripts\codespace_lean_run.ps1 -Create
.\scripts\codespace_lean_run.ps1 -Codespace <name> -Push -Run ml/evaluation/run_configs/<a>.json,ml/evaluation/run_configs/<b>.json [-Parallel 3]
.\scripts\codespace_lean_run.ps1 -Codespace <name> -Status      # every 10 minutes or less; also keeps it up
.\scripts\codespace_lean_run.ps1 -Codespace <name> -Pull -Delete
aq evaluate --lean-report --backtest-dir backtests/<run>
```

- **What the script does:** moves Docker's data root to the local disk (`/tmp`, because the workspace disk is 32 GB and the image about 20 GB), builds the image once, and installs the pinned Lean CLI.
- **Bundle:** every Lean run and Docker check of a phase goes in one lifetime.
- **Speed:** a target-weights run takes about 1 minute per 2 years on 4 cores; `-Parallel 3` is safe.
- **Per-run models:** `ml/evaluation/run_artifacts/<run name>/` replaces matching `ml/` files for that run only.

**Hard-won rules**

- **A Codespace job dies with the Codespace.** It stops about 30 minutes after the last ssh session. Hold it with `scripts/codespace_keepalive.sh`, and resume with `RESUME=1` or `--resume-run-id`. The VM can also reboot, and `/tmp` doesn't survive a stop, so a DinD image rebuilds.
- **`data/` must match on both sides, file for file.** A push overlays and never deletes (#141). `-Mode status` catches it.
- **A push overwrites `ml/` and `config.json`.** Use `-CodeOnly` during a retrain, and copy a frozen run config back afterwards.
- **Quote nothing inline.** Windows OpenSSH strips double quotes, so put remote commands in an uploaded `.sh` file. Append `</dev/null`, or the tool hangs.
- **`gh codespace cp`:** needs forward-slash paths. `-r` drops files silently, so tar instead. In Git Bash set `MSYS_NO_PATHCONV=1`.
- **Run Windows-side scripts from PowerShell,** not through Git Bash. Don't edit key files during a push, and never run two pushes at once.
- **Packages:** Codespaces have pandas 3 (read-only arrays: `to_numpy(copy=True)`). A DinD Codespace needs `pip install pyarrow httpx requests scikit-learn` for research scripts.
- **Disk:** `aq clean ml` lists what is regenerable.

**Verifying off a small PC**

- `scripts/codespace_verify.ps1 -Start` runs every CI job on a Codespace.
- `scripts/codespace_prove.sh` runs `aq prove --regen-cases`.

## Lean locally

- **Image:** `aq backtest` builds `aether-quant-lean:17900` on the pinned engine, from `Dockerfile.lean`, which avoids Lean CLI's Windows bind mount of a generated `requirements.txt`. `--image` overrides it.
- **Creation ceiling:** `algorithm-creation-timeout` in `lean.json` is 600 s. It covers `import main`, so don't run anything heavy alongside (#16).
- **Docker on a small PC:** WSL plus Docker holds about 1.5 GB. Close apps first. `CreateVm/ERROR_TIMEOUT` means too little RAM: boot the VM by hand, then Docker. Wait about 10 minutes after `docker info` answers.
- **Window:** `phase1.windows.backtest` is the dataset split; a longer run sets `runtime.lean_window_override`. A root config has no override, so a gated run otherwise stops at the split's end.
- **State writes:** `phase_v2.diagnostics.state_write` throttles them in backtests.
- **Freeze a run's config by hand:** `ml/evaluation/run_configs/<folder>.json` (`scripts/freeze_run_config.py`). `aq backtest`'s report also unpins the README; re-pin with `--lean-report --backtest-dir`.
- **Evidence order:** the engine log first (`inference failed`, `numerical precision`, a date of 2050, the teardown line), then the algorithm log, then `aq evaluate --audit-backtest`. Teardown is judged only from the engine's `log.txt` (`PythonInitializer.Shutdown(): ended` against `Operation timed out`).
- **Smoke tests:** `scripts/lean_smoke/run.sh <option_structures|futures_margin>`; `lean backtest scripts/lean_teardown_smoke --image <image> --no-update`.

## Data

**Appending, the routine way.** `data/` is one Yahoo vintage. A full rewrite would rescale every adjusted row with each new dividend, so bars are appended (#215):

1. `python scripts/data_append_guard.py snapshot --out <file> --cutoff <last stored date>`, after backing up `data/`.
2. `python scripts/data_append_refresh.py --end <last close + 1 day> --apply` rescales new rows to the stored basis and flags any factor more than 5% from 1. FRED caches take only rows dated after the cutoff.
3. `python scripts/data_append_guard.py verify --before <file>` must report 0 changed files. Repeat on the Codespace.
4. Bump `available_to` and `phase1.windows.holdout.end`.
5. Rebuild without the 8 GB build: `scripts/splice_holdout_dataset.py --build`, then `--splice --compare-until <a label horizon before the old end>`. Or on the Codespace: `scripts/build_holdout_dataset.py --full-splits --write-split-files` (active scaler, no refit). `scripts/compare_datasets.py` must show only new rows and newly resolved `target_*` cells.

**A full rewrite, only when a whole new vintage is needed:**

1. `python scripts/build_holdout_data.py --root <staging> --start ... --end ...`, then `aq evaluate --audit-data --data-root <staging>`, and resolve every flag.
2. Back up `data/`, copy the staged files over, and **delete the factor files of every Yahoo-adjusted ticker**. A missing file is an identity, but a sentinel-only stub starts the data in 2050 (#130).
3. `python -m data_pipeline.factor_file_backfill --audit` must report 0. `python scripts/coinbase_listing_dates.py --apply`.

Never follow a repair with a local `aq train --dataset-only`: it refits the scaler against the shipped weights.

**Other roots**

- **`data_wide/`, `data_crypto_wide/`:** gitignored Lean roots for research (`scripts/build_wide_root.py`, `build_wide_info.py` with `AQ_SEC_CONTACT`, `build_crypto_wide_root.py`). `aq evaluate --alpha-proof --data-dir` reads them.
- **`data_pre2013/`:** `scripts/build_pre2013_root.py`. Spent by V6.5.0, never prepended to `data/`.
- **One heavy job at a time on a small PC,** downloads included. The memory guard stops background shells.
- **Risk-free file:** `python scripts/refresh_lean_interest_rate.py --apply`. Copy it to Codespaces; `-CodeOnly` skips `data/`.

## Formal proofs

`formal/` is a Lake project with Lean and Mathlib pinned, needing elan. Mathlib's `.olean` files come from its cache, never a local compile.

1. `cd formal`, `lake update`, `lake exe cache get` (about 5 GB). Close large apps first.
2. **Don't start `lake build` before `cache get` finishes:** an interrupted unpack compiles Mathlib for hours. Never extract `~/.cache/mathlib/*.ltar` by hand.
3. `aq prove`. A module that fails under memory pressure is rebuilt alone with `aq prove --module <Name>`.
4. `aq prove --regen-cases` runs `GenCases.lean` interpreted.

`ci.yml` runs the differential tests and `tests/test_formal_no_sorry.py`, which need no Lean. `.github/workflows/formal.yml` runs the Lean build, `aq prove --check-sorry`, the regenerated cases against the committed ones and `scripts/check_axioms.py` on any change to `formal/`, to a modelled Python file, and monthly.

## Config presets

`phase_v2.presets` holds named bundles of dotted keys. `aq config preset --apply <name>` validates every key first. `aq evaluate --preset <name>` overlays one in memory, for a free comparison.

## CI

- **`ci.yml`:** `python-tests` (ubuntu and windows, 100% coverage of every tracked module; XML, JSON, HTML and JUnit reports and a run summary), `python-lint`, `dependency-audit`, `webui-tests` (vitest coverage, blocking `npm audit`), `cli-smoke`, `workflows-lint`, `fast-guards`, `subsystem-matrix`, `wheel-smoke`, `python-compat` (3.10 byte-compile only), `docker-checks` (the dashboard image built, smoke-tested and scanned with trivy), `parity-smoke`, `secret-scan` (blocking on the tree, advisory on history), `lite-install`, `typecheck`, `docs`, `notebooks` and `bandit`. <!--fact:ci.jobs-->18<!--/fact--> jobs in all, pinned by `tests/test_ci_workflows.py`.
- **`release.yml`:** on `v*.*.*` tags:
  - `tag-tests` (visibility only)
  - `publish-pypi`, with attestations and a CycloneDX SBOM
  - `publish-docker`, a matrix over `aether-quant` and `aether-quant-dashboard`, with SBOMs and build provenance
  - `github-release`
- **`codeql.yml`, `scorecard.yml`:** CodeQL (Python, TypeScript, Actions) and OpenSSF Scorecard, on main and weekly.
- **`pages.yml`:** after CI succeeds on main, it publishes the MkDocs site, the coverage HTML and the shields endpoint behind the README's coverage badge to GitHub Pages.
- **`forward-ledger.yml`, `research-cycle.yml`:** each session, on free runners, writing only to branch `forward-ledger`.
- **Clean checkout:** CI has no gitignored files. Run `scripts/clean_checkout_test.ps1` before a commit.

## The vault

`.av/` is gitignored and local. `aether-vault` is pinned in `requirements/requirements.txt`. Candidates commit through `retraining/vault_client.py`, and `scripts/vault_record.py` records research rounds.
