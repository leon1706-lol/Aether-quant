"""A synthetic world for the model lab's tests: closes with a planted, learnable signal and a ready lab around them.

The planted signal: returns persist (each day's expected return is 0.9 of the last five days' mean), so the momentum
features predict `target_rank_20d` and a model that learns anything shows a positive out-of-sample IC. Small enough (8 tickers, 520
sessions) that the linear template trains in well under a second and a 2-epoch network in a few.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from lab import lab_dataset, model_templates, run_registry


def planted_closes(rows: int = 520, names: int = 8, seed: int = 11) -> pd.DataFrame:
    """Returns that persist: each day's expected return is most of the last five days' mean, so momentum predicts."""
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, 0.01, (rows, names))
    returns = np.zeros((rows, names))
    for day in range(rows):
        returns[day] = noise[day] + (0.9 * returns[max(0, day - 5):day].mean(axis=0) if day else 0.0)
    index = [str(day.date()) for day in pd.bdate_range("2020-01-02", periods=rows)]
    return pd.DataFrame(100 * np.exp(np.cumsum(returns, axis=0)), index=index, columns=[f"C{i}" for i in range(names)])


def make_lab(folder: Path, *, features: str = "example", models: dict[str, str] | None = None, epochs: int = 2) -> Path:
    """A lab at `folder` with data/dataset.csv built from the planted closes and the given {name: template} models."""
    run_registry.init_lab(folder)
    closes = planted_closes()
    closes.to_csv(folder / "data" / "closes.csv", index_label="date")
    lab_dataset.build_dataset(closes, features=features, targets=(5, 20)).to_csv(folder / "data" / "dataset.csv", index=False)
    for name, template in (models or {"lin": "linear"}).items():
        model_templates.new_model(folder, name, template)
        config = folder / "models" / name / "config.toml"
        text = config.read_text(encoding="utf-8").replace("epochs = 30", f"epochs = {epochs}").replace("batch_dates = 16", "batch_dates = 8")
        if template == "tcn":
            text = text.replace("window = 20", "window = 5").replace("channels = [32, 32]", "channels = [8]")
        if template in ("mlp", "multitask"):
            text = text.replace("hidden = [64, 32]", "hidden = [16]")
        config.write_text(text, encoding="utf-8")
    return folder
