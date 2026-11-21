# Command line (`aq`)

`aq` is installed with the library (`pip install aether-quant`). Commands that need the project's scripts, `.git` or the private `ml/` folder say so and exit 1 when run from a wheel install. `aq doctor` checks the environment, `aq status` shows the checkout at a glance, and `aq completion bash|zsh|powershell` prints a completion script.

## Conventions

| | |
|---|---|
| Exit codes | `0` ok · `1` failure · `2` usage (a bad flag, a missing companion flag, an unconfirmed change) · `3` a gate failed or something is still running · `130` interrupted |
| `--json` | A read command prints JSON to stdout, with progress on stderr. The older `--json FILE` flags (`hello`, `live-readiness`, `accounts status`, `secrets status`) still write to that file |
| `--dry-run` | A command that writes prints what it would change and changes nothing |
| `--yes` | A command that deletes or loosens a safety switch asks on a terminal, and needs `--yes` without one |
| `--debug` / `AQ_DEBUG=1` | Show the traceback of an unexpected error instead of one line |
| `AQ_SKIP_UPDATE_CHECK=1` | Never check PyPI for a newer release (it is checked only on a terminal, never with `--json`) |
| `NO_COLOR` | No colour in `aq status`, `aq ci` and `aq doctor` |

Every command's `--help` ends with examples. `aq help COMMAND` prints the same, and suggests the nearest name for a typo.

## Every command

The list below is generated from the parser by `aq docs cli` (and `aq docs sync`), so it always matches the installed `aq`.

<!-- AQ:CLI_REFERENCE_START -->
### `aq hello`

Start here: download data, run the shipped rule, print a clean report (no key, no Docker)

```text
aq hello [-h] [--offline] [--start START] [--end END] [--json FILE] [--html FILE] [--no-cache]
```

| Flag | Meaning |
|---|---|
| `--offline` | Use the bundled sample instead of downloading |
| `--start` | First decision date (YYYY-MM-DD) |
| `--end` | Last date (default: the last closed bar) |
| `--json` | Also write the report as JSON (- prints only the JSON) |
| `--html` | Also write a self-contained HTML page with the equity curve |
| `--no-cache` | Download again instead of reading ~/.cache/aether-quant |

### `aq models`

Example models from each GitHub release: list, install, info, score (no torch; the project's own models are not published)

```text
aq models [-h] {list,remove,install,info,score} ...
```

#### `aq models list`

The example models and whether each is installed

```text
aq models list [-h] [--json]
```

| Flag | Meaning |
|---|---|
| `--json` | Print JSON instead of text |

#### `aq models remove`

Delete an installed model from the cache

```text
aq models remove [-h] [--dry-run] name
```

| Flag | Meaning |
|---|---|
| `name` |  |
| `--dry-run` | Print what would be removed |

#### `aq models install`

Download an example from the release, check its sha256, unpack it into ~/.cache/aether-quant/models

```text
aq models install [-h] [--version VERSION] [--from ZIP] name
```

| Flag | Meaning |
|---|---|
| `name` |  |
| `--version` | The release tag without its v (default: the latest release) |
| `--from` | Install a local zip instead (checked the same way, against its own manifest) |

#### `aq models info`

An installed example's model card

```text
aq models info [-h] [--json] name
```

| Flag | Meaning |
|---|---|
| `name` |  |
| `--json` | Print JSON instead of text |

#### `aq models score`

Score a close table (dates x tickers CSV) with an installed example or a model folder

```text
aq models score [-h] [--csv CSV] [--head HEAD] [--out OUT] name
```

| Flag | Meaning |
|---|---|
| `name` | An installed example, or a folder holding an exported model (your own ml/versions/&lt;id&gt;) |
| `--csv` | Wide closes: a date column then one column per ticker (default: the bundled sample) |
| `--head` | Which head to read (default rank_20d) |
| `--out` | Write date,ticker,score here instead of printing the last date's scores |

### `aq init`

Start your own signal project: signal, tests, a pipeline with a gate, a GitHub workflow

```text
aq init [-h] [--name NAME] [--force] [--dry-run] directory
```

| Flag | Meaning |
|---|---|
| `directory` | A new or empty folder |
| `--name` | The project's name (default: the folder's) |
| `--force` | Write into a folder that is not empty, overwriting the template's files |
| `--dry-run` | Print the files it would write |

### `aq pipeline`

Data, signal, evaluate, gate, report in one resumable command (pipeline.toml, or the sample with defaults)

```text
aq pipeline [-h] {run,status,validate,list} ...
```

#### `aq pipeline run`

Run (or resume) a pipeline

```text
aq pipeline run [-h] [--config CONFIG] [--run-id RUN_ID] [--runs-dir RUNS_DIR] [--resume]
```

| Flag | Meaning |
|---|---|
| `--config` | The pipeline file (default: ./pipeline.toml, else the defaults) |
| `--run-id` | Resume or read this run (default: a new one / the latest) |
| `--runs-dir` | Where runs live (default: ./runs) |
| `--resume` | Continue the newest stopped run with its own pipeline file (its finished stages are kept) |

#### `aq pipeline status`

The stages a run has finished

```text
aq pipeline status [-h] [--config CONFIG] [--run-id RUN_ID] [--runs-dir RUNS_DIR] [--json] [--all]
```

| Flag | Meaning |
|---|---|
| `--config` | The pipeline file (default: ./pipeline.toml, else the defaults) |
| `--run-id` | Resume or read this run (default: a new one / the latest) |
| `--runs-dir` | Where runs live (default: ./runs) |
| `--json` | Print JSON instead of text |
| `--all` | Every run, not only the latest |

#### `aq pipeline validate`

Read and check the pipeline file, run nothing

```text
aq pipeline validate [-h] [--config CONFIG] [--run-id RUN_ID] [--runs-dir RUNS_DIR] [--json]
```

| Flag | Meaning |
|---|---|
| `--config` | The pipeline file (default: ./pipeline.toml, else the defaults) |
| `--run-id` | Resume or read this run (default: a new one / the latest) |
| `--runs-dir` | Where runs live (default: ./runs) |
| `--json` | Print JSON instead of text |

#### `aq pipeline list`

Every run and how far it got

```text
aq pipeline list [-h] [--config CONFIG] [--run-id RUN_ID] [--runs-dir RUNS_DIR] [--json]
```

| Flag | Meaning |
|---|---|
| `--config` | The pipeline file (default: ./pipeline.toml, else the defaults) |
| `--run-id` | Resume or read this run (default: a new one / the latest) |
| `--runs-dir` | Where runs live (default: ./runs) |
| `--json` | Print JSON instead of text |

### `aq train`

Run the training pipeline (wraps python train.py)

```text
aq train [-h] [--dataset-only | --init-only | --experts-only | --candidate | --gating-only | --multitask-only | --sequence-only | --topology-only | --strategy-selector-only | --rl-sizing-only | --walk-forward] [--step-days STEP_DAYS] [--mode {rolling,expanding}] [--include-multitask] [--include-sequence] [--resume-run-id RESUME_RUN_ID] [--metrics METRICS] [--seed SEED] [--ranking-objective {mse,soft_spearman,listnet,ic_pearson,ls_sharpe,class_balanced,cost_aware}] [--memory-profile {standard,low}] [--resume [RUN_ID]] [--list-runs] [--dry-run] [--json]
```

