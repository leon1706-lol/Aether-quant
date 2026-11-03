"""Per-date cross-sectional rank normalisation (V6.4.3): a feature's level across assets is mostly asset identity, its
rank on the day is the comparable part. Pure pandas, no I/O."""

from __future__ import annotations

import pandas as pd


def cross_sectional_rank(frame: pd.DataFrame, columns, *, date_column: str = "date", group_column: str | None = None) -> pd.DataFrame:
    """Percentile rank of each of `columns` within its date (and `group_column`, e.g. the asset class, when given),
    centred to [-0.5, 0.5]. NaN stays NaN; ties get the average rank. Same index as `frame`."""
    columns = list(columns)
    if frame.empty or not columns:
        return pd.DataFrame(index=frame.index, columns=columns, dtype=float)
    keys = [date_column] + ([group_column] if group_column else [])
    return frame.groupby(keys, sort=False)[columns].rank(pct=True) - 0.5
