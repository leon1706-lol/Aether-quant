"""evaluation/tranche_book.py (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

from evaluation.tranche_book import tranche_kwargs


def test_one_tranche_is_the_base_book_and_k_tranches_stagger_the_phase():
    base = {"top_n": 6, "bottom_n": 6, "gross_exposure": 1.0, "rebalance_every_bars": 20}
    out = tranche_kwargs(base, 1)
    assert len(out) == 1 and out[0]["top_n"] == 6 and out[0]["rebalance_counter_start"] == 0
    four = tranche_kwargs(base, 4)
    assert len(four) == 4 and len({sub["rebalance_counter_start"] for sub in four}) == 4
