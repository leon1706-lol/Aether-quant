# Verification

Every way this project is verified, and when each one is required. The table is generated from `evaluation/verification_matrix.py` (`aq verify --list`; `aq verify --write-doc` rewrites it here), and
`tests/test_verification_matrix.py` holds it to the repository: every CI job, workflow, Lean smoke and formal target has a row, and a way to test the project cannot be added without one.

**After any code change** (AGENTS.md "Wrap-up"): `aq verify --quick` on the PC for what fits it, `aq test` on a Codespace for the rest, then `scripts/codespace_verify.ps1 -Start` before a commit.

- **A new public function or class:** export it from its `aether_quant` facade, or list it with a reason in `tests/data/aether_quant_unexported.json` (`library_gate`). The pre-commit hook (`python scripts/install_hooks.py`) refuses the commit otherwise.
- **A new invariant in a safety, admission or ledger path:** a Lean spec and a differential test (`formal/README.md`, "Adding a target"), `aq prove`, and a property test.
- **A change to the live path** (`main.py` signal, book, sizing, gates, orders): the pure function the simulator calls, or a parity test (AGENTS.md rule 6); Lean on a DinD Codespace.
- **A new module:** its own `tests/test_<module>.py` (`module_has_test`), registered in `aq_cli.py`'s `_SUBSYSTEM_TEST_FILES`.
- **A research round:** rules hashed in the vault before any score (`research_round`), then the stages in RUNBOOK "Research cycle".