| Flag | Meaning |
|---|---|
| `--dataset-only` | Build dataset/scaler/manifest only |
| `--init-only` | Refresh the data inventory only |
| `--experts-only` | Train the 4 expert models only |
| `--candidate` | Train the baseline and experts into ml/versions/candidate-&lt;uuid&gt;/ without touching the active ml/ (wraps python train.py --candidate) |
| `--gating-only` | Train the learned gating blend only (wraps python train_gating.py) |
| `--multitask-only` | Train the joint direction+magnitude+volatility model only (wraps python train_multitask.py) |
| `--sequence-only` | Train the Phase 2 causal-TCN sequence encoder only (wraps python train_sequence.py) |
| `--topology-only` | Train the learned topology overlay only (wraps python train_topology.py). Needs Postgres up and enough accumulated realized-outcome events - see the command's own output if it skips. |
| `--strategy-selector-only` | Train the learned multi-leg strategy-selector model only (wraps python train_strategy_selector.py). Needs real option_strategy_outcome events (real option positions traded and closed) - expect this to skip indefinitely in this environment, see the command's own output. |
| `--rl-sizing-only` | Train the offline contextual-bandit sizing overlay only (wraps python train_rl_sizing.py). Reads ml/datasets/*.csv, NOT Postgres - needs a completed `aq train` and Component D's alt-data features in phase1.features.input_set. |
| `--walk-forward` | Run the dataset-build + training pipeline once per walk-forward window (wraps python train.py --walk-forward). Never touches active ml/ - diagnostic only, writes to ml/versions/&lt;run-id&gt;/window_&lt;i&gt;/. |
| `--step-days` | Walk-forward step size in days (only with --walk-forward). |
| `--mode` | Walk-forward mode: rolling or expanding (only with --walk-forward). |
| `--include-multitask` | Force multitask training per walk-forward window on for this run (only with --walk-forward). |
| `--include-sequence` | Force sequence training per walk-forward window on for this run (only with --walk-forward). |
| `--resume-run-id` | Continue an interrupted walk-forward run (only with --walk-forward): windows already finished under ml/versions/&lt;run-id&gt;/window_&lt;i&gt;/window_result.json are loaded, not retrained. |
| `--metrics` | Comma-separated tracked-metric names to restrict walk-forward tracking to for this run (only with --walk-forward). |
| `--seed` | Override config.json's seed (only with --multitask-only/--sequence-only) |
| `--ranking-objective` | Override config.json's ranking_loss.objective for this run only (only with --multitask-only/--sequence-only) |
| `--memory-profile` | low: train on a small machine (4 GB), slower: float32 reads, lazy sequence windows, a per-epoch checkpoint (passed to every trainer) |
| `--resume` | Continue a stopped `aq train` run with its own settings (the newest unfinished one, or RUN_ID): finished steps are skipped, a walk-forward continues its windows (a window reuses its dataset and baseline when they were written completely), the sequence trainer continues from its checkpoint |
| `--list-runs` | List the `aq train` and `aq cycle retrain` runs with their finished steps, and stop |
| `--dry-run` | Print the mode and settings it would run with, and stop |
| `--json` | With --list-runs: print JSON |

### `aq test`

Run the test suite (wraps pytest tests/), or a testing tool: new, where, slowest, clean-checkout, mutation, fuzz

```text
aq test [-h] [-k EXPR] [--lf] [--impacted] [--watch] [--repeat N] [--light-hypothesis] [--list-groups] [--group GROUP] [--top TOP] [--target TARGET] [--seconds SECONDS] [--json] [--dry-run] [--lean] [--parallel] [--coverage] [--changed] [--ruff] [--cli] [--lab] [--audit] [--risk] [--portfolio] [--features] [--data-pipeline] [--webui] [--ml] [--retraining] [--notifications] [--storage] [--live] [--evaluation] [--formal] [--meta] [--scripts] [paths ...]
```

| Flag | Meaning |
|---|---|
| `paths` | Test files or node ids to run, or a tool: new MODULE, where MODULE, slowest, clean-checkout, mutation, fuzz |
| `-k`, `--keyword` | Only tests whose name matches EXPR (pytest -k) |
| `--lf` | Only the tests that failed last time (pytest --lf) |
| `--impacted` | Only the tests that name a module changed since HEAD, without coverage |
| `--watch` | With --impacted or paths: rerun on every save (Ctrl-C stops) |
| `--repeat` | Run the given tests N times and report the flaky ones (exit 3) |
| `--light-hypothesis` | Fewer hypothesis examples, no too_slow health check (a 4 GB machine) |
| `--list-groups` | Print the test groups and their sizes |
| `--group` | With new: the test group (default: from the module's folder) |
| `--top` | With slowest: how many (default 15) |
| `--target` | With fuzz: one fuzz target |
| `--seconds` | With fuzz: how long atheris runs (default 60) |
| `--json` | With where, slowest, --repeat or --list-groups: print JSON |
| `--dry-run` | Print the pytest command (or, with new, the files) and stop |
| `--lean`, `--full` | Include the real `lean backtest .` integration test (tests/test_lean_backtest_ml_coverage.py, over an hour wall-clock) - excluded by default; --full is the same flag |
| `--parallel` | Run via pytest-xdist (-n auto) - off by default, multiple workers importing torch risk OOM on memory-constrained machines |
| `--coverage` | Every registered group (or the --&lt;subsystem&gt; groups given) in turn under coverage, appending, then the combined report of every tracked module; fails under pyproject's fail_under (100). One process at a time, for a small PC. |
| `--changed` | With --coverage, the fast gate before a commit: the tests that name each changed module (vs HEAD, new files included) run under coverage and every changed file must reach 100%; a fresh full coverage.json that already shows them covered passes at once. AGENTS.md 'Coverage: 100% after every commit'. |
| `--ruff` | Run `ruff check .` BEFORE pytest - a lint failure fails fast without paying the full suite's wall-clock first (mirrors ci.yml's python-lint job). |
| `--cli` | Run only the cli subsystem's tests (test_aq_devtools.py, test_aq_testtools.py, ...) |
| `--lab` | Run only the lab subsystem's tests (test_feature_registry.py, test_lab_dataset.py, ...) |
| `--audit` | Run only the audit subsystem's tests (test_redis_queue.py, test_hash_chain.py, ...) |
| `--risk` | Run only the risk subsystem's tests (test_risk_controls.py, test_asset_class_router.py, ...) |
| `--portfolio` | Run only the portfolio subsystem's tests (test_book_construction.py, test_hrp_allocation.py, ...) |
| `--features` | Run only the features subsystem's tests (test_training_splits.py, test_wide_panel.py, ...) |
| `--data-pipeline` | Run only the data-pipeline subsystem's tests (test_bar_synthesis.py, test_cftc_cot.py, ...) |
| `--webui` | Run only the webui subsystem's tests (test_neural_network_state.py, test_assets_status.py, ...) |
| `--ml` | Run only the ml subsystem's tests (test_gating.py, test_train_cross_sectional.py, ...) |
| `--retraining` | Run only the retraining subsystem's tests (test_artifacts.py, test_orchestrator.py, ...) |
| `--notifications` | Run only the notifications subsystem's tests (test_telegram_alerts.py, test_telegram_client.py, ...) |
| `--storage` | Run only the storage subsystem's tests (test_postgres_triggers.py, test_postgres_worker.py, ...) |
| `--live` | Run only the live subsystem's tests (test_live_credentials.py, test_live_credentials_io.py, ...) |
| `--evaluation` | Run only the evaluation subsystem's tests (test_multi_asset_round.py, test_v6610_research.py, ...) |
| `--formal` | Run only the formal subsystem's tests (test_formal_cases_drift.py, test_formal_differential_order_gate.py, ...) |
| `--meta` | Run only the meta subsystem's tests (test_ci_workflows.py, test_aq_test_ruff_flag.py, ...) |
| `--scripts` | Run only the scripts subsystem's tests (test_v669_book.py, test_model_book_decide.py, ...) |

### `aq backtest`

Run a Lean backtest (wraps lean backtest .)

```text
aq backtest [-h] [--image IMAGE] [--no-publish] [--dry-run]
```

| Flag | Meaning |
|---|---|
| `--image` | Override the Lean engine Docker image (default: pinned quantconnect/lean:17900, never the mutable :latest tag - see PINNED_LEAN_ENGINE_IMAGE's comment in aq_cli.py) |
| `--no-publish` | Leave the README, charts and evaluation reports alone (a research run) |
| `--dry-run` | Print the Lean command and where the config is frozen, and stop |

### `aq profile`

Profile the per-bar hot path (wraps scripts/profile_inference.py / scripts/profile_subsystems.py)

```text
aq profile [-h] [--iterations ITERATIONS] [--sort SORT] [--batched] [--no-gc] [--bucket-report] [--parallel] [--pool-workers POOL_WORKERS] [--symbols-per-bar SYMBOLS_PER_BAR] [--regime] [--topology] [--topology-cached] [--learned-topology] [--liquidity] [--gating] [--analyzer] [--indicators] [--options]
```

| Flag | Meaning |
|---|---|
| `--iterations` | Iterations to profile (default: 10000 for inference, 200 for --&lt;subsystem&gt; flags) |
| `--sort` | pstats sort key (default: cumulative) |
| `--batched` | Use the batched expert-inference path (with its precomputed stack caches) instead of a per-expert loop |
| `--no-gc` | Disable the GC around the profiled region, to isolate whether GC pauses drive tail latency (inference only) |
| `--bucket-report` | Print a 10-bucket-by-iteration-index duration breakdown, to check for a warmup effect (inference only) |
| `--parallel` | Run the ProcessPoolExecutor IPC-overhead benchmark against run_symbol_inference() (inference only) |
| `--pool-workers` | Worker process count for --parallel (default: profile_inference.py's own default, 4) |
| `--symbols-per-bar` | Symbols-per-bar grouping for --batched's sequence-batching comparison and --parallel's benchmark (default: profile_inference.py's own default, 74) |
| `--regime` | Profile only the regime subsystem (scripts/profile_subsystems.py) |
| `--topology` | Profile only the topology subsystem (scripts/profile_subsystems.py) |
| `--topology-cached` | Profile only the topology-cached subsystem (scripts/profile_subsystems.py) |
| `--learned-topology` | Profile only the learned-topology subsystem (scripts/profile_subsystems.py) |
| `--liquidity` | Profile only the liquidity subsystem (scripts/profile_subsystems.py) |
| `--gating` | Profile only the gating subsystem (scripts/profile_subsystems.py) |
| `--analyzer` | Profile only the analyzer subsystem (scripts/profile_subsystems.py) |
| `--indicators` | Profile only the indicators subsystem (scripts/profile_subsystems.py) |
| `--options` | Profile only the options subsystem (scripts/profile_subsystems.py) |

### `aq report`

Generate a Lean HTML report for a finished backtest

```text
aq report [-h] [backtest_dir] [result_id]
```

| Flag | Meaning |
|---|---|
| `backtest_dir` | Folder name under backtests/, e.g. 2026-07-04_13-06-51 (omit to list the newest runs) |
| `result_id` | Result JSON id, e.g. 1366365999 (default: the folder's only result) |

### `aq research`

Score any signal CSV (date,ticker,score) against the rank targets

```text
aq research [-h] --signal SIGNAL [--dataset DATASET] [--horizons HORIZONS] [--out OUT] [--json]
```

| Flag | Meaning |
|---|---|
| `--signal` | CSV with date, ticker, score columns |
| `--dataset` | Dataset CSV (default: ml/datasets/full_dataset.csv) |
| `--horizons` | Comma list of rank-target horizons (default: 5,20) |
| `--out` | Report path (default: ml/evaluation/signal_report.json) |
| `--json` | Print the report as JSON |

### `aq prove`

Build the Lean 4 proofs in formal/ (needs elan + Mathlib cache)

```text
aq prove [-h] [--module MODULE] [--regen-cases] [--check-sorry] [--list] [--json]
```

| Flag | Meaning |
|---|---|
| `--module` | Build one spec only, e.g. BookNeutrality (default: all) |
| `--regen-cases` | Also regenerate aether_quant/_formal_cases/ (the differential test inputs/outputs) |
| `--check-sorry` | Only scan formal/AetherFormal/*.lean for sorry/admit (no Lean needed) |
| `--list` | List the specs and stop |
| `--json` | With --list or --check-sorry: print JSON |

### `aq cycle`

The research cycle: rounds, generations, retraining, handover

```text
aq cycle [-h] {research,status,daily,decide,retrain,promote,schedule} ...
```

#### `aq cycle research`

One stage of a pre-registered research round

```text
aq cycle research [-h] --round ROUND [--draft DRAFT] [--only [ONLY ...]] [--draws DRAWS] [--force] [--trial TRIAL] [--digest DIGEST] {rules,score,placebo,gate,pbo,freeze,hold,report}
```

| Flag | Meaning |
|---|---|
| `stage` |  |
| `--round` | The round's rule file (written once, hash checked at every stage) |
| `--draft` | rules only: the JSON to write as the round's rule file |
| `--only` | score only: these trials |
| `--draws` | placebo only: draws per null (default: 100) |
| `--force` | Rescore a trial already scored |
| `--trial` | freeze / hold: the candidate |
| `--digest` | hold: the freeze's digest |

#### `aq cycle status`

Generations, shares, decay, and what is due (writes ml/generations/status.json)

```text
aq cycle status [-h] [--ledger-file LEDGER_FILE] [--json]
```

| Flag | Meaning |
|---|---|
| `--ledger-file` | Read this generations.jsonl instead of the forward-ledger branch |
| `--json` | Print the status as JSON (the default output is JSON too) |

#### `aq cycle daily`

Today's row for each generation, and the allocation (the scheduled Action's job)

```text
aq cycle daily [-h] [--ledger-file LEDGER_FILE] [--dry-run]
```

| Flag | Meaning |
|---|---|
| `--ledger-file` | The generations.jsonl to append to (default: ml/cycle/generations.jsonl) |
| `--dry-run` | Compute on a temporary copy of the ledger |

#### `aq cycle decide`

A host's dated decision for a generation that can't decide on a bare runner

```text
aq cycle decide [-h] --generation GENERATION --weights WEIGHTS --ledger-file LEDGER_FILE --session SESSION
```

| Flag | Meaning |
|---|---|
| `--generation` |  |
| `--weights` | CSV of ticker,weight |
| `--ledger-file` | forward/decisions.jsonl in a worktree of the branch |
| `--session` |  |

#### `aq cycle retrain`

Retrain on this machine or the training Codespace, resumable (RAM preflight; --smoke proves the plumbing anywhere)

```text
aq cycle retrain [-h] [--host {local,codespace}] [--procedure PROCEDURE] [--smoke] [--dry-run] [--if-due] [--memory-profile {standard,low}] [--min-ram-gb MIN_RAM_GB] [--score-end SCORE_END] [--estimate] [--resume [RUN_ID]] [--list-runs]
```

| Flag | Meaning |
|---|---|
| `--host` | Required, except with --resume or --estimate |
| `--procedure` | A procedure in scripts/cycle_retrain.py: k06, k07, or stack (the model stack: multitask, sequence, gating and the walk-forward) |
| `--smoke` | Every stage on a tiny synthetic panel |
| `--dry-run` | Print the stages and the preflight, and stop |
| `--if-due` | Do nothing unless `aq cycle status` says a retrain is due |
| `--memory-profile` | low: train the stack on a 4 GB machine (lazy sequence windows, chunked float32 reads, per-epoch checkpoints); slower |
| `--min-ram-gb` | Override the profile's minimum RAM (standard 14, low 3.5) |
| `--score-end` | A stack run: the last date of the walk-forward scores |
| `--estimate` | Print each memory profile's estimated peak for the active dataset, and stop |
| `--resume` | Continue a stopped retrain with its own settings (the newest unfinished one, or RUN_ID): finished stages are skipped, the walk-forward and the sequence trainer continue where they stopped |
| `--list-runs` | List the retrain and `aq train` runs with their finished stages, and stop |

#### `aq cycle promote`

Change a generation's stage, by rule R-ADMIT1 (never touches broker settings)

```text
aq cycle promote [-h] --generation GENERATION --to {shadow,ramping,active,fading,winding_down,retired,rejected} [--ledger-file LEDGER_FILE]
```

| Flag | Meaning |
|---|---|
| `--generation` |  |
| `--to` |  |
| `--ledger-file` | Read this generations.jsonl instead of the forward-ledger branch |

#### `aq cycle schedule`

Show or install a weekly retrain-if-due job on a machine with the RAM

```text
aq cycle schedule [-h] [--platform {windows,linux}] [--host {local,codespace}] [--dry-run] {show,install}
```

| Flag | Meaning |
|---|---|
| `schedule_command` |  |
| `--platform` |  |
| `--host` |  |
| `--dry-run` | install: print the job and register nothing |

### `aq api`

Start the FastAPI monitoring server (default 127.0.0.1:8001), or check one is answering

```text
aq api [-h] [--host HOST] [--port PORT] [--no-reload] [--check]
```

| Flag | Meaning |
|---|---|
| `--host` | Bind address (default 127.0.0.1) |
| `--port` | Port (default 8001) |
| `--no-reload` | Do not restart on code changes |
| `--check` | GET /health on a running server (exit 1 if it does not answer) |

### `aq webui`

Start the webui dev server (npm run dev), or the dashboard image with --docker

```text
aq webui [-h] [--docker] [--build] [--image IMAGE] [--port PORT] [--open] [--data DIR]
```

| Flag | Meaning |
|---|---|
| `--docker` | Run the dashboard image (demo data unless --data) instead of the dev server |
| `--build` | With --docker: build the image from this checkout first |
| `--image` | With --docker: the image to run |
| `--port` | The port (default 8080), for the dev server and --docker |
| `--open` | Open the browser on it |
| `--data` | With --docker: serve this tree (visualization/, ml/) instead of the demo |

### `aq docker`

Docker Compose shortcuts

```text
aq docker [-h] {up,build,down,ps,logs} ...
```

#### `aq docker up`

Start infra services

```text
aq docker up [-h] [--lean | --all] [--dry-run]
```

| Flag | Meaning |
|---|---|
| `--lean` | Start via the lean Compose profile |
| `--all` | Start the full stack, including all workers |
| `--dry-run` | Print the docker command |

#### `aq docker build`

Rebuild the consolidated aether-quant-engine image (app + every worker)

```text
aq docker build [-h] [--no-cache] [--dry-run]
```

| Flag | Meaning |
|---|---|
| `--no-cache` | Build every layer again |
| `--dry-run` | Print the docker command |

#### `aq docker down`

Stop and remove the Compose services

```text
aq docker down [-h] [--dry-run]
```

| Flag | Meaning |
|---|---|
| `--dry-run` | Print the docker command |

#### `aq docker ps`

The Compose services and their state

```text
aq docker ps [-h] [--dry-run]
```

| Flag | Meaning |
|---|---|
| `--dry-run` | Print the docker command |

#### `aq docker logs`

A service's recent logs (all services without one)

```text
aq docker logs [-h] [--tail TAIL] [--follow] [--dry-run] [service]
```

| Flag | Meaning |
|---|---|
| `service` |  |
| `--tail` | Lines per service (default 100) |
| `--follow` | Keep printing new lines |
| `--dry-run` | Print the docker command |

### `aq config`

Show or edit config.json

```text
aq config [-h] {get,keys,set,diff,validate,preset} ...
```

#### `aq config get`

Print a config.json value

```text
aq config get [-h] [--json] dotted_path
```

| Flag | Meaning |
|---|---|
| `dotted_path` |  |
| `--json` | Print the value as JSON |

#### `aq config keys`

List leaf key paths (optionally scoped to a prefix)

```text
aq config keys [-h] [--json] [dotted_prefix]
```

| Flag | Meaning |
|---|---|
| `dotted_prefix` |  |
| `--json` | Print the paths as a JSON list |

#### `aq config set`

Set a config.json value (JSON-parsed, string fallback); a type change needs --force

```text
aq config set [-h] [--dry-run] [--force] dotted_path value
```

| Flag | Meaning |
|---|---|
| `dotted_path` |  |
| `value` |  |
| `--dry-run` | Print old -&gt; new, write nothing |
| `--force` | Allow the value to change type (bool to string, say) |

#### `aq config diff`

Leaf keys added, removed and changed against config.json at a git ref (rule 9 review)

```text
aq config diff [-h] [--json] [ref]
```

| Flag | Meaning |
|---|---|
| `ref` | A commit or tag (default HEAD) |
| `--json` | Print JSON instead of text |

#### `aq config validate`

Duplicate keys, NaN or inf, and (config.json) the sections main.py reads

```text
aq config validate [-h] [--json]
```

| Flag | Meaning |
|---|---|
| `--json` | Print JSON instead of text |

#### `aq config preset`

List/show/apply a named config preset (phase_v2.presets)

```text
aq config preset [-h] [--list | --show NAME | --apply NAME] [--dry-run]
```

| Flag | Meaning |
|---|---|
| `--list` | List available presets |
| `--show` | Print one preset's overrides |
| `--apply` | Apply one preset's overrides to config.json |
| `--dry-run` | With --apply: print old -&gt; new, write nothing |

### `aq lean`

Show or edit lean.json (same shape as `aq config`)

```text
aq lean [-h] {get,keys,set,diff,validate} ...
```

#### `aq lean get`

Print a lean.json value

```text
aq lean get [-h] [--json] dotted_path
```

| Flag | Meaning |
|---|---|
| `dotted_path` |  |
| `--json` | Print the value as JSON |

#### `aq lean keys`

List leaf key paths (optionally scoped to a prefix)

```text
aq lean keys [-h] [--json] [dotted_prefix]
```

| Flag | Meaning |
|---|---|
| `dotted_prefix` |  |
| `--json` | Print the paths as a JSON list |

#### `aq lean set`

Set a lean.json value (JSON-parsed, string fallback); a type change needs --force

```text
aq lean set [-h] [--dry-run] [--force] dotted_path value
```

| Flag | Meaning |
|---|---|
| `dotted_path` |  |
| `value` |  |
| `--dry-run` | Print old -&gt; new, write nothing |
| `--force` | Allow the value to change type (bool to string, say) |

#### `aq lean diff`

Leaf keys added, removed and changed against lean.json at a git ref (rule 9 review)

```text
aq lean diff [-h] [--json] [ref]
```

| Flag | Meaning |
|---|---|
| `ref` | A commit or tag (default HEAD) |
| `--json` | Print JSON instead of text |

#### `aq lean validate`

Duplicate keys, NaN or inf, and (config.json) the sections main.py reads

```text
aq lean validate [-h] [--json]
```

| Flag | Meaning |
|---|---|
| `--json` | Print JSON instead of text |

### `aq retrain`

Low-level orchestrator stage (python -m retraining.orchestrator STAGE); for a whole retrain use `aq cycle retrain`

```text
aq retrain [-h] [--dry-run] {plan,train,train_topology,train_gating,train_multitask,train_sequence,train_strategy_selector,validate,backtest,commit,promote,rollback,status,auto-rollback} ...
```

| Flag | Meaning |
|---|---|
| `--dry-run` | Print the orchestrator command |
| `stage` |  |
| `retrain_args` | Passed through verbatim, e.g. --version-id &lt;uuid&gt; |

### `aq backfill`

Whole-universe bulk backfills (python -m data_pipeline.&lt;target&gt;_backfill); each is a dry run unless given --apply. For one ad-hoc ticker, use aq fetch.

```text
aq backfill [-h] {dividends,fred,yfinance} ...
```

| Flag | Meaning |
|---|---|
| `target` |  |
| `backfill_args` | Passed through verbatim, e.g. --apply --tickers AAPL MSFT (dividends/yfinance), or --series DGS10 (fred) |

### `aq paper-readiness`

Is the system ready to run on paper (Postgres trading history, broker config)? live-readiness is the later paper-to-live scorecard

```text
aq paper-readiness [-h] [--json]
```

| Flag | Meaning |
|---|---|
| `--json` | Print the checks as JSON |

### `aq clean`

List (dry run by default) and delete regenerable ml/ artifacts: old candidate versions, older backups, walk-forward window datasets

```text
aq clean [-h] [--yes] [--keep-versions KEEP_VERSIONS] [--keep-backups KEEP_BACKUPS] [--strip-walk-forward-datasets] [--apply] [--json] {ml,coverage,caches,build}
```

| Flag | Meaning |
|---|---|
| `target` | ml: old versions and backups; coverage: coverage-report/; caches: __pycache__ and tool caches; build: build/ and dist/ |
| `--yes` | With --apply: confirm without a prompt |
| `--keep-versions` | newest N ml/versions directories to keep (default 5) |
| `--keep-backups` | newest N ml/_backup_* directories to keep (default 1) |
| `--strip-walk-forward-datasets` | also list the regenerable window_*/full_dataset.csv etc. inside kept walk-forward runs |
| `--apply` | delete the listed items (default: dry run) |
| `--json` | Print JSON instead of text |

