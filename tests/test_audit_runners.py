"""evaluation/audit_runners.py (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

from evaluation.audit_runners import live_consumers


def test_an_empty_config_has_no_live_consumer_beyond_the_defaults():
    assert isinstance(live_consumers({}), set)
