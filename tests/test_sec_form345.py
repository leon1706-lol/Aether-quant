"""data_pipeline/sec_form345.py (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

from data_pipeline.sec_form345 import quarters


def test_quarters_run_oldest_first_and_stop_at_the_end_quarter():
    assert quarters(2025, 2026, 2) == [(2025, 1), (2025, 2), (2025, 3), (2025, 4), (2026, 1), (2026, 2)]
    assert quarters(2026, 2026, 1) == [(2026, 1)]
