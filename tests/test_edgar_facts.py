"""data_pipeline/edgar_facts.py (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

from data_pipeline.edgar_facts import sector_for_sic


def test_a_sic_code_maps_to_a_sector_and_nonsense_to_a_fallback():
    assert isinstance(sector_for_sic(3571), str) and sector_for_sic(3571)
    assert sector_for_sic(3571) == sector_for_sic("3571")
    assert isinstance(sector_for_sic(None), str)