### `aq trade-lock`

Manually override the sticky total-drawdown trade lock

```text
aq trade-lock [-h] (--on | --off | --auto | --status) [--account ACCOUNT] [--yes] [--dry-run] [--json]
```

| Flag | Meaning |
|---|---|
| `--on` | Force trading paused |
| `--off` | Force trading resumed |
| `--auto` | Return to fully automatic behavior |
| `--status` | Print the current override state |
| `--account` | A named account's override (state/accounts/&lt;id&gt;/overrides.json) instead of config.json |
| `--yes` | Confirm loosening the lock without a prompt |
| `--dry-run` | Print old -&gt; new and change nothing |
| `--json` | With --status: print JSON |

### `aq kill-switch`

Manually override / inspect the automated production kill switch

```text
aq kill-switch [-h] (--arm | --disarm | --auto | --status | --history) [--limit LIMIT] [--account ACCOUNT] [--yes] [--dry-run] [--json]
```

| Flag | Meaning |
|---|---|
| `--arm` | Force kill-switch evaluation on |
| `--disarm` | Force kill-switch evaluation off |
| `--auto` | Defer to phase_v2.risk.kill_switch.enabled |
| `--status` | Print the current override state |
| `--history` | List recorded kill-switch trips from the audit log |
| `--limit` | Max --history rows (default 50) |
| `--account` | A named account's override (state/accounts/&lt;id&gt;/overrides.json) instead of config.json |
| `--yes` | Confirm disarming without a prompt |
| `--dry-run` | Print old -&gt; new and change nothing |
| `--json` | With --status: print JSON |

### `aq fetch`

Ad-hoc fetch of historical OHLCV from Yahoo Finance for a ticker not yet in config.json. For a whole-universe bulk refresh instead (dividends/FRED series/Yahoo gaps), see `aq backfill`.

```text
aq fetch [-h] --ticker TICKER --start START --end END [--apply] [--expiry EXPIRY] [--strike STRIKE] [--right {call,put}] [--contract-month CONTRACT_MONTH] [--family-ticker FAMILY_TICKER] [--json] {crypto,stock,futures,options,forex}
```

| Flag | Meaning |
|---|---|
| `asset_class` | Asset class (picks the Lean data_path/market convention) |
| `--ticker` | Internal ticker, e.g. AAPL or BTCUSD |
| `--start` | Start date, ISO 8601 YYYY-MM-DD |
| `--end` | End date, ISO 8601 YYYY-MM-DD |
| `--apply` | Actually write the zip file and update config.json (default: dry run, report only) |
| `--expiry` | Contract expiry, YYYY-MM-DD (required for asset_class futures/options; requires IB, see 'aq ib status') |
| `--strike` | Strike price (required for asset_class options) |
| `--right` | Option right (required for asset_class options) |
| `--contract-month` | Futures only: YYYYMM - fetch a specific dated contract instead of the continuous front-month (e.g. for building real historical term structure with a second, later --contract-month fetch under the same --family-ticker) |
| `--family-ticker` | Groups multiple fetched contracts under one root for offline training's derivatives-macro features (train.py::build_derivatives_macro_features_by_date()) - e.g. two futures/options fetches sharing --family-ticker ES. Defaults to --ticker itself (a single, ungrouped contract). |
| `--json` | Print the fetch report as JSON |

### `aq ib`

Check Interactive Brokers configuration/connectivity

```text
aq ib [-h] {status} ...
```

#### `aq ib status`

Report disabled / credentials-missing / reachable

```text
aq ib status [-h] [--json]
```

| Flag | Meaning |
|---|---|
| `--json` | Print JSON instead of text |

### `aq assets`

Report multi-asset-class (futures/options/FRED) readiness

```text
aq assets [-h] {status} ...
```

#### `aq assets status`

Report IB/futures/options/FRED readiness at a glance

```text
aq assets status [-h] [--json]
```

| Flag | Meaning |
|---|---|
| `--json` | Print JSON instead of text |

### `aq evaluate`

Offline, cost-aware evaluation of the cross-sectional rank book - net Sharpe/turnover/capacity/cost-stress from the active model + dataset, without a Lean backtest

```text
aq evaluate [-h] [--rank-book] [--account ACCOUNT] [--capacity] [--stress] [--calibrate-edge] [--all] [--walk-forward-summary] [--run-id RUN_ID] [--ablation] [--variants VARIANTS] [--calibrate-book-spread] [--book-spread-percentile BOOK_SPREAD_PERCENTILE] [--calibrate-confidence-threshold] [--confidence-threshold-percentile CONFIDENCE_THRESHOLD_PERCENTILE] [--calibrate-rolling-ic-floor] [--rolling-ic-floor-percentile ROLLING_IC_FLOOR_PERCENTILE] [--reconcile-features] [--symbol SYMBOL] [--reconcile-book-history] [--book-history-path BOOK_HISTORY_PATH] [--replay-hysteresis] [--reconcile-run-index RECONCILE_RUN_INDEX | --reconcile-all-runs] [--replay-kill-switch] [--replay-rolling-ic-gate] [--simulate-limit-fills] [--limit-fill-offset-sweep LIMIT_FILL_OFFSET_SWEEP] [--monte-carlo] [--mc-runs MC_RUNS] [--mc-block-size MC_BLOCK_SIZE] [--mc-seed MC_SEED] [--mc-method {block,iid}] [--benchmarks] [--hysteresis-survives-veto] [--as-live] [--audit-backtest] [--backtest-dir BACKTEST_DIR] [--period START..END] [--attribute-lean] [--lean-monte-carlo] [--lean-stats] [--forward-ledger] [--ledger-branch LEDGER_BRANCH] [--ledger-file LEDGER_FILE] [--data-dir DATA_DIR] [--alpha-proof] [--backtest-stats] [--lean-report] [--classification] [--classification-parity] [--paper-check] [--reference-dir REFERENCE_DIR] [--start START] [--end END] [--interest-rate-file INTEREST_RATE_FILE] [--trading-days TRADING_DAYS] [--book-history-file BOOK_HISTORY_FILE] [--audit-fills] [--book-run-index BOOK_RUN_INDEX] [--max-open-sessions MAX_OPEN_SESSIONS] [--factor-exposure] [--calibrate-volatility-threshold] [--volatility-threshold-percentile VOLATILITY_THRESHOLD_PERCENTILE] [--ic-by-class] [--audit-gates] [--audit-data] [--data-root DATA_ROOT] [--audit-heads] [--audit-leakage] [--overfit-report] [--pbo] [--trial-returns TRIAL_RETURNS] [--factor-spanning] [--signal SIGNAL] [--calibrate-sim-lean] [--calibration-file CALIBRATION_FILE] [--audit-features] [--permutation] [--dataset DATASET] [--model {sequence,multitask}] [--head HEAD] [--split SPLIT] [--preset PRESET] [--json] [--list]
```