<!-- AQ:VERIFICATION_START -->
| Surface | Command | What it proves | Host | Time | Evidence | When |
|---|---|---|---|---|---|---|
| `ruff` | `ruff check .` | style and the obvious errors | PC, CI | 10 s | stdout | every change |
| `vermin` | `vermin -t=3.10- --no-tips --violations -q <first-party>` | no source needs more than Python 3.10 (#326) | PC, CI | 5 s | stdout; CI python-compat | every commit |
| `suite` | `aq test` | the whole offline suite, then the doc facts | Codespace, CI | 4-6 min (PC: out of memory) | stdout, coverage.xml | every commit |
| `buckets` | `aq test --<bucket>` | each of 15 subsystems is self-contained | PC, CI | 1-2 min each | stdout | every commit |
| `guards` | `pytest tests/test_ci_workflows.py tests/test_docs_facts.py tests/test_aether_quant_coverage.py ...` | workflows, docs facts, the library gate, packaging, help surface | PC, CI | 30 s | stdout; CI fast-guards | every change |
| `clean_checkout` | `scripts/clean_checkout_test.ps1 or scripts/codespace_verify.ps1 -Start` | no test depends on a gitignored file; every CI job once, before the push | Codespace | 40-60 min | /tmp/aq_verify/status, <stage>.log | a phase |
| `library_gate` | `python scripts/library_gate.py` | a public function is in aether_quant or explained; the backlog only shrinks | PC, CI | 1 s | stdout; pre-commit hook | every commit |
| `api_pin` | `aq test --meta (tests/test_aether_quant_api.py)` | every export resolves to the real function; the import stays light; the public surface only changes on purpose | PC, CI | 1 min | tests/data/aether_quant_api.json | every commit |
| `quickstart` | `tests/test_aether_quant_quickstart.py` | the library works from an uninstalled checkout, examples included | PC, CI | 1 min | stdout | every commit |
| `wheel_smoke` | `python scripts/wheel_smoke.py (built wheel, outside the checkout)` | every shipped module imports, every aq subcommand has --help, one real call into each library module | Codespace, CI | 2 min | stdout; CI wheel-smoke | a release |
| `prove` | `aq prove` | the Lean 4 specs build (Mathlib) | Codespace, CI | 5 min (Mathlib cached) | stdout; CI formal.yml | every change to formal/ or a modelled file |
| `prove_sorry` | `aq prove --check-sorry` | no sorry or admit in any spec | PC, CI | 1 s | stdout; tests/test_formal_no_sorry.py | every commit |
| `axioms` | `python scripts/check_axioms.py` | every theorem rests on the three standard axioms, but two named native_decide findings | Codespace, CI | 2 min | stdout; CI formal.yml | every change to formal/ |
| `differential` | `aq test --formal` | the Python functions equal the Lean models on thousands of computed cases (18 targets) | PC, CI | 1 min | aether_quant/_formal_cases/*.json | every commit |
| `properties` | `pytest tests/test_v664_properties.py` | invariants of the order gate, admission, session, shares, weight caps, hash chain and JSON safety hold for every input (hypothesis, derandomized) | PC, CI | 2 min | stdout | every commit |
| `mutation` | `python scripts/mutation_check.py --out ml/evaluation/v664/mutation.json` | the tests of seven safety and ledger modules notice a changed comparison, operator or constant | Codespace | 1-2 h | ml/evaluation/v664/mutation.json | a phase |
| `on_data` | `pytest tests/test_main_on_data_target_weights.py` | on_data() on the shipped path places the orders the pure rebalance function says, across a week | PC, CI | 10 s | stdout | every change to main.py |
| `module_has_test` | `pytest tests/test_module_has_test.py` | every shipped module has its own test file or is on the frozen list | PC, CI | 5 s | stdout | every commit |
| `docs_sync` | `aq docs sync --check` | every number quoted in a doc is a current fact | PC, CI | 10 s | stdout | every commit |
| `secrets` | `aq secrets-check` | no secret in a tracked file | PC, CI | 2 s | stdout; pre-commit hook | every commit |
| `readme_freshness` | `python scripts/readme_freshness.py --since <date>` | the README's generated blocks are newer than their inputs | PC | 10 s | stdout | a phase |
| `lean_backtest` | `aq backtest` | a real Lean backtest of the shipped book (the owner runs it) | owner | 1 h+ | backtests/<run>/log.txt | a material change to the book |
| `lean_runs` | `scripts/codespace_lean_run.ps1 -Create/-Push/-Run/-Pull -Delete` | frozen run configs on a DinD Codespace, engine log read for completion (rule 7) | DinD Codespace | 2 min per 3 years | backtests/<run>/ | a change to the book |
| `lean_smoke:option_structures` | `bash scripts/lean_smoke/run.sh option_structures` | all 43 option structures fill in Lean's engine on its sample chain | DinD Codespace | 30 s | backtests/smoke_option_structures | a phase |
| `lean_smoke:futures_margin` | `bash scripts/lean_smoke/run.sh futures_margin` | futures margin calls main.py makes return a number | DinD Codespace | 30 s | backtests/smoke_futures_margin | a phase |
| `lean_smoke:exception_scope` | `bash scripts/lean_smoke/run.sh exception_scope` | Lean's star import shadows Exception, which main.py corrects (#276) | DinD Codespace | 30 s | backtests/smoke_exception_scope | on demand |
| `lean_smoke:main_option_order` | `bash scripts/lean_smoke/run_main_option_order.sh` | main.py's own multi-leg order fills on the sample chain | DinD Codespace | 2 min | backtests/smoke_main_option_order | a phase |
| `lean_smoke:main_option_scenarios` | `bash scripts/lean_smoke/run_main_option_scenarios.sh <scale|all43|arb|assign>` | scale-down, rotation, every structure, the arbitrage router and the assignment sweep through main.py | DinD Codespace | 2 min each | ml/evaluation/v664/lean_smoke_option_*.jsonl | a phase |
| `lean_smoke:live_plumbing` | `bash scripts/lean_smoke/live_plumbing.sh` | main.py runs in Lean's live-paper mode on PaperBrokerage and fake ticks with no login or key, survives Redis then Postgres stopping under it, restarts, and the audit chain verifies | DinD Codespace | 10 min | ml/evaluation/v664/live_plumbing.json | a phase |
| `engine_check` | `scripts/codespace_engine_check.sh` | the pinned engine image runs a teardown-clean algorithm | DinD Codespace | 5 min | /tmp/aq_lean/engine_status | on demand |
| `lean_report` | `aq evaluate --lean-report --backtest-dir <run>` | statistics, alpha proof, attribution and every run-folder tool for a pinned run (rule 8) | PC | 2 min | ml/evaluation/*.json, README blocks | every new pin |
| `reconcile_features` | `aq evaluate --reconcile-features --symbol <X>` | a backtest's feature snapshot equals the dataset's row (rule 12) | PC | 1 min | ml/evaluation/feature_reconciliation.json | a change to features |
| `paper_check` | `aq evaluate --paper-check --backtest-dir <run> --reference-dir <pin>` | a paper run sits inside the frozen bands of the pinned run | PC | 10 s | ml/evaluation/paper_check.json | a paper period |
| `forward_ledger` | `aq evaluate --forward-ledger; aq cycle status` | the forward chains are intact and current | PC, GitHub | 5 s | forward/*.jsonl on the forward-ledger branch | every session |
| `research_round` | `aq cycle research score|placebo|gate|pbo|report --round <file>` | a pre-registered round, rule file hashed in the vault before any score | PC, Codespace | 5 min - 2 h | ml/evaluation/<phase>/ | a research round |
| `audit_verify` | `aq audit-log --verify` | the audit chain in Postgres is intact (a real database; #339) | Codespace | 5 s | stdout | a phase |
| `paper_readiness` | `aq paper-readiness` | the paper-readiness checklist against real services | Codespace | 5 s | visualization/grafana/paper_readiness_report.json | a phase |
| `field_test_services` | `python scripts/field_test_services.py (scripts/field_services.sh up)` | audit events flow Redis to Postgres, a tampered row is found, each service restarts underneath a running pipeline | Codespace | 2 min | ml/evaluation/v664/field_test_services.json | a phase |
| `lean_smoke:field_test` | `python scripts/lean_smoke/field_test.py` | main.py on Lean's paper brokerage places and fills an order, an injected drift breaches reconciliation, an injected shock trips the kill switch and flattens the book, a restart resumes, Redis and Postgres outages pass, two accounts run apart, the audit chain verifies | PC, Codespace | 1 h | ml/evaluation/field_test/<date>/report.json | a phase; a change to the safety path |
| `live_readiness` | `aq live-readiness` | every paper-to-live condition, measured; unknown counts as fail | PC | 10 s | visualization/grafana/live_readiness.json, docs/live/paper-to-live.md | a phase; before any live capital |
| `lite_install` | `pytest tests/test_lite_install.py (a clean venv with the built wheel: aq hello --offline)` | the base install (numpy, pandas) imports every facade and runs aq hello | PC, CI | 1 min | ml/evaluation/v665/lite_install.json | every commit |
| `hello` | `aq hello [--offline]` | the five-minute start downloads keyless data, backtests the shipped rule and reports | PC | 30-60 s | stdout, --json | a release |
| `type_completeness` | `python scripts/type_completeness.py` | every export of aether_quant is fully annotated; the floor only rises | PC, CI | 20 s | ml/evaluation/v665/type_completeness.json | every commit |
| `docs_site` | `python scripts/build_docs.py && mkdocs build --strict` | the docs site builds with no warning, every facade has a reference page | PC, CI | 1 min | site/ | every change to docs/ or a public docstring |
| `notebooks` | `python scripts/build_notebooks.py --check --execute` | the four tutorials match their sources and run clean | PC, CI | 5 min | notebooks/*.ipynb | every change to notebooks/ or the library |
| `dashboard_image` | `docker build --target dashboard -t aether-quant-dashboard . && docker run -p 8080:8000` | the light dashboard image builds, serves the UI and answers /api/health in demo mode | PC, CI | 5 min | ml/evaluation/v665/dashboard.json | every change to Dockerfile, webui/ or monitoring/ |
| `bandit` | `bandit -r <shipped packages> -lll -c pyproject.toml` | no high-severity static finding in shipped code | PC, CI | 1 min | stdout | every commit |
| `coverage` | `aq test --coverage` | every tracked module at 100%, one group at a time | PC, Codespace | 1-2 h on the PC | coverage.json | every commit |
| `ci:python-tests` | `CI: ubuntu and windows, coverage gate 100% of every tracked module` | the suite on both platforms, and the JUnit report behind the test badge | CI | 6 min | GitHub Actions | every push |
| `ci:python-lint` | `CI: ruff and py_compile main.py` | lint and syntax | CI | 1 min | GitHub Actions | every push |
| `ci:dependency-audit` | `CI: pip-audit` | no known-vulnerable pinned dependency | CI | 3 min | GitHub Actions | every push |
| `ci:webui-tests` | `CI: tsc, oxlint (jsx-a11y), vitest with coverage, build, npm audit` | the dashboard builds, its tests pass and no runtime dependency has a high advisory | CI | 2 min | GitHub Actions | every push |
| `ci:cli-smoke` | `CI: aq --help, config get, secrets-check` | the CLI starts from a clean install | CI | 1 min | GitHub Actions | every push |
| `ci:workflows-lint` | `CI: actionlint` | workflow syntax | CI | 10 s | GitHub Actions | every push |
| `ci:fast-guards` | `CI: guard tests` | registration, help surface, workflows, packaging, docs, library gate | CI | 1 min | GitHub Actions | every push |
| `ci:subsystem-matrix` | `CI: aq test --<bucket> for each of 15 buckets` | each bucket stands alone | CI | 2 min each | GitHub Actions | every push |
| `ci:wheel-smoke` | `CI: build and install the wheel outside the checkout` | the package works installed | CI | 1 min | GitHub Actions | every push |
| `ci:python-compat` | `CI: byte-compile and vermin on Python 3.10` | the floor in requires-python holds | CI | 1 min | GitHub Actions | every push |
| `ci:docker-checks` | `CI: hadolint, compose config, dashboard build and smoke, trivy` | the Dockerfiles lint, the compose files parse, the dashboard image serves and has no fixable critical CVE | CI | 6 min | GitHub Actions | every push |
| `ci:lite-install` | `CI: the wheel in a clean venv with no extras` | the light install imports every facade and runs aq hello --offline | CI | 2 min | GitHub Actions | every push |
| `ci:typecheck` | `CI: scripts/type_completeness.py (pyright advisory)` | the public API stays fully annotated | CI | 1 min | GitHub Actions | every push |
| `ci:docs` | `CI: mkdocs build --strict` | the docs site builds | CI | 2 min | GitHub Actions (site artifact) | every push |
| `ci:notebooks` | `CI: build_notebooks.py --check --execute` | the tutorials run | CI | 6 min | GitHub Actions | every push |
| `ci:bandit` | `CI: bandit -lll` | no high-severity static finding | CI | 1 min | GitHub Actions | every push |
| `ci:parity-smoke` | `CI: parity tests and feature_parity_audit --synthetic-only` | live and offline compute the same features | CI | 1 min | GitHub Actions | every push |
| `ci:secret-scan` | `CI: gitleaks (blocking on the tree, advisory on history)` | no secret in a tracked file | CI | 10 s | GitHub Actions | every push |
| `wf:formal` | `.github/workflows/formal.yml` | the proofs, the sorry scan, regenerated cases and axioms on spec changes and monthly | GitHub | 10 min | GitHub Actions | every change to formal/ |
| `wf:forward-ledger` | `.github/workflows/forward-ledger.yml` | one hash-chained forward row a session for the frozen rule | GitHub | 30 s | branch forward-ledger | every session |
| `wf:research-cycle` | `.github/workflows/research-cycle.yml` | one row per tracked generation and the allocation a session | GitHub | 30 s | branch forward-ledger | every session |
| `wf:keepalive` | `.github/workflows/keepalive.yml` | the schedules stay enabled | GitHub | 10 s | GitHub Actions | monthly |
| `wf:release` | `.github/workflows/release.yml` | the tagged commit's suite, PyPI and both images with SBOMs and provenance (the tag is the owner's) | GitHub, owner | 20 min | GitHub Actions | a release |
| `wf:codeql` | `.github/workflows/codeql.yml` | CodeQL over Python, TypeScript and the workflows | GitHub | 10 min | GitHub code scanning | every push to main; weekly |
| `wf:scorecard` | `.github/workflows/scorecard.yml` | the OpenSSF Scorecard of the repository | GitHub | 2 min | GitHub code scanning, scorecard.dev | every push to main; weekly |
| `wf:pages` | `.github/workflows/pages.yml` | the docs, coverage HTML and the coverage badge on GitHub Pages | GitHub | 3 min | https://leon1706-lol.github.io/Aether-quant/ | every green CI on main |
| `wf:ci` | `.github/workflows/ci.yml` | the jobs above | GitHub | 6 min | GitHub Actions | every push |
<!-- AQ:VERIFICATION_END -->
