"""retraining/worker.py (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

from retraining.worker import RetrainingWorker


class _Cursor:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *args, **kwargs):
        return None

    def fetchall(self):
        return []

    def fetchone(self):
        return None


class _Conn:
    def cursor(self, *args, **kwargs):
        return _Cursor()

    def commit(self):
        return None


def test_a_worker_starts_on_an_injected_connection():
    worker = RetrainingWorker(config={}, poll_interval=17, _pg_conn=_Conn())
    assert worker is not None
