"""Round 4C's x13: a walk-forward gradient-boosted ranker over crypto features (V6.6.4).

Features are the cross-sectional ranks of x01-x08 and the c1, c2 tables; the label is the rank of the next 20 days' return. Refit each 1 January and 1 July on rows whose label ended before the
refit date, scored for the half-year after it, from 2019-01-01. Reads cell CS only. Writes `ml/evaluation/v664/scores/x13.csv` (`date,ticker,score`), which round 4C's x13 reads as a
`score_file`. Deterministic: fixed seeds, so two runs give identical bytes.

    python scripts/v664_crypto_gbm.py
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from portfolio import crypto_signals as cs  # noqa: E402

HORIZON = 20
FIRST_SCORED = "2019-01-01"
FEATURES = ("x01", "x02", "x03", "x04", "x05", "x06", "x07", "x08", "c1", "c2")
OUTPUT = ROOT / "ml" / "evaluation" / "v664" / "scores" / "x13.csv"
PARAMETERS = {"max_depth": 3, "learning_rate": 0.05, "max_iter": 200, "random_state": 0}


def feature_tables(known: pd.DataFrame, volume: pd.DataFrame, member: pd.DataFrame, c_tables: Mapping[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """The ten inputs as session x coin tables, ranked within each session among members."""
    raw = {
        "x01": cs.low_vol(known), "x02": cs.lottery_max(known), "x03": cs.amihud(known, volume), "x04": cs.volume_trend(volume.reindex(columns=known.columns)),
        "x05": cs.high_proximity(known), "x06": cs.short_reversal(known), "x07": cs.low_beta(known), "x08": cs.idio_vol(known), "c1": c_tables["c1"], "c2": c_tables["c2"],
    }
    return {name: table.where(member).rank(axis=1, pct=True) for name, table in raw.items()}


def label_rank(known: pd.DataFrame, member: pd.DataFrame, horizon: int = HORIZON) -> pd.DataFrame:
    """The rank of each coin's next-`horizon`-days return. A training label only; it is never a feature."""
    ahead = (known.shift(-horizon) / known - 1.0).replace([np.inf, -np.inf], np.nan)
    return ahead.where(member).rank(axis=1, pct=True)


def refit_dates(index: pd.Index, first: str = FIRST_SCORED) -> list[str]:
    """Each 1 January and 1 July from `first`, as the first session on or after it."""
    sessions = [str(day) for day in index]
    out = []
    for stamp in pd.date_range(first, sessions[-1], freq="6MS"):
        later = [day for day in sessions if day >= stamp.strftime("%Y-%m-%d")]
        if later:
            out.append(later[0])
    return out


def walk_forward(features: Mapping[str, pd.DataFrame], label: pd.DataFrame, index: pd.Index, *, horizon: int = HORIZON, fit=None) -> pd.DataFrame:
    """Scores for every session from the first refit, each half-year by a model fitted only on rows whose label had ended before that refit."""
    from sklearn.ensemble import HistGradientBoostingRegressor

    names = list(features)
    sessions = [str(day) for day in index]
    refits = refit_dates(index)
    scores = pd.DataFrame(np.nan, index=index, columns=label.columns)
    stack = np.stack([features[name].reindex(index=index, columns=label.columns).to_numpy(dtype=float) for name in names], axis=-1)
    for position, start in enumerate(refits):
        end = refits[position + 1] if position + 1 < len(refits) else None
        cut = sessions.index(start) - horizon  # the last row whose label ended before this refit
        if cut <= 0:
            continue
        rows = stack[:cut]
        target = label.to_numpy(dtype=float)[:cut]
        x, y = rows.reshape(-1, len(names)), target.reshape(-1)
        keep = np.isfinite(y) & np.isfinite(x).all(axis=1)
        if keep.sum() < 500:
            continue
        model = fit() if fit else HistGradientBoostingRegressor(**PARAMETERS)
        model.fit(x[keep], y[keep])
        first = sessions.index(start)
        last = sessions.index(end) if end else len(sessions)
        block = stack[first:last]
        flat = block.reshape(-1, len(names))
        ok = np.isfinite(flat).all(axis=1)
        predicted = np.full(len(flat), np.nan)
        if ok.any():
            predicted[ok] = model.predict(flat[ok])
        scores.iloc[first:last] = predicted.reshape(block.shape[0], block.shape[1])
    return scores


def main() -> int:
    from evaluation.research_cells import CELLS
    from evaluation.wide_context import crypto_cell

    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    cell = crypto_cell(ROOT, base, "CS")
    if cell.cell.name != "CS" or cell.cell.end != CELLS["CS"].end:
        raise SystemExit("x13 reads cell CS only")
    known = cell.context.panel.known
    features = feature_tables(known, cell.features["quote_volume"], cell.member, cell.tables)
    scores = walk_forward(features, label_rank(known, cell.member), known.index)
    scores = scores[scores.index <= cell.cell.end].where(cell.member)
    frame = scores.stack().rename("score").reset_index()
    frame.columns = ["date", "ticker", "score"]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUTPUT, index=False, lineterminator="\n", float_format="%.10g")
    print(f"wrote {OUTPUT}: {len(frame)} rows, {frame['date'].nunique()} sessions, refits {len(refit_dates(known.index))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
