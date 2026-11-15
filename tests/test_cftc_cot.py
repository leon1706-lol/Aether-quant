"""data_pipeline/cftc_cot.py (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

from data_pipeline.cftc_cot import parse_annual_text


def test_an_empty_or_unrelated_file_has_no_rows():
    assert parse_annual_text("") == []
