# tests

The pytest suite for everything except `webui`. The count is on the root README's badge, which `aq test` refreshes.

**Run `aq test`, or `pytest` from the repo root:** `testpaths` in `pyproject.toml` points it at `tests/`, which is what CI does. Pointing pytest at `.` crawls the code each Lean run copies into `backtests/` and collides on module names (#8).

## Conventions

- **One file per source module** (`tests/test_<module>.py`). Cross-module regressions go in round files such as `test_v660_fixes.py`, committed with their fix.
- **Register every new file** in `aq_cli.py`'s `_SUBSYSTEM_TEST_FILES`, or `aq test --risk` and the like skip it.
- **Plain functions and module-level helpers;** no shared `conftest.py`.
- **`tests/` is not a package on CI:** never `from tests.x import ...`.
- **Never assume Redis, Postgres or IB.** Workers (`PostgresWorker`, `TriggerWorker`, `RetrainingWorker`) take `_pg_conn` and `_redis_client` so tests can inject a mocked connection:

```python
def _make_conn_mock():
    conn_mock = MagicMock()
    cur_mock = MagicMock()
    conn_mock.cursor.return_value.__enter__.return_value = cur_mock
    conn_mock.cursor.return_value.__exit__.return_value = False
    return conn_mock, cur_mock
```

## Special suites

- **Synthetic worlds (V6.6.6):** whole programs run on a CPU in seconds, so the gate is a literal 100% with no pragma. Use one before writing a new stub.
  - `lean_world.py` + `lean_fakes.py` (`test_main_world_*.py`): a fake QuantConnect `QCAlgorithm` (portfolio, instant fills, order events, option chains, strategies), synthetic `ml/` artifacts and FRED series, and a seeded market. They drive `main.py`'s setup, bars, books, risk, options and teardown.
  - `train_world.py` (`test_train_pipeline_runtime.py`, `test_train_runtime_gaps_*.py`): Lean-format zips for twelve assets and a trimmed config. `repoint()` moves every module path under the repo root to a temporary root, so nothing touches the real `data/` or `ml/`.
  - `trainer_fakes.py` (`test_train_mains_runtime.py`): a small dataset, schema and config for the multitask, sequence and gating trainers.
  - `script_loader.py` (`test_*_runtime.py` for `scripts/`): loads a script by path, runs its `__main__`, blocks writes and stubs the gitignored stored rules.
- **`main.py` against a Lean stub:** `test_main_wiring.py` installs a minimal `AlgorithmImports`, builds the algorithm with `object.__new__` and drives the order-path methods. It proves this repo's decisions around Lean's APIs, not fill timing, and it doesn't drive `on_data()`. `test_main_ensure_ready_smoke.py` runs the real first-bar setup.
- **Repo guards (`aq test --meta`):**
  - `test_ci_workflows.py`: the CI shape.
  - `test_packaging_modules.py`: every shipped import is shipped.
  - `test_docs_links.py`: relative links and `AQ:*` marker pairs.
  - `test_docs_facts.py`: quoted numbers, the README's library example, and paths, config keys, commands and problem numbers in living docs.
  - `test_ci_scripts.py`: CI helper scripts.
  - `test_aether_quant_api.py`: the library's public surface, and that importing it loads nothing heavy.
  - `test_aether_quant_coverage.py`: the library gate (`scripts/library_gate.py`): every public name is exported or explained, and the backlog only shrinks.
  - `test_module_has_test.py`: one test file per source module, against a frozen list that only shrinks.
  - `test_verification_matrix.py`: `development/verification.md` has a row for every CI job, workflow, Lean smoke and formal target.
  - `test_formal_no_sorry.py`: no `sorry`, every spec built and listed.
- **Property tests:** `test_v664_properties.py` (hypothesis, derandomized) states invariants of the order gate, admission, session resolution, generation shares, weight caps, the hash chain and JSON safety, and checks them on generated inputs.
- **`on_data()`:** `test_main_on_data_target_weights.py` drives the real entry point for a week of sessions on the stub and compares its orders with the pure rebalance function.
- **Mutation check:** `scripts/mutation_check.py` (on a Codespace; `test_mutation_check.py` tests the tool) changes one thing at a time in seven safety and ledger modules and counts what their tests miss. `test_v664_mutation_safety.py` and `test_v664_mutation_ledgers.py` are the boundary tests it called for: every threshold in the kill switch, order gate, risk controls, admission rules, forward ledger, research cells and generation blend is tested exactly at its edge and one step past it.
- **Formal cases (`aq test --formal`):** `test_formal_differential_<target>.py` runs each verified function on the inputs Lean 4 generated and compares exact outputs. `test_formal_cases_drift.py` fails when a spec changed after its cases were generated. No Lean install is needed.

## Before a commit

- `scripts/clean_checkout_test.ps1` runs CI's pytest in a detached worktree with no gitignored files. A test that reads `ml/model_weights.json` or a backtest folder passes locally and fails only on CI, so tests bring their artifacts in `tmp_path`.
- On a low-memory PC, `scripts/codespace_verify.ps1 -Start` runs every CI job on a Codespace. Never `aq test --parallel` there.