| Flag | Meaning |
|---|---|
| `--rank-book` | Simulate the rank book net of costs |
| `--account` | Evaluate with one account's tightened limits (accounts.json), as its deployment runs |
| `--capacity` | Breadth (top_n sweep) + capacity estimate |
| `--stress` | Re-run at 1x/2x/3x the configured cost |
| `--calibrate-edge` | Print an edge_bps_per_rank_unit calibrated from this split's realized rank-vs-return relationship |
| `--all` | Run --rank-book, --capacity, --stress, --calibrate-edge, --benchmarks, --monte-carlo and --classification together |
| `--walk-forward-summary` | Print an already-written ml/versions/walk-forward-*/walk_forward_summary.json - never runs training itself; run `aq train --walk-forward` first. |
| `--run-id` | Specific walk-forward run-id to read with --walk-forward-summary (default: the most recent run). |
| `--ablation` | Run the adaptive-machinery ablation harness - runtime-only mechanisms (gating, topology sizing, the net-edge gate, ...) honestly report not_offline_measurable rather than a fabricated number. Not included in --all. |
| `--variants` | Comma-separated ablation variant names to run with --ablation (default: phase_v2.evaluation.ablation.variants from config.json). |
| `--calibrate-book-spread` | Print a min_rank_confidence_spread calibrated from this split's actual raw-score dispersion (the same resolved rank-signal blend and book top_n/bottom_n main.py uses live). Not included in --all - loads both models' predictions, a heavier run like --ablation. |
| `--book-spread-percentile` | Percentile (0-1) of the per-date confidence-spread distribution to use as the calibrated floor with --calibrate-book-spread (default: 0.10). |
| `--calibrate-confidence-threshold` | Print a min_confidence_to_trade (and, when book-selection data is available, a separate min_confidence_to_trade_book_selected) calibrated from this split's real confidence-vs-forward-return relationship, mirroring --calibrate-book-spread's discipline. Not included in --all. |
| `--confidence-threshold-percentile` | Percentile (0-1) of the paying-trade confidence distribution to use as the calibrated floor with --calibrate-confidence-threshold (default: 0.10). |
| `--calibrate-rolling-ic-floor` | Print a phase_v2.rolling_ic_gate.min_rolling_mean_ic calibrated from this split's real walk-forward rolling trailing-IC distribution (portfolio/rolling_ic_gate.py's own aggregation, no-lookahead - see evaluation/rolling_ic_gate_calibration.py's docstring), mirroring --calibrate-book-spread's discipline. Not included in --all - loads both models' predictions, a heavier run like --ablation. |
| `--rolling-ic-floor-percentile` | Percentile (0-1) of the rolling-IC distribution to use as the calibrated floor with --calibrate-rolling-ic-floor (default: 0.10). |
| `--reconcile-features` | Diff ONE symbol's logged live feature values (book_history.jsonl's optional 'feature_snapshot' key, written when phase_v2.diagnostics.book_history.include_feature_snapshot is on and the symbol is in feature_snapshot_symbols) against full_dataset.csv's same (ticker, date) row - per-feature deltas, worst offenders first. Requires --symbol. Not included in --all - investigation-only. |
| `--symbol` | Ticker to reconcile with --reconcile-features (e.g. --symbol XOM). Matched case-insensitively against each record's feature_snapshot keys. |
| `--reconcile-book-history` | Compare a real Lean backtest's logged book selections (phase_v2.diagnostics.book_history) against a fresh offline re-derivation of the same raw scores on those same dates - true ground truth for diagnosing offline-vs-live divergence. Not included in --all - loads both models' predictions like --calibrate-book-spread. |
| `--book-history-path` | Path to the book_history.jsonl log to reconcile with --reconcile-book-history (default: phase_v2.diagnostics.book_history.output_path from config.json). |
| `--replay-hysteresis` | With --reconcile-book-history, replay offline's own hysteresis-aware selection walk-forward across the log's dates (carrying held allocations forward, same as main.py's live book) instead of reconciling each date independently - tells a real divergence apart from the live book correctly holding an incumbent a from-scratch reselection wouldn't naturally pick. |
| `--reconcile-run-index` | With --reconcile-book-history, reconcile only the run at this 0-indexed position within the log's own run-segmented history (negative indices count from the end, -1 == most recent - the default). book_history.jsonl is a cumulative, never-rotated log - every historical real backtest's records are appended forever - so reconciling without this flag defaults to the LATEST run only, never a silent cross-run merge. |
| `--reconcile-all-runs` | With --reconcile-book-history, reconcile EVERY run segment independently (each its own held-allocations/summary, never merged across a run boundary) instead of just the most recent - for investigating an older run's own numbers, not for combining them into one figure. |
| `--replay-kill-switch` | Day-by-day OFFLINE replay of the kill-switch + sticky trade-lock state machine (evaluation/kill_switch_replay.py) against the rank book's own simulated return series - an explicitly approximate estimate of how much of the run would have been locked out, without needing a real Lean backtest. Not included in --all - investigation-only (an approximation: no intraday fills). |
| `--replay-rolling-ic-gate` | Day-by-day, no-lookahead OFFLINE replay of portfolio/rolling_ic_gate.py's engagement decision (evaluation/rolling_ic_gate_replay.py) at phase_v2.net_performance's rebalance cadence, with a per-era breakdown against the three known bad eras this round's research found - the critical pre-main.py checkpoint before flipping phase_v2.rolling_ic_gate.enabled live. Not included in --all - investigation-only. |
| `--simulate-limit-fills` | Offline counterfactual (evaluation/limit_fill_simulator.py) estimating how often a real limit order would fill vs. time out, using the existing dataset's own high/low bars and phase_v2.limit_orders' pricing/timeout config - without needing a real Lean backtest. Not included in --all - investigation-only (an estimate from daily high/low bars). |
| `--limit-fill-offset-sweep` | Comma-separated offset_multiplier values to sweep with --simulate-limit-fills (default: a single run at the configured phase_v2.limit_orders.offset_multiplier). |
| `--monte-carlo` | Monte Carlo simulation testing layer (evaluation/monte_carlo.py) - stationary-block bootstraps the base rank-book run's daily net returns into --mc-runs alternative equity histories, writing ml/evaluation/monte_carlo.json + monte_carlo_curves.npz and refreshing the README's Monte Carlo section (curves chart + red average line + foldable deep stats). Requires/implies the base --rank-book simulation. Included in --all. |
| `--mc-runs` | Number of Monte Carlo resampled equity runs (default: 1000). |
| `--mc-block-size` | Stationary block bootstrap block length in days (default: 20). |
| `--mc-seed` | RNG seed - pinned by default so the README stays stable unless results change. |
| `--mc-method` | Resampling method (default: block = stationary block bootstrap). |
| `--benchmarks` | Benchmark comparison (evaluation/benchmark_comparison.py + evaluation/public_benchmarks.py) - runs the momentum/mean-reversion/random-entry strategy baselines AND the SP500 buy-and-hold + daily-rebalanced 60/40 SPY-TLT public baselines over the SAME dataset window/split as the rank book, writing ml/evaluation/benchmark_comparison.json and refreshing the README's Benchmark Comparison section. Included in --all. |
| `--hysteresis-survives-veto` | With --reconcile-book-history --replay-hysteresis, keep offline's hysteresis anchor across a date live VETOED. Default resets it, which replays logs from the older live code (where a veto wiped live's memory); pass this flag for a newer run's log (the last formed book survives a veto). |
| `--as-live` | Also run the rank book AS-LIVE (evaluation/live_parity.py) - the blended rank head, percentile hysteresis, the live confidence-spread and rolling-IC gates, hold-on-veto, confidence-weighted sizing, one-day-stale forex/crypto features, a one-bar entry lag and the max-holding age exit - and report it next to the idealized run (ml/evaluation/rank_book_simulation_as_live.json), with and without the Almgren impact model. Opt-in, not included in --all. |
| `--audit-backtest` | Order-level audit of one finished Lean backtest folder (exposure per asset class, book-member vs non-member entries, overlapping limit orders, holding periods, fees, Sharpe with and without a risk-free rate, gate vetoes, engine-log teardown) -&gt; ml/evaluation/backtest_audit.json. Needs no dataset or model. Not included in --all. |
| `--backtest-dir` | With --audit-backtest or --audit-fills, the backtests/&lt;timestamp&gt; folder to audit (default: the newest). |
| `--period` | With --audit-backtest, also summarise this sub-period (ISO dates, repeatable): return, drawdown, Sharpe, closed trades and realized P&L per class - BT2 spans the backtest split and the holdout and is judged on each. |
| `--attribute-lean` | One finished Lean run's daily P&L rebuilt per ticker from its order events and the data zips' closes, split into main book / legacy signal / bond and forex sleeves / crypto core and graduates, fees per route, and reconciled with Lean's equity curve (--backtest-dir, --period, --book-history-file) -&gt; ml/evaluation/lean_attribution.json. Needs no dataset or model. |
| `--lean-monte-carlo` | Block-bootstrap a finished Lean run's own daily equity returns (--backtest-dir, --mc-runs, --mc-block-size, --mc-seed) -&gt; ml/evaluation/monte_carlo_lean.json; the README Monte Carlo block shows it next to the offline book. Needs no dataset or model. |
| `--lean-stats` | A finished Lean run's printed Sharpe / Sortino / PSR next to an exact replica of Lean's formulas on the shipped and the older risk-free file, at 252 and 365 days a year (--backtest-dir, --interest-rate-file, --trading-days) -&gt; ml/evaluation/lean_stats_&lt;run&gt;.json. Needs no dataset or model. |
| `--forward-ledger` | Verify the forward ledger's hash chain and judge each frozen candidate (sessions, Sharpe, alpha t, what this many sessions can show), read from the branch the scheduled Action writes (--ledger-branch) or a file (--ledger-file). Exit 1 on a broken chain. |
| `--ledger-branch` | the forward ledger's branch (default forward-ledger) |
| `--ledger-file` | read the forward ledger from this file instead of its branch |
| `--data-dir` | The Lean run's data root for --alpha-proof (data_wide, data_crypto_wide; default data): closes read from any other root come back empty. |
| `--alpha-proof` | Proof of alpha for one finished Lean run (--backtest-dir, default the README pin or the newest run): the strategy without its T-bill sweep, per period (full / backtest / holdout / the fresh weeks after 2026-10-16) - Sharpe with a bootstrap 95% interval, alpha against SPY / AGG / BTC with a Newey-West t, PSR and the deflated Sharpe over the trial registry - and the descriptive R-ALPHA1 verdict -&gt; ml/evaluation/alpha_proof.json. |
| `--backtest-stats` | The README's Backtest Statistics for one finished Lean run (--backtest-dir, default the README pin or the newest run): general characteristics, performance, runs and drawdowns, implementation shortfall, efficiency (PSR, deflated Sharpe), classification scores and per-class attribution, for the portfolio and the strategy without its T-bill sweep -&gt; ml/evaluation/backtest_statistics.json. Needs no dataset or model. |
| `--lean-report` | Every run-folder tool for one finished Lean run in order (--lean-stats, --lean-monte-carlo, --audit-backtest with the config's backtest and holdout periods, --attribute-lean, --audit-fills, --backtest-stats), then the README. With --backtest-dir it also pins the README to that run. `aq backtest` runs it automatically. |
| `--classification` | Accuracy / precision / recall / F1 / negative log-loss of the --model's direction_20d head on --split -&gt; ml/evaluation/classification_scores_&lt;model&gt;.json (the Backtest Statistics' offline rows). Included in --all. |
| `--classification-parity` | A Lean run's logged book-call probabilities (diagnostics.book_history.include_probabilities) against the same direction_20d head scored offline on the same rows, to a pre-registered tolerance (--backtest-dir, --dataset) -&gt; ml/evaluation/classification_parity.json. Needs the dataset and the model. |
| `--paper-check` | The paper-period checklist (veto rate, exposure, fills, slippage, fees, strategy vs sweep P&L, turnover) of --backtest-dir (a paper or Lean run folder, optionally --start/--end) against the bands of the contiguous 6-rebalance windows of --reference-dir (default: the README pin) -&gt; ml/evaluation/paper_check.json. |
| `--reference-dir` | With --paper-check, the reference Lean run (default: the README pin). |
| `--start` | With --paper-check, first date (YYYY-MM-DD) of the window to check. |
| `--end` | With --paper-check, last date (YYYY-MM-DD) of the window to check. |
| `--interest-rate-file` | With --lean-stats, price the run on this risk-free file only (Lean's interest-rate.csv format). |
| `--trading-days` | With --lean-stats, annualise with this many days a year only (default: both 252 and 365). |
| `--book-history-file` | With --attribute-lean, the run's per-run book history (default: the visualization/book_history/*.jsonl that started closest to the run folder's timestamp). |
| `--audit-fills` | Every fill of one finished Lean backtest against the dataset's open and the Lean zip's own open, per asset class and order type, plus the dataset-vs-zip gap on the traded dates -&gt; ml/evaluation/fill_price_audit.json. Needs no model. Not included in --all. |
| `--book-run-index` | With --audit-backtest: which run of the cumulative book_history.jsonl belongs to --backtest-dir (-1 = the latest run, -2 = the one before it, ...). Older runs audited at the default pair the wrong book. |
| `--max-open-sessions` | With --audit-backtest, flag limit orders open longer than this many weekday sessions (default: phase_v2.limit_orders.unfilled_timeout_bars + 1; the timeout is counted in equity bars, so calendar days over a weekend made correct cancellations look stale). |
| `--factor-exposure` | Regress the rank book's daily net returns on SPY and a momentum factor (R2, loadings, alpha Sharpe) -&gt; ml/evaluation/factor_exposure.json. Opt-in, not included in --all. |
| `--calibrate-volatility-threshold` | Per-asset-class percentile of realized annualized volatility, with a suggested phase_v2.topology.elevated_volatility_threshold (crypto sits structurally above the global 0.45 cutoff). Opt-in, not included in --all. |
| `--volatility-threshold-percentile` | With --calibrate-volatility-threshold, the percentile used as the cutoff (default: 0.80). |
| `--ic-by-class` | Within- vs between-asset-class rank IC of the live blended score on --split (-&gt; ml/evaluation/class_ic_audit.json). Needs the model and dataset. Not included in --all. |
| `--audit-gates` | The rolling-IC gate's own reading vs the fully resolved IC on every date of --split, false-veto share and lag (-&gt; ml/evaluation/gate_audit.json). Not included in --all. |
| `--audit-data` | Audit every universe zip (coverage, gaps, suspicious moves, OHLC sanity, quote coverage, factor files) and write a size+SHA-256 manifest of the data root (-&gt; ml/evaluation/data_audit.json). No model. |
| `--data-root` | With --audit-data, the Lean data root to audit (default: data). |
| `--audit-heads` | Every model head and submodel against its own promotion gate, marking what the live path reads (-&gt; ml/evaluation/head_audit.json). Reads only ml/*_training_metrics.json. |
| `--audit-leakage` | Label/feature leakage audit - tail NaN, label shuffle, single-feature IC, asset-identity prior (-&gt; ml/evaluation/leakage_audit.json). |
| `--overfit-report` | Train / validation / backtest rank IC per head and the gap (-&gt; ml/evaluation/overfit_report.json). |
| `--pbo` | Probability of backtest overfitting (CSCV) over a trials' daily-returns table (-&gt; ml/evaluation/pbo.json). |
| `--trial-returns` | With --pbo, a parquet/csv of daily returns, one column per trial (default: ml/evaluation/v643/trial_returns.parquet). |
| `--factor-spanning` | Regress a signal's long/short return on five factor baselines; needs --signal (-&gt; ml/evaluation/factor_spanning.json). |
| `--signal` | With --factor-spanning, a CSV of date,ticker,score. |
| `--calibrate-sim-lean` | Decompose the offline-vs-Lean gap of a scripts/lean_calibration.py report rung by rung; needs --calibration-file (-&gt; ml/evaluation/sim_lean_gap.json). |
| `--calibration-file` | With --calibrate-sim-lean, the lean_calibration.py JSON report. |
| `--audit-features` | Model-input feature quality - ticker-ID suspects, class-constant features, per-split IC sign (-&gt; ml/evaluation/feature_quality_audit.json). |
| `--permutation` | With --audit-features, also the multitask model's validation IC drop per shuffled feature (slow). |
| `--dataset` | With --ic-by-class / --audit-gates / --audit-features / --reconcile-features / --reconcile-book-history (also --audit-fills and the rank-book runs), a dataset CSV other than ml/datasets/full_dataset.csv, which holds all four splits (train / validation / backtest / holdout). |
| `--model` | Default: sequence |
| `--head` | Model head to evaluate, e.g. rank_20d/rank_5d (default: rank_20d) |
| `--split` | Dataset split to evaluate: train/validation/backtest/all (default: backtest) |
| `--preset` | Overlay phase_v2.presets.&lt;name&gt; in memory only (never writes config.json) - see `aq config preset --list` |
| `--json` | Print the full report as JSON instead of a summary |
| `--list` | List the tool groups and their flags, and stop |

### `aq render-lean-config`

Render gitignored lean.live.json from .env.live / AETHER_* env vars (secrets for live/paper)

```text
aq render-lean-config [-h] [--base BASE] [--out OUT] [--env-file ENV_FILE] [--account ACCOUNT] [--dry-run] [--check]
```

| Flag | Meaning |
|---|---|
| `--base` | Empty tracked template (default: lean.json) |
| `--out` | Rendered secret-bearing output (default: lean.live.json) |
| `--env-file` | Secrets file (default: .env.live) |
| `--account` | Render one account's secrets (AETHER_&lt;ACCOUNT&gt;_*) into lean.live.&lt;account&gt;.json |
| `--dry-run` | Print the field names that would be filled (never values), write nothing |
| `--check` | Exit 1 when the rendered file is missing or differs from what the secrets give |

### `aq users`

Dashboard and API users: viewer, operator (may lock an account), admin (may unlock)

```text
aq users [-h] {add,list,rotate,remove} ...
```

#### `aq users add`

Add a user and print their token once

```text
aq users add [-h] [--role ROLE] [--accounts ACCOUNTS] name
```

| Flag | Meaning |
|---|---|
| `name` |  |
| `--role` | viewer, operator or admin |
| `--accounts` | Comma-separated account ids this user may act on (default: all) |

#### `aq users list`

Every user, role and account scope (no tokens)

```text
aq users list [-h] [--json]
```

| Flag | Meaning |
|---|---|
| `--json` | Print JSON instead of text |

#### `aq users rotate`

Issue a user a new token (printed once); the old one stops working

```text
aq users rotate [-h] [--yes] name
```

| Flag | Meaning |
|---|---|
| `name` |  |
| `--yes` | Confirm without a prompt (needed without a terminal) |

#### `aq users remove`

Remove a user (revokes their token)

```text
aq users remove [-h] [--yes] name
```

| Flag | Meaning |
|---|---|
| `name` |  |
| `--yes` | Confirm without a prompt (needed without a terminal) |

### `aq live-readiness`

The paper-to-live scorecard: every condition for live capital, measured (exit 1 unless ready)

```text
aq live-readiness [-h] [--account ACCOUNT] [--paper-check FILE] [--markdown] [--json FILE] [--no-write] [--docs]
```

| Flag | Meaning |
|---|---|
| `--account` | Score one account (accounts.json); default: the default account |
| `--paper-check` | `aq evaluate --paper-check`'s JSON report, for the paper metrics |
| `--markdown` | Print the scorecard as a Markdown table |
| `--json` | Also write the scorecard here |
| `--no-write` | Do not write visualization/grafana/live_readiness.json |
| `--docs` | Also write the scorecard into docs/live/paper-to-live.md's generated block |

### `aq accounts`

The account registry (accounts.json): list, validate, status of each deployment

```text
aq accounts [-h] {list,validate,status} ...
```

#### `aq accounts list`

Every account and its broker, environment and mode

```text
aq accounts list [-h] [--json]
```

| Flag | Meaning |
|---|---|
| `--json` | Print JSON instead of text |

#### `aq accounts validate`

Parse accounts.json against config.json: ids, brokers, overrides that only tighten

```text
aq accounts validate [-h] [--json]
```

| Flag | Meaning |
|---|---|
| `--json` | Print JSON instead of text |

#### `aq accounts status`

Each account's secrets (resolved or not) and last state

```text
aq accounts status [-h] [--json FILE]
```

| Flag | Meaning |
|---|---|
| `--json` | Also write the rows |

### `aq live`

Start or stop one account's Lean live deployment (docker compose lean-live)

```text
aq live [-h] {up,down,status} ...
```

#### `aq live up`

Start the account's live/paper deployment

```text
aq live up [-h] [--account ACCOUNT] [--dry-run] [--yes]
```

| Flag | Meaning |
|---|---|
| `--account` | The account id (default: the default account) |
| `--dry-run` | Print the commands instead of running them |
| `--yes` | Confirm a live (real-money) start without a prompt |

#### `aq live down`

Stop and remove it

```text
aq live down [-h] [--account ACCOUNT] [--dry-run]
```

| Flag | Meaning |
|---|---|
| `--account` | The account id (default: the default account) |
| `--dry-run` | Print the commands instead of running them |

#### `aq live status`

Whether the account's container runs

```text
aq live status [-h] [--account ACCOUNT] [--json]
```

| Flag | Meaning |
|---|---|
| `--account` | The account id (default: the default account) |
| `--json` | Print JSON instead of text |

### `aq secrets`

Where each credential comes from (file, Docker secret, env, keyring), and keyring storage; never prints a value

```text
aq secrets [-h] [--account ACCOUNT] {status,set,delete} ...
```

| Flag | Meaning |
|---|---|
| `--account` | One account's secrets (AETHER_&lt;ACCOUNT&gt;_*); default: the default account |

#### `aq secrets status`

Each known secret: resolved or not, and from where

```text
aq secrets status [-h] [--json FILE]
```

| Flag | Meaning |
|---|---|
| `--json` | Also write the status (names and sources only) |

#### `aq secrets set`

Store a secret in the OS keyring (prompted, never echoed)

```text
aq secrets set [-h] name
```

| Flag | Meaning |
|---|---|
| `name` | e.g. IB_PASSWORD, COINBASE_API_SECRET |

#### `aq secrets delete`

Remove a secret from the OS keyring

```text
aq secrets delete [-h] [--yes] name
```

| Flag | Meaning |
|---|---|
| `name` |  |
| `--yes` | Confirm without a prompt (needed without a terminal) |

### `aq secrets-check`

Fail if a populated secret field in lean.json or a tracked .env is about to be committed (backs the pre-commit hook)

```text
aq secrets-check [-h] [--json]
```

| Flag | Meaning |
|---|---|
| `--json` | Print the findings as JSON (field names only, never values) |

### `aq audit-log`

Query the tamper-evident audit log (order placement, credential loads, live-mode transitions)

```text
aq audit-log [-h] [--event-type {order_placement,credential_load,live_mode_transition}] [--since SINCE] [--limit LIMIT] [--verify] [--until UNTIL] [--export FILE] [--json]
```

| Flag | Meaning |
|---|---|
| `--event-type` | Filter to one event type (default: all) |
| `--since` | Only entries after this date, ISO 8601 YYYY-MM-DD |
| `--limit` | Max entries to show (default: 100) |
| `--verify` | Walk the whole hash chain and report the first break, if any |
| `--until` | Only entries on or before this date, ISO 8601 YYYY-MM-DD |
| `--export` | Write the matching entries as JSON lines |
| `--json` | Print the entries as JSON |

### `aq docs`

Keep the numbers quoted in the docs true

```text
aq docs [-h] {sync,build,serve,cli,links} ...
```

#### `aq docs sync`

Rewrite every &lt;!--fact:key--&gt; value and generated AQ block from its source

```text
aq docs sync [-h] [--check] [--json]
```

| Flag | Meaning |
|---|---|
| `--check` | Change nothing; exit 1 if a value is stale |
| `--json` | Print the stale and unknown keys as JSON |

#### `aq docs build`

Build the documentation site (scripts/build_docs.py, then mkdocs build)

```text
aq docs build [-h] [--strict]
```

| Flag | Meaning |
|---|---|
| `--strict` | Fail on any warning, as CI's docs job does |

#### `aq docs serve`

Serve the site locally with live reload

```text
aq docs serve [-h] [--port PORT]
```

| Flag | Meaning |
|---|---|
| `--port` | Port (default 8000) |

#### `aq docs cli`

Regenerate docs/reference/cli.md from the parser

```text
aq docs cli [-h] [--check]
```

| Flag | Meaning |
|---|---|
| `--check` | Change nothing; exit 1 if the page is stale |

#### `aq docs links`

Every relative link and anchor in the docs resolves (exit 1 on a broken one)

```text
aq docs links [-h] [--external] [--json]
```

| Flag | Meaning |
|---|---|
| `--external` | Also check http(s) links (network) |
| `--json` | Print the broken links as JSON |

### `aq verify`

Every way to verify the project: the table, and the checks a small machine can run

```text
aq verify [-h] [--list] [--quick] [--record FILE] [--write-doc] [--json]
```

| Flag | Meaning |
|---|---|
| `--list` | Print the table of verification surfaces (default) |
| `--quick` | Run the checks that fit a 4 GB machine: ruff, doc facts, the library gate, the sorry scan, secrets, the guard tests |
| `--record` | Run --quick and write the results as JSON |
| `--write-doc` | Regenerate the table in development/verification.md |
| `--json` | With --quick: print the results as JSON |

### `aq hooks`

The pre-commit gate: install it, show it, turn its coverage step off or on

```text
aq hooks [-h] {install,status,coverage} ...
```

#### `aq hooks install`

Install the wrapper in .git/hooks/pre-commit

```text
aq hooks install [-h] [--dry-run]
```

| Flag | Meaning |
|---|---|
| `--dry-run` | Print what would happen, change nothing |

#### `aq hooks status`

Whether the hook is installed, its gates, and the coverage switch

```text
aq hooks status [-h] [--json]
```

| Flag | Meaning |
|---|---|
| `--json` | Print JSON instead of text |

#### `aq hooks coverage`

Turn the hook's coverage step off (--once: the next commit only), back on, or show it

```text
aq hooks coverage [-h] [--once] [--dry-run] [--json] {off,on,status}
```

| Flag | Meaning |
|---|---|
| `coverage_action` |  |
| `--once` | With off: skip only the next commit's coverage step |
| `--dry-run` | Print what would happen, change nothing |
| `--json` | Print JSON instead of text |

### `aq commit`

git commit through the pre-commit gate, optionally skipping its coverage step for this one commit

```text
aq commit [-h] -m MESSAGE [-a] [--skip-coverage] [--dry-run] [git_args ...]
```

| Flag | Meaning |
|---|---|
| `-m`, `--message` | The commit message |
| `-a`, `--all` | Stage every tracked change first (git commit -a) |
| `--skip-coverage` | Skip the coverage step for this commit only (sets AQ_SKIP_COVERAGE_HOOK=1); the other gates still run |
| `--dry-run` | Print what would happen, change nothing |
| `git_args` | More git commit arguments, after -- |

### `aq check`

Run the pre-commit gate now, committing nothing

```text
aq check [-h] [--no-coverage]
```

| Flag | Meaning |
|---|---|
| `--no-coverage` | Skip the coverage step |

### `aq doctor`

Check the environment: Python, the install, tools, services, RAM, disk, model pins

```text
aq doctor [-h] [--json]
```

| Flag | Meaning |
|---|---|
| `--json` | Print JSON instead of text |

### `aq version`

The installed version, Python, platform and (in a checkout) the git commit

```text
aq version [-h] [--json]
```

| Flag | Meaning |
|---|---|
| `--json` | Print JSON instead of text |

### `aq completion`

Print a shell completion script

```text
aq completion [-h] {bash,zsh,powershell}
```

| Flag | Meaning |
|---|---|
| `shell` |  |

### `aq help`

Help for a command (the same as aq COMMAND --help)

```text
aq help [-h] [topic ...]
```

| Flag | Meaning |
|---|---|
| `topic` | The command path |

### `aq status`

The project at a glance: branch, changes, hook and coverage, CI of HEAD, Dependabot, Codespaces

```text
aq status [-h] [--json] [--offline] [--git]
```

| Flag | Meaning |
|---|---|
| `--json` | Print JSON instead of text |
| `--offline` | Skip the GitHub queries (CI, PRs, Codespaces) |
| `--git` | Print plain git status instead |

### `aq ci`

GitHub Actions: the runs of a commit, the failing lines of a run, or a ci.yml job run here

```text
aq ci [-h] {status,logs,local} ...
```

#### `aq ci status`

Every workflow run of a commit: green, red (exit 1) or running (exit 3)

```text
aq ci status [-h] [--sha SHA] [--branch BRANCH] [--watch] [--interval INTERVAL] [--json]
```

| Flag | Meaning |
|---|---|
| `--sha` | The commit (default HEAD) |
| `--branch` | The tip of this remote branch instead |
| `--watch` | Poll until nothing is running |
| `--interval` | Seconds between polls with --watch (default 30) |
| `--json` | Print JSON instead of text |

#### `aq ci logs`

The lines that explain each failed job of a run

```text
aq ci logs [-h] [--job JOB] [--lines LINES] [--json] run_id
```

| Flag | Meaning |
|---|---|
| `run_id` |  |
| `--job` | Only jobs whose name contains this (default: every failed job) |
| `--lines` | At most this many lines per job (default 80) |
| `--json` | Print JSON instead of text |

#### `aq ci local`

Run a workflow job's run: steps here, in order (uses: steps are skipped)

```text
aq ci local [-h] [--workflow WORKFLOW] [--list] [--matrix KEY=VALUE] [--dry-run] [job]
```

| Flag | Meaning |
|---|---|
| `job` | The job (omit or --list to list them) |
| `--workflow` | The workflow file under .github/workflows (default ci.yml) |
| `--list` | List the jobs and what each needs |
| `--matrix` | A matrix value (default: each key's first) |
| `--dry-run` | Print what would happen, change nothing |

### `aq deps`

Dependencies: Dependabot PRs, applying one correctly, the hash locks, pins, audit, why a package is locked

```text
aq deps [-h] {prs,apply,lock,pins,audit,why} ...
```

#### `aq deps prs`

Open Dependabot PRs: ecosystem, package, versions, checks

```text
aq deps prs [-h] [--json]
```

| Flag | Meaning |
|---|---|
| `--json` | Print JSON instead of text |

#### `aq deps apply`

Apply Dependabot PRs to the working tree (pip: re-lock with uv; npm: npm install); never commits

```text
aq deps apply [-h] [--dry-run] numbers [numbers ...]
```

| Flag | Meaning |
|---|---|
| `numbers` | PR numbers |
| `--dry-run` | Print what would happen, change nothing |

#### `aq deps lock`

Rebuild requirements/lock/*.txt from their .in files (uv)

```text
aq deps lock [-h] [--profile PROFILE] [--upgrade-package NAME]
```

| Flag | Meaning |
|---|---|
| `--profile` | One profile (repeatable; default all) |
| `--upgrade-package` | Let this pin move to its newest allowed version (repeatable) |

#### `aq deps pins`

Every install pinned by hash (the Scorecard check); prints 0 when clean

```text
aq deps pins [-h]
```

#### `aq deps audit`

pip-audit over the runtime and ci locks (as CI's dependency-audit job)

```text
aq deps audit [-h]
```

#### `aq deps why`

Which packages pull PACKAGE into each lock

```text
aq deps why [-h] [--profile PROFILE] [--json] package
```

| Flag | Meaning |
|---|---|
| `package` |  |
| `--profile` | Only this lock profile (repeatable) |
| `--json` | Print JSON instead of text |

### `aq coverage`

The last coverage run: totals, files below 100%, misses by function, cleaning

```text
aq coverage [-h] {report,misses,clean} ...
```

#### `aq coverage report`

Total, files below 100%, age, and files changed since (exit 3 below 100%)

```text
aq coverage report [-h] [--json]
```

| Flag | Meaning |
|---|---|
| `--json` | Print JSON instead of text |

#### `aq coverage misses`

Uncovered lines, by file or function (scripts/coverage_misses.py)

```text
aq coverage misses [-h] [--include INCLUDE] [--by-function] [--context N]
```

| Flag | Meaning |
|---|---|
| `--include` | Glob of files (repeatable) |
| `--by-function` | Group misses by function |
| `--context` | Print each miss with N lines around it |

#### `aq coverage clean`

Delete coverage-report/ and .coverage* (dry run unless --apply)

```text
aq coverage clean [-h] [--apply] [--yes] [--json]
```

| Flag | Meaning |
|---|---|
| `--apply` | Delete (default: list only) |
| `--yes` | Confirm without a prompt (needed without a terminal) |
| `--json` | Print JSON instead of text |

### `aq codespace`

GitHub Codespaces: list (running ones bill), stop, delete

```text
aq codespace [-h] {list,stop,delete} ...
```

#### `aq codespace list`

Every Codespace and its state

```text
aq codespace list [-h] [--json]
```

| Flag | Meaning |
|---|---|
| `--json` | Print JSON instead of text |

#### `aq codespace stop`

Stop one Codespace, or every running one

```text
aq codespace stop [-h] [--all] [--dry-run] [name]
```

| Flag | Meaning |
|---|---|
| `name` |  |
| `--all` | Every running Codespace |
| `--dry-run` | Print what would happen, change nothing |

#### `aq codespace delete`

Delete a Codespace and its storage (asks first)

```text
aq codespace delete [-h] [--dry-run] [--yes] name
```

| Flag | Meaning |
|---|---|
| `name` |  |
| `--dry-run` | Print what would happen, change nothing |
| `--yes` | Confirm without a prompt (needed without a terminal) |

### `aq vault`

Aether-Vault records and the Obsidian code graph

```text
aq vault [-h] {record,graph} ...
```

#### `aq vault record`

Record files in the vault with a label and metrics (scripts/vault_record.py)

```text
aq vault record [-h] --label LABEL [--metric METRIC] [--dry-run] paths [paths ...]
```

| Flag | Meaning |
|---|---|
| `--label` | The record's tag |
| `--metric` | key=value (repeatable) |
| `paths` |  |
| `--dry-run` | Print what would happen, change nothing |

#### `aq vault graph`

Regenerate the Obsidian code graph and append a handoff entry

```text
aq vault graph [-h] --summary SUMMARY --files FILES [FILES ...] [--agent AGENT] [--dry-run]
```

| Flag | Meaning |
|---|---|
| `--summary` | The handoff summary |
| `--files` | Files the phase changed |
| `--agent` | The handoff's agent name (default ox-alpha) |
| `--dry-run` | Print what would happen, change nothing |

### `aq problems`

development/Problems.md: the next number and template, one entry, the partial ones

```text
aq problems [-h] {next,show,open} ...
```

#### `aq problems next`

The next free number and an entry template

```text
aq problems next [-h] [--json]
```

| Flag | Meaning |
|---|---|
| `--json` | Print JSON instead of text |

#### `aq problems show`

One entry

```text
aq problems show [-h] [--json] number
```

| Flag | Meaning |
|---|---|
| `number` |  |
| `--json` | Print JSON instead of text |

#### `aq problems open`

Entries still partial (🟡)

```text
aq problems open [-h] [--json]
```

| Flag | Meaning |
|---|---|
| `--json` | Print JSON instead of text |

### `aq lint`

ruff over the project, optionally fixing, optionally the library's type completeness

```text
aq lint [-h] [--fix] [--types]
```

| Flag | Meaning |
|---|---|
| `--fix` | Apply ruff's safe fixes |
| `--types` | Also check the library's type completeness (scripts/type_completeness.py) |

### `aq scaffold`

Create a module with its registered test file and the reminders for the export and the readme

```text
aq scaffold [-h] [--group GROUP] [--dry-run] path
```

| Flag | Meaning |
|---|---|
| `path` | The new module's path, e.g. risk/my_rule.py |
| `--group` | The test group (default: from the folder) |
| `--dry-run` | Print what would happen, change nothing |

### `aq phase`

The end-of-phase checklist from AGENTS.md, checked where it can be

```text
aq phase [-h] {check} ...
```

#### `aq phase check`

Changelog, docs, gates, coverage, tree, CI, Codespaces, vault (exit 3 on a failure)

```text
aq phase check [-h] --version VERSION [--json]
```

| Flag | Meaning |
|---|---|
| `--version` | The phase as its Changelog heading names it |
| `--json` | Print JSON instead of text |

### `aq bug-report`

A Markdown report for a GitHub issue: versions and the doctor's checks (no config, no env, no user names)

```text
aq bug-report [-h] [--out OUT]
```

| Flag | Meaning |
|---|---|
| `--out` | Write it here instead of printing |

### `aq examples`

The runnable examples in examples/

```text
aq examples [-h] {list,run} ...
```

#### `aq examples list`

Every example and what it shows

```text
aq examples list [-h] [--json]
```

| Flag | Meaning |
|---|---|
| `--json` | Print JSON instead of text |

#### `aq examples run`

Run one example

```text
aq examples run [-h] name
```

| Flag | Meaning |
|---|---|
| `name` |  |

### `aq notebooks`

The tutorial notebooks: list them, run one

```text
aq notebooks [-h] {list,run} ...
```

#### `aq notebooks list`

Every tutorial and its title

```text
aq notebooks list [-h] [--json]
```

| Flag | Meaning |
|---|---|
| `--json` | Print JSON instead of text |

#### `aq notebooks run`

Execute one tutorial

```text
aq notebooks run [-h] [--out OUT] name
```

| Flag | Meaning |
|---|---|
| `name` | The file name without .ipynb, or without its number prefix |
| `--out` | Write the executed notebook here |

### `aq bench`

Hot-path latency of the numpy forward pass, against a baseline saved for this machine

```text
aq bench [-h] {run,baseline,compare} ...
```

#### `aq bench run`

Time it and print p50/p95/p99

```text
aq bench run [-h] [--iterations ITERATIONS] [--json]
```

| Flag | Meaning |
|---|---|
| `--iterations` | Symbol-bars to time (default 2000) |
| `--json` | Print JSON instead of text |

#### `aq bench baseline`

Time it and save the result as this machine's baseline

```text
aq bench baseline [-h] [--iterations ITERATIONS] [--json]
```

| Flag | Meaning |
|---|---|
| `--iterations` | Symbol-bars to time (default 2000) |
| `--json` | Print JSON instead of text |

#### `aq bench compare`

Time it against the baseline (exit 3 when p95 regressed)

```text
aq bench compare [-h] [--iterations ITERATIONS] [--json] [--threshold THRESHOLD]
```

| Flag | Meaning |
|---|---|
| `--iterations` | Symbol-bars to time (default 2000) |
| `--json` | Print JSON instead of text |
| `--threshold` | Allowed p95 slowdown as a fraction (default 0.2) |

### `aq data`

Price data: fetch (keyless), the bundled sample, a first look, an HTML page, file manifests and their diff

```text
aq data [-h] {fetch,sample,info,explore,manifest,diff} ...
```

#### `aq data fetch`

Daily closes of Coinbase coins (public candles, no key), cached

```text
aq data fetch [-h] --coins COINS [--start START] [--end END] --out OUT
```

| Flag | Meaning |
|---|---|
| `--coins` | Comma list, e.g. BTC,ETH |
| `--start` | First date (default 2021-01-01) |
| `--end` | Last date (default: the last closed bar) |
| `--out` | closes.csv or closes.parquet |

#### `aq data sample`

Write the bundled sample's closes to DIR/closes.csv

```text
aq data sample [-h] --out OUT
```

| Flag | Meaning |
|---|---|
| `--out` | A folder |

#### `aq data info`

Shape, dates, calendar, and per ticker its span, missing share and longest gap

```text
aq data info [-h] [--json] file
```

| Flag | Meaning |
|---|---|
| `file` |  |
| `--json` | Print JSON instead of text |

#### `aq data explore`

A one-file HTML page: growth, return moments, correlations, rolling volatility, gaps

```text
aq data explore [-h] [--out OUT] file
```

| Flag | Meaning |
|---|---|
| `file` |  |
| `--out` | The page (default: FILE with .html) |

#### `aq data manifest`

Size and sha256 of every file under a data root

```text
aq data manifest [-h] [--root ROOT] [--out OUT]
```

| Flag | Meaning |
|---|---|
| `--root` | The folder (default data) |
| `--out` | Write here instead of printing |

#### `aq data diff`

Compare two manifests, or one with a folder (exit 3 on any difference)

```text
aq data diff [-h] [--root ROOT] [--json] manifest_a [manifest_b]
```

| Flag | Meaning |
|---|---|
| `manifest_a` |  |
| `manifest_b` |  |
| `--root` | Without MANIFEST_B: the folder to compare (default data) |
| `--json` | Print JSON instead of text |

### `aq signal`

Any signal CSV (date, ticker, score): check it, evaluate it on prices, compare signals, neutralize, backtest

```text
aq signal [-h] {check,eval,compare,neutralize,backtest} ...
```

#### `aq signal check`

Columns, dates, duplicates, finite scores, names per date (exit 1 on an error)

```text
aq signal check [-h] [--min-names MIN_NAMES] [--json] file
```

| Flag | Meaning |
|---|---|
| `file` |  |
| `--min-names` | Warn on dates with fewer scored names (default 2) |
| `--json` | Print JSON instead of text |

#### `aq signal eval`

IC by horizon (HAC t, bootstrap CI), decay, half-life, quintile returns

```text
aq signal eval [-h] [--prices PRICES] [--horizons HORIZONS] [--min-names MIN_NAMES] [--html FILE] [--json] file
```

| Flag | Meaning |
|---|---|
| `file` |  |
| `--prices` | Closes CSV (default: the bundled sample) |
| `--horizons` | Comma list of horizons (default 5,20) |
| `--min-names` | Names a date needs to count (default 3) |
| `--html` | Also write an HTML page |
| `--json` | Print JSON instead of text |

#### `aq signal compare`

Each signal's IC, what is left after the others, their correlation, an equal-weight blend

```text
aq signal compare [-h] [--prices PRICES] [--horizons HORIZONS] [--min-names MIN_NAMES] [--json] files [files ...]
```

| Flag | Meaning |
|---|---|
| `files` |  |
| `--prices` | Closes CSV (default: the bundled sample) |
| `--horizons` | Comma list of horizons (default 5,20) |
| `--min-names` | Names a date needs to count (default 3) |
| `--json` | Print JSON instead of text |

#### `aq signal neutralize`

Remove each date's cross-sectional beta from the scores

```text
aq signal neutralize [-h] [--prices PRICES] [--horizons HORIZONS] [--min-names MIN_NAMES] [--market MARKET] [--window WINDOW] [--out OUT] file
```

| Flag | Meaning |
|---|---|
| `file` |  |
| `--prices` | Closes CSV (default: the bundled sample) |
| `--horizons` | Comma list of horizons (default 5,20) |
| `--min-names` | Names a date needs to count (default 3) |
| `--market` | A ticker as the market (default: the equal-weight mean) |
| `--window` | Beta window in rows (default 120) |
| `--out` | Output CSV (default: FILE_neutral.csv) |

#### `aq signal backtest`

A cost-aware long-only book on the scores, with PSR, DSR at N and the minimum track record

```text
aq signal backtest [-h] [--prices PRICES] [--horizons HORIZONS] [--min-names MIN_NAMES] [--top-n TOP_N] [--cost COST] [--rebalance REBALANCE] [--ledger LEDGER] [--json] file
```

| Flag | Meaning |
|---|---|
| `file` |  |
| `--prices` | Closes CSV (default: the bundled sample) |
| `--horizons` | Comma list of horizons (default 5,20) |
| `--min-names` | Names a date needs to count (default 3) |
| `--top-n` | Hold the top N names equally (default: rank weights over all) |
| `--cost` | coinbase, ib_equity or bps:N (default coinbase) |
| `--rebalance` | Rebalance every N rows (default 5) |
| `--ledger` | Count this backtest as a trial in this ledger (JSONL) |
| `--json` | Print JSON instead of text |

### `aq features`

The features the lab builds from closes: list, build a table, inspect one

```text
aq features [-h] {list,build,inspect} ...
```

#### `aq features list`

Every buildable feature and the named sets

```text
aq features list [-h] [--all] [--json]
```

| Flag | Meaning |
|---|---|
| `--all` | Also name the production-only groups |
| `--json` | Print JSON instead of text |

#### `aq features build`

Long table date, ticker, features (each uses closes up to its date only)

```text
aq features build [-h] [--prices PRICES] [--set SET] [--out OUT] [--dry-run]
```

| Flag | Meaning |
|---|---|
| `--prices` | Closes CSV (default: the bundled sample) |
| `--set` | A set (example, momentum, core, all) or a comma list (default core) |
| `--out` | Output CSV (default features.csv) |
| `--dry-run` | Print what would happen, change nothing |

#### `aq features inspect`

One feature: IC by horizon, decay, half-life, IC by year, overlap with the core set

```text
aq features inspect [-h] [--prices PRICES] [--horizons HORIZONS] [--html FILE] [--json] name
```

| Flag | Meaning |
|---|---|
| `name` |  |
| `--prices` | Closes CSV (default: the bundled sample) |
| `--horizons` | Comma list (default 5,20) |
| `--html` | Also write an HTML page |
| `--json` | Print JSON instead of text |

### `aq overfit`

Overfitting statistics as calculators: PBO, PSR, DSR, the hurdle a winner must beat, haircut Sharpe, minimum track record

```text
aq overfit [-h] {pbo,psr,dsr,hurdle,haircut,mintrl} ...
```

#### `aq overfit pbo`

Probability of backtest overfitting over a returns table, one column per trial

```text
aq overfit pbo [-h] [--blocks BLOCKS] [--json] trials
```

| Flag | Meaning |
|---|---|
| `trials` | CSV of daily returns, one column per trial |
| `--blocks` | CSCV blocks (default 16) |
| `--json` | Print JSON instead of text |

#### `aq overfit psr`

Probabilistic Sharpe ratio of a returns series

```text
aq overfit psr [-h] --returns RETURNS [--benchmark-sharpe BENCHMARK_SHARPE] [--json]
```

| Flag | Meaning |
|---|---|
| `--returns` | CSV with a return column |
| `--benchmark-sharpe` | Per-period benchmark Sharpe (default 0) |
| `--json` | Print JSON instead of text |

#### `aq overfit dsr`

Deflated Sharpe ratio of a returns series at N trials

```text
aq overfit dsr [-h] --returns RETURNS [--trials TRIALS] [--trial-variance TRIAL_VARIANCE] [--from-ledger] [--periods PERIODS] [--json]
```

| Flag | Meaning |
|---|---|
| `--returns` | CSV with a return column |
| `--trials` | N |
| `--trial-variance` | Variance of the trials' annual Sharpes |
| `--from-ledger` | Take N and the variance from the project's trial ledgers |
| `--periods` | Periods a year (default 252; 365 for crypto) |
| `--json` | Print JSON instead of text |

#### `aq overfit hurdle`

The Sharpe the best of N unskilled trials is expected to show

```text
aq overfit hurdle [-h] --trials TRIALS --trial-variance TRIAL_VARIANCE [--json]
```

| Flag | Meaning |
|---|---|
| `--trials` |  |
| `--trial-variance` |  |
| `--json` | Print JSON instead of text |

#### `aq overfit haircut`

Haircut Sharpe for multiple testing

```text
aq overfit haircut [-h] --sharpe SHARPE --obs OBS --trials TRIALS [--method {bonferroni,holm,bhy}] [--json]
```

| Flag | Meaning |
|---|---|
| `--sharpe` | Annual Sharpe |
| `--obs` | Observations |
| `--trials` |  |
| `--method` | Adjustment (default bhy) |
| `--json` | Print JSON instead of text |

#### `aq overfit mintrl`

Minimum track record before the Sharpe beats a target at a confidence

```text
aq overfit mintrl [-h] --returns RETURNS [--target-sharpe TARGET_SHARPE] [--confidence CONFIDENCE] [--periods PERIODS] [--json]
```

| Flag | Meaning |
|---|---|
| `--returns` |  |
| `--target-sharpe` | Annual target (default 0) |
| `--confidence` | Default 0.95 |
| `--periods` | Periods a year (default 252) |
| `--json` | Print JSON instead of text |

### `aq lab`

The model lab: create, train, evaluate, compare, sweep, explain and export models (networks or linear) on any dataset

```text
aq lab [-h] {init,new,train,runs,show,eval,compare,card,sweep,explain,ablate,seeds,export} ...
```

#### `aq lab init`

Create a lab folder: lab.toml, models/, runs/, data/

```text
aq lab init [-h] directory
```

| Flag | Meaning |
|---|---|
| `directory` |  |

#### `aq lab new`

A model folder from a template: model.py, config.toml, a shape test

```text
aq lab new [-h] [--lab LAB] --template {mlp,multitask,tcn,linear} [--force] name
```

| Flag | Meaning |
|---|---|
| `--lab` | The lab folder (default: the nearest lab.toml above here) |
| `name` |  |
| `--template` | mlp, multitask, tcn (production networks) or linear (numpy) |
| `--force` | Overwrite an existing model folder |

#### `aq lab train`

Train a model per seed; record the run, its out-of-sample scores, weights, pins and one ledger trial per seed

```text
aq lab train [-h] [--lab LAB] [--seeds SEEDS] [--folds {split,annual}] [--set KEY=VALUE] [--resume [RUN_ID]] [--engine {lab,production}] [--production-kind {multitask,tcn}] [--objective OBJECTIVE] [--memory-profile {standard,low}] [--project-ledger] [--dry-run] [--json] model
```

| Flag | Meaning |
|---|---|
| `--lab` | The lab folder (default: the nearest lab.toml above here) |
| `model` |  |
| `--seeds` | Comma list (default: the config's) |
| `--folds` | split: train/validation/backtest; annual: an expanding walk-forward by year |
| `--set` | Override the config for this run, e.g. train.lr=3e-4 (repeatable) |
| `--resume` | Continue a stopped run |
| `--engine` | production: the real trainers on the project dataset (source checkout) |
| `--production-kind` | With --engine production: which trainer |
| `--objective` | With --engine production: the ranking objective |
| `--memory-profile` | With --engine production: the trainer's profile |
| `--project-ledger` | Also count the trials in the project's ledger and seal the project's holdout window |
| `--dry-run` | Print what would happen, change nothing |
| `--json` | Print JSON instead of text |

#### `aq lab runs`

Every run, newest first: status, model, IC with its seed spread, N

```text
aq lab runs [-h] [--lab LAB] [--json]
```

| Flag | Meaning |
|---|---|
| `--lab` | The lab folder (default: the nearest lab.toml above here) |
| `--json` | Print JSON instead of text |

#### `aq lab show`

One run's record

```text
aq lab show [-h] [--lab LAB] [--json] run
```

| Flag | Meaning |
|---|---|
| `--lab` | The lab folder (default: the nearest lab.toml above here) |
| `run` | A run id, a unique prefix, or latest |
| `--json` | Print JSON instead of text |

#### `aq lab eval`

IC by split and year, decay, half-life, quintiles, the overfit gap, and with --book a cost-aware book judged at N

```text
aq lab eval [-h] [--lab LAB] [--book] [--cost-bps COST_BPS] [--html FILE] [--holdout] [--i-understand-this-spends-it] [--project-ledger] [--json] run
```

| Flag | Meaning |
|---|---|
| `--lab` | The lab folder (default: the nearest lab.toml above here) |
| `run` |  |
| `--book` | Also a quintile long-short book after costs, with PSR and DSR at N |
| `--cost-bps` | Per-side cost for --book (default 10) |
| `--html` | Also write an HTML page |
| `--holdout` | Spend the sealed holdout on this run (once, recorded first) |
| `--i-understand-this-spends-it` | Required with --holdout |
| `--project-ledger` | With --holdout: the project's holdout ledger |
| `--json` | Print JSON instead of text |

#### `aq lab compare`

A leaderboard on the rows every run scored, each run tested against the best (HAC t, bootstrap CI)

```text
aq lab compare [-h] [--lab LAB] [--baseline BASELINE] [--html FILE] [--json] runs [runs ...]
```

| Flag | Meaning |
|---|---|
| `--lab` | The lab folder (default: the nearest lab.toml above here) |
| `runs` |  |
| `--baseline` | Add a baseline: momentum_20, momentum_60, reversal_5 or a feature column |
| `--html` | Also write an HTML page |
| `--json` | Print JSON instead of text |

#### `aq lab card`

A Markdown model card from the run's own numbers

```text
aq lab card [-h] [--lab LAB] [--out OUT] run
```

| Flag | Meaning |
|---|---|
| `--lab` | The lab folder (default: the nearest lab.toml above here) |
| `run` |  |
| `--out` | Default: the run's MODEL_CARD.md |

#### `aq lab sweep`

Train every grid point (each a counted trial, failures too), resumable, then the sweep's PBO

```text
aq lab sweep [-h] [--lab LAB] --grid GRID [--random K] [--seed SEED] [--max-trials MAX_TRIALS] [--project-ledger] [--json] model
```

| Flag | Meaning |
|---|---|
| `--lab` | The lab folder (default: the nearest lab.toml above here) |
| `model` |  |
| `--grid` | Space-separated key=v1,v2 items |
| `--random` | Only K points drawn at random |
| `--seed` | The draw's seed (default 7) |
| `--max-trials` | Refuse a sweep that would push N past this |
| `--project-ledger` | Also count the trials in the project's ledger |
| `--json` | Print JSON instead of text |

#### `aq lab explain`

Out-of-sample permutation importance per feature and group, and each feature's own IC

```text
aq lab explain [-h] [--lab LAB] [--json] run
```

| Flag | Meaning |
|---|---|
| `--lab` | The lab folder (default: the nearest lab.toml above here) |
| `run` |  |
| `--json` | Print JSON instead of text |

#### `aq lab ablate`

Retrain without each feature group; the IC each group carries

```text
aq lab ablate [-h] [--lab LAB] [--project-ledger] [--json] run
```

| Flag | Meaning |
|---|---|
| `--lab` | The lab folder (default: the nearest lab.toml above here) |
| `run` |  |
| `--project-ledger` | Also count the trials in the project's ledger |
| `--json` | Print JSON instead of text |

#### `aq lab seeds`

Retrain with N seeds; IC mean, spread and range (flags an unstable model)

```text
aq lab seeds [-h] [--lab LAB] [--seeds SEEDS] [--project-ledger] [--json] run
```

| Flag | Meaning |
|---|---|
| `--lab` | The lab folder (default: the nearest lab.toml above here) |
| `run` |  |
| `--seeds` | How many seeds (default 5) |
| `--project-ledger` | Also count the trials in the project's ledger |
| `--json` | Print JSON instead of text |

#### `aq lab export`

Package a run as an aq models zip (numpy forward pass, no torch to score it)

```text
aq lab export [-h] [--lab LAB] --name NAME [--out OUT] [--json] run
```

| Flag | Meaning |
|---|---|
| `--lab` | The lab folder (default: the nearest lab.toml above here) |
| `run` |  |
| `--name` | The model's name for aq models |
| `--out` | The zip (default: LAB/NAME.zip) |
| `--json` | Print JSON instead of text |

### `aq dataset`

Lab datasets: build one from closes (features, rank targets, purged splits), describe one, audit it for leakage

```text
aq dataset [-h] {build,info,leakage} ...
```

#### `aq dataset build`

Features, forward rank targets and split labels in the production dataset's columns

```text
aq dataset build [-h] [--prices PRICES] [--features FEATURES] [--targets TARGETS] [--splits SPLITS] [--out OUT] [--dry-run] [--json]
```

| Flag | Meaning |
|---|---|
| `--prices` | Closes CSV (default: the bundled sample) |
| `--features` | A set or comma list (default core; aq features list) |
| `--targets` | Comma list of horizons (default 5,20) |
| `--splits` | NAME:START..END,... (default 60/20/20 by date); a holdout split is sealed |
| `--out` | Output CSV (default dataset.csv) |
| `--dry-run` | Print what would happen, change nothing |
| `--json` | Print JSON instead of text |

#### `aq dataset info`

Rows, dates, tickers, splits, features with their missing share, targets, sealed rows

```text
aq dataset info [-h] [--json] file
```

| Flag | Meaning |
|---|---|
| `file` |  |
| `--json` | Print JSON instead of text |

#### `aq dataset leakage`

Tail NaN, label shuffle, single-feature IC, asset prior (exit 3 when something is flagged)

```text
aq dataset leakage [-h] [--target TARGET] [--json] file
```

| Flag | Meaning |
|---|---|
| `file` |  |
| `--target` | Default target_rank_20d |
| `--json` | Print JSON instead of text |

### `aq stack`

The installed model stack (owner research): what is installed, how its IC decays by class/year, what it uses, a lab baseline

```text
aq stack [-h] {inspect,decay,attrib,lab-baseline} ...
```

#### `aq stack inspect`

Models, heads with their validation/backtest IC, inputs, pins

```text
aq stack inspect [-h] [--ml-dir ML_DIR] [--json]
```

| Flag | Meaning |
|---|---|
| `--ml-dir` | Another model folder, e.g. ml/versions/&lt;id&gt; |
| `--json` | Print JSON instead of text |

#### `aq stack decay`

Rolling and grouped IC of the live blend, with its half-life (never the holdout)

```text
aq stack decay [-h] [--ml-dir ML_DIR] [--head HEAD] [--split {train,validation,backtest}] [--max-dates MAX_DATES] [--by {class,year,split}] [--window WINDOW] [--html FILE] [--json]
```

| Flag | Meaning |
|---|---|
| `--ml-dir` | Another model folder |
| `--head` | Target head (default rank_20d) |
| `--split` | One split (default validation and backtest) |
| `--max-dates` | Only the last N dates (a small machine) |
| `--by` | Group by (default class) |
| `--window` | Rolling window in dates (default 60) |
| `--html` | Also write an HTML page |
| `--json` | Print JSON instead of text |

#### `aq stack attrib`

Permutation importance of the inputs per asset class

```text
aq stack attrib [-h] [--ml-dir ML_DIR] [--head HEAD] [--split {train,validation,backtest}] [--max-dates MAX_DATES] [--max-features MAX_FEATURES] [--json]
```

| Flag | Meaning |
|---|---|
| `--ml-dir` | Another model folder |
| `--head` | Target head (default rank_20d) |
| `--split` | One split (default validation and backtest) |
| `--max-dates` | Only the last N dates (a small machine) |
| `--max-features` | At most this many inputs (default 30) |
| `--json` | Print JSON instead of text |

#### `aq stack lab-baseline`

Register the installed stack's scores as a lab run, for aq lab compare

```text
aq stack lab-baseline [-h] [--ml-dir ML_DIR] [--head HEAD] [--split {train,validation,backtest}] [--max-dates MAX_DATES] [--lab LAB]
```

| Flag | Meaning |
|---|---|
| `--ml-dir` | Another model folder |
| `--head` | Target head (default rank_20d) |
| `--split` | One split (default validation and backtest) |
| `--max-dates` | Only the last N dates (a small machine) |
| `--lab` | The lab folder |

### `aq trials`

The trial ledgers: N, the deflated-Sharpe hurdle at N, the trials, adding one

```text
aq trials [-h] {count,list,dsr,add} ...
```

#### `aq trials count`

N and where it comes from

```text
aq trials count [-h] [--evaluation-dir EVALUATION_DIR] [--json]
```

| Flag | Meaning |
|---|---|
| `--evaluation-dir` | Default ml/evaluation |
| `--json` | Print JSON instead of text |

#### `aq trials list`

The last trials of every ledger

```text
aq trials list [-h] [--phase PHASE] [--limit LIMIT] [--evaluation-dir EVALUATION_DIR] [--json]
```

| Flag | Meaning |
|---|---|
| `--phase` | Only ledgers whose path contains this |
| `--limit` | At most this many (default 50) |
| `--evaluation-dir` | Default ml/evaluation |
| `--json` | Print JSON instead of text |

#### `aq trials dsr`

The Sharpe a new candidate must beat at the current N, and a returns series' DSR

```text
aq trials dsr [-h] [--window WINDOW] [--returns RETURNS] [--periods PERIODS] [--evaluation-dir EVALUATION_DIR] [--json]
```

| Flag | Meaning |
|---|---|
| `--window` | Only this window's trials for the variance |
| `--returns` | CSV with a return column |
| `--periods` | Periods a year (default 252) |
| `--evaluation-dir` | Default ml/evaluation |
| `--json` | Print JSON instead of text |

#### `aq trials add`

Record a manual trial (it counts toward N when its role is candidate)

```text
aq trials add [-h] --trial-id TRIAL_ID --role {candidate,verification,placebo,plumbing} --sharpe SHARPE --obs OBS [--track TRACK] [--window WINDOW] [--note NOTE] [--ledger LEDGER] [--dry-run]
```

| Flag | Meaning |
|---|---|
| `--trial-id` |  |
| `--role` |  |
| `--sharpe` | Annualised Sharpe |
| `--obs` | Observations |
| `--track` | Default manual |
| `--window` | The window it was judged on (default manual) |
| `--note` |  |
| `--ledger` | Default ml/evaluation/v671/trial_ledger.jsonl |
| `--dry-run` | Print what would happen, change nothing |

### `aq runs`

Lean runs in backtests/: list them, show one with its engine-log verdict, diff two with their frozen configs

```text
aq runs [-h] {list,show,diff} ...
```

#### `aq runs list`

Newest first: Sharpe, net profit, drawdown, orders, the README pin, a frozen config

```text
aq runs list [-h] [--limit LIMIT] [--json]
```

| Flag | Meaning |
|---|---|
| `--limit` | Default 15 |
| `--json` | Print JSON instead of text |

#### `aq runs show`

Every statistic of one run and its engine-log verdict (rule 7)

```text
aq runs show [-h] [--json] run
```

| Flag | Meaning |
|---|---|
| `run` |  |
| `--json` | Print JSON instead of text |

#### `aq runs diff`

The statistics that differ, and the configs' leaf diff

```text
aq runs diff [-h] [--json] run_a run_b
```

| Flag | Meaning |
|---|---|
| `run_a` |  |
| `run_b` |  |
| `--json` | Print JSON instead of text |

### `aq api-diff`

The library's public names added and removed since a tag, and the semver bump that implies (exit 3 on a removal)

```text
aq api-diff [-h] [--json] [ref]
```

| Flag | Meaning |
|---|---|
| `ref` | A tag or commit (default: the latest tag) |
| `--json` | Print JSON instead of text |

### `aq release`

Before tagging: tree, branch, CI, changelog, version against the API, wheel build and smoke (never tags)

```text
aq release [-h] {check} ...
```

#### `aq release check`

Every pre-tag check (exit 3 on a failure)

```text
aq release check [-h] [--json] version
```

| Flag | Meaning |
|---|---|
| `version` |  |
| `--json` | Print JSON instead of text |

### `aq health`

Maintainer dashboard: code size, tests, coverage per subsystem, gate ceilings, Problems, with a trend

```text
aq health [-h] [--history] [--json]
```

| Flag | Meaning |
|---|---|
| `--history` | Append today's row to development/health_history.jsonl and show the change |
| `--json` | Print JSON instead of text |
<!-- AQ:CLI_REFERENCE_END -->
