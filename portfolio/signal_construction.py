"""Signal tables built from other signal tables (V6.6.1): the recipes a research round names, and a cross-sectional residual.

Each works on tables of session x ticker known at that session's close, row by row, so a row depends on nothing later. Nothing here is fitted
across dates: a recipe's signs and parts are fixed in the round's rule file before any score.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from portfolio.wide_signals import rank_mean

MIN_RESIDUAL_NAMES = 30


def residualise_signal(table: pd.DataFrame, exposures: Mapping[str, pd.DataFrame], sectors: Mapping[str, str]) -> pd.DataFrame:
    """Per date, what is left of the signal's rank after an OLS on the ranked exposures and sector dummies. A name missing an exposure gets
    NaN; a date with too few names is all NaN, never an unadjusted signal."""
    columns = list(table.columns)
    sector_names = sorted({sectors.get(ticker) for ticker in columns if sectors.get(ticker) not in (None, "unknown")})
    sector_of = np.array([sectors.get(ticker) for ticker in columns], dtype=object)
    ranked = [frame.reindex(index=table.index, columns=columns).rank(axis=1, pct=True).to_numpy(dtype=float) for _, frame in sorted(exposures.items())]
    signal = table.rank(axis=1, pct=True).to_numpy(dtype=float)
    out = np.full(signal.shape, np.nan)
    for row in range(signal.shape[0]):
        keep = np.isfinite(signal[row])
        for exposure in ranked:
            keep &= np.isfinite(exposure[row])
        keep &= np.array([name in sector_names for name in sector_of])
        if keep.sum() < MIN_RESIDUAL_NAMES:
            continue
        design = [exposure[row, keep] - 0.5 for exposure in ranked]
        design += [(sector_of[keep] == name).astype(float) for name in sector_names]
        matrix = np.column_stack(design)
        beta, *_ = np.linalg.lstsq(matrix, signal[row, keep], rcond=None)
        out[row, keep] = signal[row, keep] - matrix @ beta
    return pd.DataFrame(out, index=table.index, columns=table.columns)


def build_table(recipe: Mapping, tables: Mapping[str, pd.DataFrame], member: pd.DataFrame | None = None, *, sectors: Mapping[str, str] | None = None) -> pd.DataFrame:
    """One trial's table from a recipe in its round file: {"op": "single" | "rank_mean" | "residualise", "parts": [names], "signs": {name: -1.0},
    "minimum": n, "exposures": [names]}. A missing part is an error: a trial must not quietly become a different trial."""
    op = str(recipe["op"])
    parts = [str(name) for name in recipe["parts"]]
    missing = [name for name in parts if name not in tables]
    if missing:
        raise KeyError(f"recipe needs {missing}, which the cell does not hold")
    signs = recipe.get("signs") or {}
    frames = [tables[name] * float(signs.get(name, 1.0)) for name in parts]
    if op == "single":
        if len(frames) != 1:
            raise ValueError("a single recipe has one part")
        table = frames[0]
    elif op == "rank_mean":
        table = rank_mean(frames, minimum=int(recipe.get("minimum", len(frames))))
    elif op == "residualise":
        names = [str(name) for name in recipe.get("exposures") or ()]
        unknown = [name for name in names if name not in tables]
        if unknown:
            raise KeyError(f"recipe needs exposures {unknown}, which the cell does not hold")
        base = frames[0] if len(frames) == 1 else rank_mean(frames, minimum=int(recipe.get("minimum", len(frames))))
        table = residualise_signal(base, {name: tables[name] for name in names}, sectors or {})
    else:
        raise ValueError(f"unknown recipe op {op!r}")
    if member is None:
        return table
    return table.where(member.reindex(index=table.index, columns=table.columns, fill_value=False))
