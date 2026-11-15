"""evaluation/benchmark_comparison.py (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

from evaluation.benchmark_comparison import random_entry_baseline


def test_the_random_baseline_is_seeded():
    tickers = [f"T{i}" for i in range(14)]
    first = random_entry_baseline(tickers, n_days=60, top_n=3, bottom_n=3, seed=7)
    assert first == random_entry_baseline(tickers, n_days=60, top_n=3, bottom_n=3, seed=7)
    assert isinstance(first, dict) and first
