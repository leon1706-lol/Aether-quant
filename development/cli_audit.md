# The `aq` CLI audit (V6.7.1)

Every `aq` command and subcommand rated 1-10 before this phase, with the gaps found and what closed them, then rated again against one rubric. The ratings before are from the audit at the start of the phase (2026-11-20). The ratings after need every rubric point to hold, and each point names the test or document that shows it.

## The 10/10 rubric

A command is 10 only when all six hold. A new command is built to it from the start (AGENTS.md "Conventions").

| # | Point | What it means | Enforced by |
|---|---|---|---|
| 1 | **Tested** | An argv-level parse test, plus behaviour tests of the success path, every error path and every exit code; 100% line coverage of its code | `test_every_leaf_parses_to_its_command` (`tests/test_cli_help_surface.py`), the command's own test file below, the coverage gate |
| 2 | **Flags** | Companion flags validated (exit 2 with the fix), types and choices enforced, one spelling (`--dry-run`, `--yes`, `--json`, `--account`). A read command has `--json`; a write has `--dry-run` (or `--check`); a deletion or a loosened safety switch asks on a terminal and needs `--yes` without one | `test_every_leaf_is_classified_and_has_the_flags_its_class_needs`: every leaf is in `READ_COMMANDS`, `WRITE_COMMANDS`, `CONFIRM_COMMANDS` or `EXEMPT` with a reason; `companion_errors` tables (#417) |
| 3 | **Help** | A one-line purpose, defaults stated, no version history, an epilog with real examples | `test_every_leaf_has_examples_and_no_version_history_in_its_help` |
| 4 | **Docs** | A README `#### \`aq X\`` section naming every flag, an entry in the generated `docs/reference/cli.md`, an example | `test_readme_documents_every_parser_flag`, `test_readme_documents_no_phantom_flags`, `test_the_generated_reference_page_names_every_command`, `aq docs sync --check` in CI |
| 5 | **Errors** | One line with the fix, no traceback, exit codes 0 ok / 1 failure / 2 usage / 3 gate failed or still running / 130 interrupted; degrades without Redis, Postgres, IB, Docker, gh or a network (rule 3) | `run_command` (`test_run_command_turns_ctrl_c_and_crashes_into_exit_codes`), `_AqParser` suggestions, each command's error-path tests |
| 6 | **Fast** | `aq <cmd> --help` well under the old 5.7 s; no heavy import before the command runs | `test_help_is_fast`, `test_importing_aq_cli_loads_no_pandas_numpy_or_torch` (#421) |

**What cannot be proven in an agent session.** Two paths are tested against fakes up to the external boundary and marked "10 (fake-proven)" below: `backtest` against real Lean (owner-only, rule 4) and `live up` against a real broker (needs the keys). `models install` was proved against the real v6.7.1 release.

## Global changes

| Gap (before) | Fix |
|---|---|
| `aq --help` took 5.7 s: `aq_cli` imported pandas through `data_pipeline.fetch` at import | Lazy names through a module `__getattr__` (#421) |
| No `--version`, no completion, no `aq help`, an unknown command gave argparse's bare error | `--version`, `aq version`, `aq completion bash\|zsh\|powershell`, `aq help CMD`, and "did you mean" on every mistyped command or choice |
| A crash printed a traceback; Ctrl-C printed one too | One line and exit 1 (`--debug` or `AQ_DEBUG=1` for the traceback); Ctrl-C is exit 130 |
| The update check ran after every command, JSON included | Only on a terminal, never with `--json` |
| Help strings carried version history ("V5.5.0:", Problems numbers) | Stripped; history lives in the Changelog |
| `aq evaluate`'s ~70 flags were one flat list | Argument groups, `--list`, an example per group |
| Companion flags were silently ignored (`evaluate`, `train`, `test`) | `companion_errors`: `--x needs --y`, exit 2 (#417) |
| No command reference on the docs site | `docs/reference/cli.md`, generated from the parser by `aq docs cli` and `aq docs sync` |

## Every command

"Before" is the start-of-phase rating; "After" holds only with all six rubric points. The test column names the command's own tests; the four rubric tests above apply to every row.

| Command | Before | After | Gaps found → fixed | Tests |
|---|---|---|---|---|
| `aq` (global) | 4 | 10 | See "Global changes" | `test_aq_cli_commands.py` (entry points), `test_cli_help_surface.py` |
| `hello` | 9 | 10 | Epilog | `test_hello_world.py`, `test_aq_cli.py` |
| `models list/info/score/remove` | 8 | 10 | `remove`; `list/info --json` | `test_aq_models_cli.py` |
| `models install` | 8 | 10 | Local zips (`--from`), checked against their own manifest; proved against the real v6.7.1 release | `test_aq_models_cli.py`, `test_model_catalog.py` |
| `init` | 8 | 10 | `--force`, `--dry-run` | `test_project_template.py` |
| `pipeline run/status/validate/list` | 6 | 10 | Python 3.10 crash (#413); `validate`, `list`, `--json` | `test_project_template.py`, `test_pipeline.py` |
| `train` | 6 | 10 | Companion flags (#417), `--dry-run`, `--list-runs --json` | `test_aq_cli.py`, `test_aq_train_resume.py`, `test_aq_cli_last_branches.py` |
| `test` | 7 | 10 | Paths and verbs (`new`, `where`, `slowest`, `clean-checkout`, `mutation`, `fuzz`), `-k`, `--lf`, `--impacted`, `--watch`, `--repeat`, `--light-hypothesis` (#420), `--list-groups`, JUnit of every run | `test_aq_cli.py`, `test_aq_testtools.py` |
| `backtest` | 5 | 10 (fake-proven) | `--no-publish`, `--dry-run`, the run's config frozen under its name (#419) | `test_aq_cli.py` (synthetic run folders, `_lean_run_names`) |
| `profile` | 6 | 10 | Help cleaned; its output is the profiler's own table, and `aq bench run --json` gives the timings as JSON | `test_aq_cli.py` |
| `report` | 5 | 10 | No arguments lists the newest runs; the result id is found when the folder holds one | `test_aq_cli.py` |
| `research` | 7 | 10 | `aq signal check` runs first; `--json` | `test_aq_cli.py`, `test_signal_tools.py` |
| `prove` | 7 | 10 | `--list`, `--json` | `test_aq_cli_verify.py` |
| `cycle research/status/daily/decide/retrain/promote/schedule` | 8 | 10 | `retrain --host` enforced; `status --json` | `test_aq_cycle_cli.py`, `test_aq_cli_cycle.py` |
| `retrain` | 4 | 10 | Help points at `aq cycle retrain`; `--dry-run`; stage choices match the orchestrator's (`RETRAIN_STAGES`) | `test_aq_cli.py` |
| `api` | 4 | 10 | `--host`, `--port`, `--no-reload`, `--check` | `test_aq_cli.py` |
| `webui` | 6 | 10 | `--port`, `--open` | `test_aq_cli_cycle.py` |
| `docker up/build/down/ps/logs` | 5 | 10 | `down`, `ps`, `logs`, `--dry-run`, a clear "Docker is not running" | `test_aq_cli.py` |
| `config get/keys/set/diff/validate/preset` | 7 | 10 | `diff` (rule 9 review), `validate` (duplicate keys, NaN), `set --dry-run`, a type change needs `--force` | `test_aq_cli.py`, `test_aq_devtools.py` |
| `lean get/keys/set/diff/validate` | 6 | 10 | The same; `set` refuses secret fields | `test_aq_cli.py` |
| `backfill` | 5 | 10 | The target choices come from the module table it dispatches to; help states that every backfill is a dry run unless given `--apply` | `test_aq_cli.py` |
| `paper-readiness` | 4 | 10 | `--json`; help says how it differs from `live-readiness` | `test_aq_cli.py` |
| `clean` | 6 | 10 | `coverage`, `caches`, `build` targets; dry run by default; `--apply` asks (`--yes`); `--json` | `test_aq_cli.py`, `test_aq_devtools.py` |
| `trade-lock`, `kill-switch` | 8 | 10 | Loosening asks (`--yes`), `--dry-run` prints old → new, every change in the audit log, `--json` | `test_aq_cli.py` |
| `fetch` | 7 | 10 | `--json`; its asset classes tested against the fetch module | `test_aq_cli.py`, `test_aq_cli_commands.py` |
| `ib status`, `assets status` | 6 | 10 | `--json` | `test_aq_cli.py` |
| `evaluate` | 4 | 10 | Groups, `--list`, companion flags (#417), the stale book history named (#418), a missing frozen config said | `test_aq_cli.py` |
| `render-lean-config` | 7 | 10 | `--dry-run` (names, never values), `--check` | `test_aq_cli.py` |
| `users add/list/rotate/remove` | 8 | 10 | `rotate`; `rotate` and `remove` ask (`--yes`); `list --json` | `test_aq_cli_commands.py`, `test_aq_accounts_cli.py` |
| `accounts`, `live-readiness` | 8-9 | 10 | `--json` | `test_aq_accounts_cli.py` |
| `live up/down/status` | 8 | 10 (fake-proven) | `status`; `up` on a live account asks | `test_aq_accounts_cli.py` |
| `secrets status/set/delete`, `secrets-check` | 8-9 | 10 | `delete` asks (`--yes`); `secrets-check --json` | `test_aq_cli_commands.py` |
| `audit-log` | 7 | 10 | `--json`, `--until`, `--export` | `test_aq_cli.py` |
| `docs sync/build/serve/cli/links` | 7 | 10 | `build`, `serve`, `cli` (the generated reference), `links` (relative links and anchors; `--external`), `sync --json` | `test_aq_devtools.py`, `test_docs_facts.py` |
| `verify` | 7 | 10 | `--json` | `test_aq_cli_verify.py` |
| `status` | 2 | 10 | Rewritten: branch, CI of HEAD, hook and coverage gate, coverage age, Dependabot PRs, running Codespaces, todo.md (`--git` for the old output) | `test_aq_devtools.py` |

### New commands (built to the rubric)

| Command | What it is for | Tests |
|---|---|---|
| `hooks install/status/coverage`, `commit --skip-coverage`, `check` | The pre-commit hook: install it, see its gates, skip its coverage gate once or until turned on (CI still enforces 100%), run it without committing | `test_aq_devtools.py`, `test_install_hooks.py` (the real hook under `sh`) |
| `doctor`, `version`, `completion`, `help`, `bug-report` | Is this machine set up, what is installed, shell completion, help by name, a report without paths or user names | `test_aq_devtools.py` |
| `ci status/logs/local` | CI of a commit (`--watch`), the failing lines of a run, a job's steps run here | `test_aq_devtools.py` |
| `deps prs/apply/lock/pins/audit/why` | Dependabot PRs applied on main with rebuilt locks (#415), the locks, pins and audit, why a package is locked | `test_aq_devtools.py` |
| `coverage report/misses/clean` | The last run's gaps, by function | `test_aq_devtools.py` |
| `codespace list/stop/delete` | Billing Codespaces in red (rule 13) | `test_aq_devtools.py` |
| `vault record/graph`, `problems next/show/open`, `phase check`, `lint`, `scaffold` | Phase bookkeeping: vault records, the next Problems number with a template, what a phase still owes, ruff and the type check, a new module with its registered test | `test_aq_devtools.py` |
| `examples`, `notebooks` | List and run the examples and tutorials | `test_aq_devtools.py` |
| `bench run/baseline/compare` | Hot-path timings against a per-machine baseline (exit 3 on a regression) | `test_aq_testtools.py` |
| `runs list/show/diff` | Lean run folders: statistics, the engine-log verdict (rule 7), the frozen configs' diff | `test_aq_lab_cli.py` |
| `data fetch/sample/info/explore/manifest/diff` | Close tables: download, the bundled sample, coverage and gaps, an HTML exploration, sha256 manifests and their diff (rule 12) | `test_aq_lab_cli.py`, `test_data_explore.py` |
| `signal check/eval/compare/neutralize/backtest` | A `date, ticker, score` file: validated, judged by IC and decay, compared, neutralised on market betas, backtested after costs with PSR and DSR | `test_aq_lab_cli.py`, `test_signal_tools.py` |
| `features list/build/inspect` | The feature registry: names, a feature table, one feature's IC and overlap | `test_aq_lab_cli.py`, `test_feature_registry.py` |
| `overfit pbo/psr/dsr/hurdle/haircut/mintrl` | The overfitting statistics as calculators | `test_aq_lab_cli.py` |
| `lab init/new/train/runs/show/eval/compare/card/sweep/explain/ablate/seeds/export` | The model lab ([`docs/guide/model-lab.md`](../docs/guide/model-lab.md)): every run a counted trial, the holdout sealed, export to `aq models` | `test_aq_lab_cli.py` and the `lab` group |
| `dataset build/info/leakage` | Datasets in the production layout, with purged splits and a leakage audit | `test_aq_lab_cli.py`, `test_lab_dataset.py` |
| `stack inspect/decay/attrib/lab-baseline` | The installed models (source checkout): metrics, decay by class, importance, a lab baseline | `test_aq_lab_cli.py` |
| `trials count/list/dsr/add` | The project's N and the Sharpe a candidate must beat | `test_aq_lab_cli.py`, `test_trial_ledger.py` |
| `api-diff`, `release check`, `health` | The library's surface against a tag with the semver bump, a release's checks (never tags), the maintainer dashboard | `test_aq_lab_cli.py` |
