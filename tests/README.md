# tests

Pytest suite for every non-`webui` module. 528 tests as of the README
flagship-rewrite pass (`aq test` keeps the count badge in the root
`README.md` in sync automatically — see `aq_cli.py::cmd_test`).

Conventions (established since the first V2 test files and followed
throughout): one test file per source module (`tests/test_<module>.py`),
no test classes — plain `def test_...():` functions — and no shared
`conftest.py`; each file carries its own module-level fixtures/helpers
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
