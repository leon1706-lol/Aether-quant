# AGENTS.md: guidance for AI coding agents

**Aether Quant** is a self-adapting trading system on QuantConnect Lean and PyTorch, and a toolkit (`aether_quant`, `aq`) for building other algorithms. The shipped book is a long-only crypto trend sleeve (70%) beside a multi-asset model book (30%), on paper, reinstated and not verified. A model stack, research cycle, kill switch, reconciliation and controlled retraining surround it. Read this before changing anything.

## Before touching anything

- **[`todo.md`](todo.md):** the owner's current objectives. Check it first. It gets rewritten, so if it's empty, ask, or read `development/Changelog.md`'s latest phase.
- **Sub-readmes:** every folder has one; read it before editing that folder.
- **`development/*.md`:** structure and problems context.
- **`Aether-quant-Obsidian-Vault/`:** a generated code graph for orientation. It can be stale, so verify against source.

## Commands

```powershell
pip install -e .          # register `aq` from source (pyproject.toml)
aq test                   # full suite, then the doc facts (aq test --risk etc. = one subsystem)
#                         # no --parallel on a low-memory machine: each xdist worker imports torch
aq test --coverage        # every group in turn under coverage: every tracked module must reach 100%
aq test --coverage --changed   # the fast gate before a commit (the pre-commit hook): changed modules at 100%
python scripts/scorecard_pins.py      # every install pinned by hash (OpenSSF Scorecard), must print 0
python scripts/lock_requirements.py   # regenerate requirements/lock/*.txt from their .in files (uv)
aq evaluate               # offline evaluation
aq cycle status           # generations, shares, decay, what is due (RUNBOOK "Research cycle")
aq docs sync              # refresh numbers quoted in the docs
aq backtest               # real Lean backtest (Docker, ~1hr+): the owner runs this, never agents
ruff check .              # must be clean before commit: 14 rule sets, each exclusion's reason in pyproject.toml (the pinned ruff, tools.in)
aq doctor                 # is this machine set up: Python, the editable install, the hook, git, gh, Docker, RAM, config.json
aq status                 # branch, CI of HEAD, hook and coverage gate, coverage age, Dependabot PRs, running Codespaces, todo.md
aq test --impacted        # only the tests that name changed modules, no coverage (--watch reruns on every save)
aq check                  # the pre-commit hook's gates without committing (--no-coverage skips the slow one)
aq commit -m "msg" --skip-coverage   # commit through the hook with its coverage gate off for this commit only
aq hooks coverage off --once         # the same for the next plain git commit (aq hooks coverage on|status)
aq ci status --watch      # every workflow of HEAD until done; aq ci logs 123 prints a run's failing lines; aq ci local fast-guards
aq deps prs               # open Dependabot PRs; aq deps apply 58 applies one on main with its locks rebuilt (never commits)
aq coverage misses --include "risk/*" --by-function   # the last run's uncovered lines
aq lint                   # ruff (--fix, --types for the typecheck job)
aq docs cli               # regenerate docs/reference/cli.md from the parser (aq docs sync does it too)
aq phase check --version V6.7.1  # what the phase still owes: the automatic checks of "After every phase", the rest as reminders
aq trials count           # the project's N (every trial ledger plus the legacy registry)
aq codespace list         # billing Codespaces in red (stop, delete --yes)
aq vault graph --summary "s" --files a.py   # the wrap-up's two vault commands in one
aq lab train m1           # the model lab (aq lab --help, docs/guide/model-lab.md)
```

## Non-negotiables

