# tests

Pytest suite for every non-`webui` module. The current count lives in the
root `README.md`'s badge (`aq test` keeps it in sync automatically — see
`aq_cli.py::cmd_test`), not hardcoded here since it changes too often to
keep two copies aligned.

Conventions (established since the first V2 test files and followed
throughout): one test file per source module (`tests/test_<module>.py`),
plain `def test_...():` functions — newer files (V5.3+) may group related
tests into `class TestX:` namespaces, still with no shared `conftest.py`;
each file carries its own module-level fixtures/helpers
(`_sample_x()` builders, `_make_conn_mock()` for Postgres-backed modules),
duplicated across files rather than centralized.

`_make_conn_mock()` (used by every Postgres IO-layer test, e.g.
`test_retraining_postgres_registry.py`, `test_postgres_triggers.py`,
`test_postgres_worker.py`) mocks a psycopg3 connection/cursor pair so DDL
and queries can be asserted on without a real database:

```python
def _make_conn_mock():
    conn_mock = MagicMock()
    cur_mock = MagicMock()
    conn_mock.cursor.return_value.__enter__.return_value = cur_mock
    conn_mock.cursor.return_value.__exit__.return_value = False
    return conn_mock, cur_mock
```

Worker classes (`PostgresWorker`, `TriggerWorker`, `RetrainingWorker`)
accept a `_pg_conn`/`_redis_client` constructor kwarg specifically so tests
can inject the mock above instead of opening a real connection.

**`main.py` against a Lean stub (V5.5.0):** `main.py` only imports inside a Lean
process, so it had no unit coverage at all. `tests/test_main_wiring.py` installs a
minimal `AlgorithmImports` (just `QCAlgorithm`), builds the algorithm with
`object.__new__` (skipping `initialize()`), sets only the attributes a method reads, and
drives the order-path methods (`_apply_signal`, `_try_submit_limit_order`,
`_open_order_quantity`, `_short_exposure`, exit tracking, slippage divergence, the
shutdown probe). It proves the decisions *this repo* makes around Lean's APIs - never
fill timing or API semantics (that stays the owner-run backtest's job), and it does
not drive `on_data()`; `tests/test_v550_parity_fixes.py` therefore also keeps a
structural guard that `main.py` still contains a real call to each fixed function.

**Repo-level guards (`aq test --meta`):** `test_ci_workflows.py` pins the CI shape (every
job, the subsystem matrix equal to `_SUBSYSTEM_TEST_FILES`, CPU torch ordering, pinned
tool versions), `test_packaging_modules.py` fails when a shipped file imports a
first-party module `pyproject.toml` does not ship, `test_docs_links.py` checks every
relative Markdown link and `AQ:*` marker pair, `test_ci_scripts.py` covers the CI
helper scripts.

**Run with an explicit path, never bare `pytest`:**

```powershell
pytest tests/
```

Per `development/Problems.md` #8: a bare `pytest` from the repo root also
crawls `backtests/<run>/code/tests/` (each Lean backtest run copies the
full algorithm source, tests included, into its own output folder), and
pytest's default import mode then collides on duplicate module names once
enough backtests have accumulated locally. This only bites locally
(`backtests/` is gitignored), never on a fresh clone or CI.
