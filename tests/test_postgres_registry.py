"""retraining/postgres_registry.py (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

from retraining.postgres_registry import model_version_to_row


def test_a_version_becomes_insert_parameters():
    row = model_version_to_row({"model_version_id": "v1", "status": "candidate"})
    assert isinstance(row, dict) and row.get("model_version_id") == "v1"
