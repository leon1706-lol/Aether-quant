"""retraining/orchestrator.py (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

import pytest

from retraining import orchestrator


def test_connect_without_a_dsn_or_driver_fails_loudly(monkeypatch):
    monkeypatch.delenv("AETHER_POSTGRES_DSN", raising=False)
    with pytest.raises(Exception):
        orchestrator.connect("postgresql://nobody@127.0.0.1:1/none?connect_timeout=1")
