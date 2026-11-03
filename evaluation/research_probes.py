"""Research probes (V6.4.3): small cross-sectional models fitted in-process to measure what the dataset supports. They
are evaluation tools, never installed (no artifact is written to ml/).

`load_research_frame` reads only the needed columns in chunks as float32 (the 254-column dataset is ~0.5 GB resident on
the 4 GB dev PC otherwise); `fit_ridge_rank` is a closed-form ridge on per-date ranked features; `fit_hgb_rank` wraps
sklearn's HistGradientBoostingRegressor (imported only when called).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

KEY_COLUMNS = ("date", "ticker", "split")


def load_research_frame(dataset_path, *, columns, splits=None, chunksize: int = 40_000) -> pd.DataFrame:
    """The dataset's KEY_COLUMNS plus `columns` (numeric ones as float32), optionally only some splits."""
    wanted = list(dict.fromkeys([*KEY_COLUMNS, *columns]))
    header = pd.read_csv(Path(dataset_path), nrows=0).columns
    usecols = [column for column in wanted if column in header]
    parts = []
    for chunk in pd.read_csv(Path(dataset_path), usecols=usecols, chunksize=chunksize, low_memory=False):
        if splits is not None:
            chunk = chunk[chunk["split"].isin(list(splits))]
        numeric = [c for c in chunk.columns if c not in KEY_COLUMNS and pd.api.types.is_numeric_dtype(chunk[c])]
        chunk[numeric] = chunk[numeric].astype(np.float32)
        parts.append(chunk)
    frame = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=usecols)
    frame["date"] = frame["date"].astype(str).str[:10]
    return frame


def fit_ridge_rank(x_train: np.ndarray, y_train: np.ndarray, *, alpha: float = 10.0, features=None) -> dict:
    """Ridge on centred targets: coef = (X'X + alpha I)^-1 X'(y - mean y). Rows with any NaN are dropped."""
    x = np.asarray(x_train, dtype=np.float64)
    y = np.asarray(y_train, dtype=np.float64)
    keep = np.isfinite(x).all(axis=1) & np.isfinite(y)
    x, y = x[keep], y[keep]
    intercept = float(y.mean()) if len(y) else 0.0
    gram = x.T @ x + alpha * np.eye(x.shape[1])
    coef = np.linalg.solve(gram, x.T @ (y - intercept)) if len(y) else np.zeros(x.shape[1])
    return {"kind": "ridge", "coef": coef, "intercept": intercept, "alpha": float(alpha), "features": list(features or []),
            "rows": int(len(y))}


def fit_hgb_rank(x_train: np.ndarray, y_train: np.ndarray, **params):
    from sklearn.ensemble import HistGradientBoostingRegressor

    y = np.asarray(y_train, dtype=np.float64)
    keep = np.isfinite(y)
    model = HistGradientBoostingRegressor(**params)
    model.fit(np.asarray(x_train, dtype=np.float32)[keep], y[keep])
    return model


def predict_scores(model, x: np.ndarray) -> np.ndarray:
    """Scores for every row; a ridge row with a NaN feature scores NaN (the model has no view on it)."""
    x = np.asarray(x, dtype=np.float64)
    if isinstance(model, dict) and model.get("kind") == "ridge":
        scores = x @ model["coef"] + model["intercept"]
        scores[~np.isfinite(x).all(axis=1)] = np.nan
        return scores
    return np.asarray(model.predict(x.astype(np.float32)), dtype=np.float64)
