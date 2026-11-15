"""data_pipeline/factor_library.py (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

import pytest

from data_pipeline.factor_library import fetch_factors


def test_a_download_that_fails_is_not_hidden():
    def broken(url: str) -> bytes:
        raise OSError("offline")

    with pytest.raises(Exception):
        fetch_factors(broken)