1. **Pure, testable modules over `main.py` logic.** `main.py` only runs inside Lean: its order paths and `on_data()` on the target-weights path are stub-tested (`tests/test_main_wiring.py`, `tests/test_main_on_data_target_weights.py`), but not Lean's fills. Anything needing tests is a pure function both `main.py` and `tests/` can import.
2. **Nothing is done until verified.** Run `aq test` after every code change (or `pytest` from the repo root, which `testpaths` points at `tests/`; a path of `.` crawls the code each Lean run copies into `backtests/`, #8), with ruff clean. Never commit a red suite.
3. **Fail safe, degrade gracefully.** Never assume Redis, Postgres or IB is available. Never let NaN, inf or None pass silently through feature pipelines: use `json_safety` helpers and explicit guards.
4. **No secrets in commits. No `aq backtest` in any automated gate or agent session.**
5. **New top-level `.py` module:** add it to `pyproject.toml` `py-modules` (or, if `aq` never imports it, to `INTENTIONALLY_NOT_SHIPPED` in `tests/test_packaging_modules.py`), then `pip install -e .`. A stale editable install breaks `aq` with `ModuleNotFoundError`.
6. **Offline/live parity.** Any change to the live path (`main.py` signal, book, sizing, gates, orders) reuses the pure function the offline simulator calls, or ships a parity test. Live-only logic needs a one-line justification in `development/architecture.md`'s Offline/Live Parity Contract.
7. **Evidence comes from the engine log.** Lean teardown claims are checked in `backtests/<run>/log.txt`, never only `<id>-log.txt` (#104).
8. **Every owner-run backtest gets written up** (Problems.md, Changelog.md, `aq evaluate --lean-report`) before further work builds on it.
9. **New `config.json` keys default to current behaviour.** Behaviour flips are owner decisions, recorded in the Changelog.
10. **`main.py` lives behind Lean's `from AlgorithmImports import *`,** which exports `time` (`datetime.time`) and `Exception` (.NET's, which no Python error matches, #276). Never `import time` there (use `from time import perf_counter as _perf_counter` after the star import), and keep `from builtins import Exception`. Run `tests/test_main_ensure_ready_smoke.py` after touching its imports or config reads. Read the **engine** log of any backtest before calling a failure understood (#132).
11. **Latency-aware.** Hot-path code (`main.py` per-bar, `inference/`) allocates nothing new per bar without need, does no per-bar disk I/O, and keeps diagnostics behind default-off flags. Heavy imports stay out of Lean startup (#16).
12. **Data parity is checked against live, not against code.** A dataset row sees the bars live would have at that tick (`features/cross_asset_timing.py`), and local `data/` and the Codespace's must be file-for-file identical (a push overlays, never deletes). After any feature or dataset change, compare a backtest's `feature_snapshot` with `aq evaluate --reconcile-features`. Don't run a heavy process during `aq backtest` on the PC: `import main` runs under `algorithm-creation-timeout`. CI runs Python 3.11, the dev PC 3.14, the Codespaces pandas 3: test with the stub guards, not by intuition.
13. **Codespaces bill the owner's budget: on only while a job runs.**
    - Run `aq codespace list` (or `gh codespace list`) at the start and end of every session, and stop anything idle (`aq codespace stop --all`).
    - Anything that fits on the dev PC runs locally. Create every Codespace with `--idle-timeout 30m`.
    - The training Codespace is started for one job and stopped once results are pulled.
    - A Lean DinD Codespace bundles every Lean run of a phase into one lifetime, then `gh codespace delete` in the same session (its ~20 GB image is billed storage).
    - Record on and off times in the phase's Changelog "Hosts" bullet.
14. **Every commit that adds a public function or class to a shipped package updates `aether_quant`, or lists why it stays out.** Export it from the matching facade (`aether_quant/<subsystem>.py`), regenerate the API pin (`AQ_UPDATE_API_SNAPSHOT=1 aq test --meta`) and add a line to `aether_quant/README.md`; a name that must stay out goes under `unexported` in `tests/data/aether_quant_unexported.json` with a reason. `scripts/library_gate.py` enforces this in the pre-commit hook (`python scripts/install_hooks.py`) and in CI's fast-guards, and its legacy backlog can only shrink.
15. **Every install is pinned by hash** (the OpenSSF Scorecard's Pinned-Dependencies). A workflow, Dockerfile or shell script installs with `pip install --require-hashes -r requirements/lock/<profile>.txt` (then `--no-deps -e .` or `--no-deps <wheel>`), `npm ci`, and actions and images by commit and digest. Edit the profile's `.in` and run `python scripts/lock_requirements.py --profile <name>` (uv; a Dependabot floor bump needs it on its branch). `python scripts/scorecard_pins.py` must report nothing: it runs in the pre-commit hook and in fast-guards.

## Where things live

| Path | What lives here |
|---|---|
| `main.py` | Lean algorithm entry point |
| `risk/` · `portfolio/` · `execution/` | Sizing, kill switch · target weights, book construction, HRP, the book optimizers and the model book (`book_optimizer.py`, `model_book.py`), options · order gate, cost model, reconciliation |
| `features/` · `inference/` · `moe/` | Pure features (`feature_registry.py`: the named features `aq features` and the lab build) · model loading and batch inference · gating |
| `lab/` | The model lab (`aq lab`, `aq dataset`): the production networks, losses and training utilities (moved from `train.py`, which re-exports them), datasets, the trainer, runs, evaluation, sweeps, explanations and export; `lab/README.md`, `docs/guide/model-lab.md` |
| `train.py` · `train_*.py` | Training loop · specialized trainers |
| `evaluation/` · `retraining/` | Offline eval, research rounds, generations' registry and ledger, `pipeline.py` (`aq pipeline`) · candidate gates, versioning, `slicing.py` (the low memory profile), `run_resume.py` (resumable runs), `model_catalog.py` (the example models) |
| `ml/artifact_pins.json` · `retraining/artifact_pins.py` | The sha256 of every installed model file, checked before anything scores with them and by `tests/conftest.py` after every suite run |
| `ml/generations/` | Generations, glide policy, lifecycle log, the once-only holdout ledger (tracked; nothing in Lean reads it) |
| `aether_quant/` | The library, pinned by `tests/data/aether_quant_api.json`; `_templates/project/` is what `aq init` copies |
| `formal/inventory.json` | Every public function of the trading and research paths and how it is proved (`scripts/formal_inventory.py`; the backlog only shrinks) |
| `fuzz/` | Atheris fuzz targets (`targets.py`, run by `.github/workflows/fuzz.yml`; hypothesis drives them in the suite) |
| `requirements/lock/` | Hash-locked install sets per job (`*.in` → `*.txt`, `scripts/lock_requirements.py`) |
| `development/openssf_best_practices.md` | The OpenSSF Best Practices answers, ready for the owner to enter |
| `experience/` · `audit/` · `monitoring/` · `notifications/` | Redis and Postgres pipeline · hash-chained audit log · FastAPI · Telegram |
| `data_pipeline/` · `regime/` · `topology/` | Backfills · regime detection · topology overlay |
| `docs_facts.py` · `json_safety.py` · `performance_probe.py` · `aq_cli.py` | Doc facts · finite-safe JSON · opt-in probes · the CLI |
| `aq_devtools.py` · `aq_testtools.py` · `aq_lab_cli.py` | The developer and owner commands (hooks, commit, check, doctor, status, ci, deps, coverage, codespace, vault, problems, docs build/cli/links, scaffold, phase) · the `aq test` verbs and `aq bench` · the lab, data, signal, features, overfit, dataset, stack, trials, runs, api-diff, release and health commands |
| `development/cli_audit.md` · `docs/reference/cli.md` | Every command rated against the 10/10 rubric, with evidence · the generated command reference (`aq docs cli`) |
| `development/health_history.jsonl` | One dated row per `aq health --history`: lines, tests, backlogs, Problems |
| `tests/` · `development/` · `webui/` | The suite · docs and logs · React dashboard |

## Conventions

- **One test file per source module.** Cross-module regressions go in round files (`test_v660_fixes.py`), committed with their fix.
- **Register every new test file** in `aq_cli.py`'s `_SUBSYSTEM_TEST_FILES`, or subsystem runs silently skip it (`aq test new MODULE` and `aq scaffold module PATH` do it).
- **A new command meets the 10/10 rubric** in `development/cli_audit.md`: tested at the argv level and on every error path, `--json` where it reads, `--dry-run` where it writes, `--yes` where it deletes or loosens a safety switch, an epilog with examples, a README section naming every flag, one-line errors with the exit-code convention, and a fast `--help`. `tests/test_cli_help_surface.py` enforces it.
- **Docs move with code:** README and sub-readmes, `development/`, `aq --help` for new flags.
- **A doc or doc section added is named here,** in "Where things live" or "After every phase", so an agent finds it.
- **Synthetic worlds first.** `tests/README.md` "Synthetic worlds" names the fake Lean (`main.py`), the trainer and `train.py` worlds and the script loader. A new runtime test uses one rather than a fresh stub.
- **Use Aether-Vault wherever it has a use** (`scripts/vault_record.py`, `retraining/vault_*`; not the Obsidian code graph above). Its commit timestamp is the proof that something existed before what judged it, so a research phase records its rules before the first score, its trial ledger and gate results, the frozen candidate before any verification row, and the installed weights and config; a retrain records the new models. A phase that scores, freezes or installs without a vault record cannot show its order of events later. V6.6.9 recorded only the rules and the freeze, and should have recorded the ledger at each gate, the verification, the Lean pins and the install too.
- **100% coverage of every tracked module, no pragma:** the next section.
- **Numbers in docs are facts, not text.** A count, window or version goes through `<!--fact:key-->` (`docs_facts.py`) or a generated `AQ:*` block. `tests/test_docs_facts.py` also fails on a path, `phase_v2` key, `aq` command or problem number that no longer exists in a living doc.
- **The README's Backtest Statistics shows the shipped book only.** The retired book's blocks live in `development/research_results.md`.
- **Problems.md and Changelog.md entries are condensed.**
  - Problems: `### N. Title`, then a status and severity line, then **Problem:** / **Fix:** / **Verification:**, each 1-3 sentences.
  - Changelog: `## Phase N — Title`, then one bold-led bullet per fix, about 2 sentences: what changed and why.
  - A condensing pass snapshots to `development/backups/` first.
- **Problems.md status markers:** 🟢 `fixed` (changed and verified) · 🟡 `partial` (shipped, verification pending) · 🔴 `closed` (no code fix: declined, moot, superseded).
- **Comments: short and precise.** Keep one only if it says what the code can't: a non-obvious why, an invariant, a gotcha. Process history belongs in git log, Changelog and Problems.

## Coverage: 100% after every commit

Every tracked `.py` outside `tests/` is measured, and the gate is literally 100%. Nothing is excluded but `if TYPE_CHECKING:` (`tests/test_coverage_scope.py`). CI's `python-tests` fails under 100, and the pre-commit hook runs the fast gate.

- **Before every commit: `aq test --coverage --changed`.** The hook runs it (`aq check` runs the hook without committing). It runs every registered test that names a module changed since HEAD (new files included) and fails on any uncovered line in those files.
  - A fresh full `coverage-report/coverage.json` that already shows them covered passes at once. Every coverage output (data, json, xml, html, JUnit) lives in `coverage-report/`.
  - More than 40 changed modules means a phase: run `aq test --coverage`.
  - Skipping it is only for the commit right after a full run on that tree: `aq commit -m "..." --skip-coverage`, or `aq hooks coverage off --once` before a plain `git commit` (both set the hook's `AQ_SKIP_COVERAGE_HOOK=1` mechanism; the other gates still run, and CI still enforces 100%).
- **A new line ships with the test that runs it,** in the module's own `tests/test_<module>.py`, registered in `_SUBSYSTEM_TEST_FILES` (the gate refuses an unregistered test that names the module). Never `# pragma: no cover`, never a new `omit`, never a test that only imports.
- **Finding misses.** After a run: `aq coverage misses --include "risk/*" --by-function --context 2` (`scripts/coverage_misses.py`), and `aq test where risk/kelly.py` for which files test a module. The last full run's `coverage-report/coverage.json` is the worklist.
- **Use the synthetic worlds, not a fresh stub:**
  - `tests/lean_world.py` with `tests/lean_fakes.py` (main.py against a fake Lean);
  - `tests/train_world.py` with `tests/trainer_fakes.py` (train*.py);
  - `tests/script_loader.py` (`load_script`, `run_script`, `fake_module`, `block_path_writes`, `stop_at_first_read`);
  - `tests/research_fakes.py` and `tests/synthetic_lean.py` (research scripts, Lean run folders).
- **Dead code is deleted, not excluded.** A branch no input can reach goes, and the commit says why. A defensive guard stays only if a test reaches it.
- **CI has no gitignored files.** A test that skips without `ml/` or `data/` leaves lines uncovered there: build its input in a tmp dir and confirm with `scripts/clean_checkout_test.ps1`.
- **Gotchas:**
  - Never `--cov=pkg.module` (it double-imports); use bare `--cov` with `coverage report --include`.
  - Give each slice its own `COVERAGE_FILE`.
  - On the 4 GB PC, run the full gate detached (`Start-Process aq -ArgumentList 'test','--coverage'`) with other apps closed.
  - Scripts a test runs as a subprocess are measured through `patch = ["subprocess"]`.

## Model training

Train locally with `aq cycle retrain --host local --memory-profile low` (fits the 4 GB dev PC, slower; 14 GB for the standard profile; `--estimate` prints each profile's peak, `--smoke` proves the plumbing anywhere), or on the Codespace `aq-Training-Ground-Fixed` through the CLI (sync the full local project first, including gitignored files; bring model, data and extra files back afterwards). A stopped retrain continues with `aq cycle retrain --resume [RUN_ID]` (its folder `ml/cycle/retrain_<id>/` holds `resume.json`, `state.json`, `walk_forward_run_id`), a stopped `aq train` with `aq train --resume` (`ml/cycle/train_<id>/`, `retraining/run_resume.py`), and `--list-runs` lists both. On the 4 GB PC start a long run detached (`Start-Process`) and run nothing else heavy beside it: a background shell is stopped when memory runs low.

Lean backtests run on a temporary DinD Codespace (`scripts/codespace_lean_run.ps1`, `development/infrastructure.md`). Delete it when its runs are pulled.

## CI

`forward-ledger.yml` and `research-cycle.yml` run each session on free runners and write only to branch `forward-ledger`.

`.github/workflows/ci.yml` (Python 3.11): `python-tests` (ubuntu and windows, 100% coverage gate over every tracked module, coverage XML/JSON/HTML and a JUnit report), `python-lint`, `dependency-audit`, `webui-tests` (with coverage and a blocking `npm audit`), `cli-smoke`, `workflows-lint`, and the guard jobs: fast-guards, subsystem-matrix, wheel-smoke, python-compat, docker-checks (dashboard image smoke and trivy), secret-scan (blocking on the tree), parity-smoke, lite-install, typecheck, docs, notebooks, bandit and cpp-sanitizers (the C++ accelerator under ASan and UBSan, with a canary that must abort). `codeql.yml`, `scorecard.yml` and `pages.yml` (docs, coverage reports, and the coverage and test badges on GitHub Pages) run beside it. `release.yml` attaches the wheel, sdist, SBOM, Sigstore signatures and SLSA provenance to each GitHub release, then reruns the Scorecard; its `backfill_tag` dispatch signs and attaches PyPI's files to an older release. Actions are pinned by commit and base images by digest; Dependabot moves the pins. `tests/test_ci_workflows.py` pins the shape: update it with any workflow change. No Lean backtest in CI. A Docker rebuild is required before any paper or live deploy once material code lands.

## After every phase: what doesn't update itself

Automatic: the PyPI, CI, CodeQL, Scorecard, coverage and test badges; every `<!--fact:-->` and `AQ:*` block (`aq docs sync`, checked in CI), including the command reference in `docs/reference/cli.md`; the site's reference pages; release assets and the Scorecard run that follows a tag. Refresh the rest by hand when its trigger happens:

| Item | Where | Trigger and how |
|---|---|---|
| Changelog highlights | `docs/about/changelog.md`, the paragraph above the generated list | Every phase: three to six bullets of what a user would notice |
| Research Record | README "Research Record" table | A research round: one row with trials, survivors, nearest result and entry |
| Backtest Statistics | README `AQ:BACKTEST`, `BTSTATS_*`, `ALPHA` blocks | A new Lean pin: `generate_backtest_report.py`, then `python scripts/readme_freshness.py --since <date>` |
| Long-window run | `REPRODUCIBILITY.md` "Long-window row" | A new Lean pin: the `long_run` ID |
| Readiness block | `docs/live/paper-to-live.md` `AQ:READINESS` | A paper period: `aq live-readiness` |
| Install sizes | README "Download", `docs/getting-started/install.md` | A dependency change: measure a fresh venv |
| GitHub About | repository description and homepage | The book or the site moves: `gh repo edit --description ... --homepage ...` (the workflow token can't) |
| Older releases | GitHub releases without assets | Once per such release: `gh workflow run release.yml -f backfill_tag=vX.Y.Z` |
| Scorecard account checks | branch protection, code review, CII badge | Owner decisions, outside the code |
| `webui/package.json` version | stays `0.0.0` | Never: a private package, versioned by the image tag |
| OpenSSF Scorecard | `curl -s https://api.securityscorecards.dev/projects/github.com/leon1706-lol/Aether-quant` | Every phase: a check that fell gets a Problems entry (the ceiling without a second maintainer is about 8.8) |
| Best Practices badge | bestpractices.dev, then the README badge | Once, by the owner (a sign-up): `development/openssf_best_practices.md` holds the answers |

## Wrap-up checklist

`aq phase check` lists what of this is still open. After every code change, from [`development/verification.md`](development/verification.md) (`aq verify --list`): unit tests added; for a new invariant in a safety, admission or ledger path a Lean spec with its differential test (`formal/README.md`, `aq prove`) and a property test; for a new public function the `aether_quant` export (rule 14); `aq verify --quick` on the PC; `aq test --coverage --changed` and `python scripts/scorecard_pins.py`; `aq test` (a Codespace when the PC cannot finish it, #324), `aq test --coverage` at 100%, and ruff green; `aq docs sync`; vault regenerated. Before handing over a commit also run `scripts/clean_checkout_test.ps1` (CI has no gitignored files), or on the 4 GB dev PC `scripts/codespace_verify.ps1 -Start`, which runs every CI job except Windows, the webui image build and `npm audit` on a Codespace. A change to the live path adds Lean on a DinD Codespace and the parity test (rule 6). Install the pre-commit hook once: `python scripts/install_hooks.py`.

`aq vault graph --summary "..." --files file1.py file2.py` runs both vault commands; by hand:

```powershell
cd Aether-quant-Obsidian-Vault
python scripts/generate_code_graph.py --repo-root .. --vault .
python scripts/regenerate_vault.py --repo-root .. --vault . --append-handoff --agent ox-alpha --action completed --summary "..." --files file1.py file2.py
```

Then **ask, don't act:** tell the user whether the Docker image needs rebuilding, whether a commit should be saved, and whether an `aq backtest` is needed. Do none of these unprompted.
