# tests

The pytest suite for everything except `webui`. The count is on the root README's badge, which `aq test` refreshes.

**Run with an explicit path, never bare `pytest`:** `aq test`, or `pytest tests/`. A bare run crawls the code each Lean run copies into `backtests/` and collides on module names (#8).

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

- **`main.py` against a Lean stub:** `test_main_wiring.py` installs a minimal `AlgorithmImports`, builds the algorithm with `object.__new__` and drives the order-path methods. It proves this repo's decisions around Lean's APIs, not fill timing, and it doesn't drive `on_data()`. `test_main_ensure_ready_smoke.py` runs the real first-bar setup.
- **Repo guards (`aq test --meta`):**
  - `test_ci_workflows.py`: the CI shape.
  - `test_packaging_modules.py`: every shipped import is shipped.
  - `test_docs_links.py`: relative links and `AQ:*` marker pairs.
  - `test_docs_facts.py`: quoted numbers, the README's library example, and paths, config keys, commands and problem numbers in living docs.
  - `test_ci_scripts.py`: CI helper scripts.
  - `test_aether_quant_api.py`: the library's public surface, and that importing it loads nothing heavy.
- **Formal cases (`aq test --formal`):** `test_formal_differential_<target>.py` runs each verified function on the inputs Lean 4 generated and compares exact outputs. `test_formal_cases_drift.py` fails when a spec changed after its cases were generated. No Lean install is needed.

## Before a commit

- `scripts/clean_checkout_test.ps1` runs CI's pytest in a detached worktree with no gitignored files. A test that reads `ml/model_weights.json` or a backtest folder passes locally and fails only on CI, so tests bring their artifacts in `tmp_path`.
- On a low-memory PC, `scripts/codespace_verify.ps1 -Start` runs every CI job on a Codespace. Never `aq test --parallel` there.
