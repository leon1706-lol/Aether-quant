"""scripts/k09_decide.py: k09's weights for a session, from fundamentals filed before it, pooled by sector (V6.6.4)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import k09_decide as k09  # noqa: E402

DAYS = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2026-04-01", periods=130)]
SESSION = DAYS[-1]
TECH = [f"T{i}" for i in range(8)]
UTIL = [f"U{i}" for i in range(8)]
NAMES = TECH + UTIL
SECTORS = {**{name: "information_technology" for name in TECH}, **{name: "utilities" for name in UTIL}}


def _known() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    return pd.DataFrame(100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, (len(DAYS), len(NAMES))), axis=0)), index=DAYS, columns=NAMES)


def _extended(filed="2026-08-03", accruals=None) -> pd.DataFrame:
    """Quarterly rows: the higher a name's index, the more of its income is accruals rather than cash."""
    rows = []
    for position, name in enumerate(NAMES):
        gap = (accruals or {}).get(name, position % 8 * 10.0)
        for field, value in (("ttm_net_income", 100.0 + gap), ("ttm_operating_cash_flow", 100.0), ("assets_q", 1000.0)):
            rows.append({"ticker": name, "field": field, "period_end": "2026-06-30", "filed": filed, "form": "10-Q", "value": value})
    return pd.DataFrame(rows)


def _weights(extended=None):
    return k09.k09_weights(SESSION, _known(), _extended() if extended is None else extended, pd.DataFrame(columns=["ticker", "field", "period_end", "filed", "form", "value"]), NAMES, SECTORS)


def test_low_accruals_are_held_long_and_high_accruals_short_inside_each_sector():
    weights = _weights()
    assert weights, "a book is built from the quarterly filings"
    for group in (TECH, UTIL):
        assert weights.get(group[0], 0.0) > 0.0 > weights.get(group[-1], 0.0), "the name with the lowest accruals is long and the highest short"
    assert all(np.isfinite(value) and abs(value) <= 0.03 + 1e-9 for value in weights.values())
    assert sum(abs(value) for value in weights.values()) <= 1.4 + 1e-9


def test_a_filing_dated_after_the_session_changes_nothing():
    late = _extended(filed="2026-12-31")
    assert _weights(late) == {}, "a filing the session could not have seen builds no book"
    both = pd.concat([_extended(), _extended(filed="2026-12-31", accruals={name: 500.0 for name in NAMES})], ignore_index=True)
    assert _weights(both) == _weights()


def test_a_name_with_no_sector_or_no_price_is_not_ranked():
    sectors = {**SECTORS, "T0": "unknown"}
    weights = k09.k09_weights(SESSION, _known(), _extended(), pd.DataFrame(columns=["ticker", "field", "period_end", "filed", "form", "value"]), NAMES + ["GHOST"], sectors)
    assert "T0" not in weights and "GHOST" not in weights


def test_the_same_inputs_give_the_same_weights():
    assert _weights() == _weights()
