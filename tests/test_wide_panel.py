"""features/wide_panel.py (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

import pandas as pd

from features.wide_panel import growth_rows


def test_growth_needs_a_year_before():
    rows = pd.DataFrame({"ticker": [], "fiscal_year": [], "field": [], "value": [], "filed": []})
    out = growth_rows(rows, "revenue", "revenue_growth")
    assert isinstance(out, pd.DataFrame) and out.empty
