"""What a lab model uses and how stable it is: permutation importance per feature and group (`aq lab explain`), the IC
lost when a feature group is removed and the model retrained (`aq lab ablate`), and the spread of out-of-sample IC
across seeds (`aq lab seeds`).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from features import feature_registry
from lab import lab_dataset, run_registry, trainer
from lab.trainer import progress


def run_predictor(run_dir: Path, frame: pd.DataFrame) -> Callable[[pd.DataFrame], np.ndarray]:
    """A function scoring a dataset frame with the run's first seed's model of its last fold (what `explain` permutes)."""
    record = run_registry.read_run(run_dir)
    features = record["features"]
    seed = record["seeds"][0]
    if record["template"] == "linear":
        path = sorted(run_dir.glob(f"linear_*_seed_{seed}.json"))[-1]
        coefficients = np.asarray(json.loads(path.read_text(encoding="utf-8"))["coefficients"])
        return lambda data: trainer.predict_linear(lab_dataset.rank_features(data, features), coefficients)
    torch = trainer.require_torch()
    module = trainer.load_model_module(run_dir.parent.parent / "models" / record["model"])
    spec = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    head = trainer.head_of(record["target"])
    hparams = {key: value for key, value in spec["model"].items() if key not in {"template", "name"}}
    model = module.build(len(features), [head], **hparams)
    model.load_state_dict(torch.load(sorted(run_dir.glob(f"model_*_seed_{seed}.pt"))[-1], weights_only=True))
    window = int(spec["model"]["window"]) if record["template"] == "tcn" else None

    def predict(data: pd.DataFrame) -> np.ndarray:
        # the rows `data` holds (perhaps with a feature shuffled) inside the whole dataset, so a sequence window reaches back into
        # the rows before them exactly as in training
        full = frame.copy()
        full.loc[data.index, features] = data[features].to_numpy()
        ordered = full.sort_values(["ticker", "date"])
        x = lab_dataset.rank_features(ordered, features)
        windows = None
        if window is not None:
            from retraining.slicing import sequence_window_index

            windows = sequence_window_index(ordered["ticker"].to_numpy(), window)
        scores = trainer.predict_torch(model, x, np.arange(len(ordered)), windows, head)
        return pd.Series(scores, index=ordered.index).reindex(data.index).to_numpy()

    return predict


def explain_run(run_dir: Path, *, dataset: pd.DataFrame | None = None, seed: int = 7) -> dict[str, Any]:
    """Out-of-sample permutation importance (IC drop) per feature, summed per feature group, and each feature's own IC."""
    from evaluation.feature_quality_audit import permutation_ic_drop
    from lab.run_evaluation import daily_ic

    record = run_registry.read_run(run_dir)
    full = (dataset if dataset is not None else lab_dataset.load_dataset(Path(record["dataset"]))).reset_index(drop=True)
    frame = full[full["split"].isin(["validation", "backtest"])]
    features = record["features"]
    drops = permutation_ic_drop(frame, features, run_predictor(run_dir, full), target=record["target"], min_names=3, seed=seed)
    groups: dict[str, float] = {}
    for group, names in feature_registry.groups_of(features).items():
        values = [drops[name] for name in names if drops.get(name) is not None]
        groups[group] = float(np.sum(values)) if values else None
    own = {name: float(daily_ic(frame[name], frame[record["target"]], frame["date"]).mean()) for name in features}
    return {"run": run_dir.name, "importance": dict(sorted(drops.items(), key=lambda item: -(item[1] or 0.0))), "groups": groups, "feature_ic": own}


def ablate_run(lab_dir: Path, run_dir: Path, *, groups: Mapping[str, Sequence[str]] | None = None, train: Callable[..., dict] = trainer.train_run,
               log: Callable[[str], None] = progress) -> dict[str, Any]:
    """Retrain the run's model once per feature group with that group removed; the change in out-of-sample IC per group."""
    record = run_registry.read_run(run_dir)
    features = record["features"]
    groups = dict(groups or feature_registry.groups_of(features))
    base = (record.get("metrics") or {}).get("oof_ic_mean")
    rows = {}
    for group, names in groups.items():
        kept = [name for name in features if name not in set(names)]
        if not kept:
            rows[group] = {"removed": list(names), "oof_ic": None, "change": None, "note": "nothing left to train on"}
            continue
        log(f"without {group} ({', '.join(names)})")
        result = train(lab_dir, record["model"], overrides={"data": {"features": kept}}, seeds=record["seeds"], log=log)
        ic = (result.get("metrics") or {}).get("oof_ic_mean")
        rows[group] = {"removed": list(names), "run": result["id"], "oof_ic": ic, "change": None if ic is None or base is None else ic - base}
    return {"run": run_dir.name, "base_oof_ic": base, "groups": rows}


def seed_stability(lab_dir: Path, run_dir: Path, *, seeds: int, train: Callable[..., dict] = trainer.train_run, log: Callable[[str], None] = progress) -> dict[str, Any]:
    """Retrain with `seeds` seeds; the IC mean, spread and range, flagged unstable when the spread is over half the mean."""
    record = run_registry.read_run(run_dir)
    result = train(lab_dir, record["model"], seeds=list(range(1, seeds + 1)), log=log)
    per_seed = list(((result.get("metrics") or {}).get("per_seed_ic") or {}).values())
    values = np.asarray([value for value in per_seed if value is not None], dtype=float)
    mean = float(values.mean()) if len(values) else None
    spread = float(values.std(ddof=1)) if len(values) > 1 else None
    return {"run": result["id"], "seeds": seeds, "per_seed_ic": per_seed, "mean": mean, "std": spread,
            "range": [float(values.min()), float(values.max())] if len(values) else None,
            "unstable": bool(mean is not None and spread is not None and spread > abs(mean) / 2.0)}


def render_mapping(title: str, values: Mapping[str, Any], digits: int = 4) -> str:
    """A titled list of `name: value` lines in the mapping's order (floats signed, None as -)."""
    lines = [title]
    for key, value in values.items():
        lines.append(f"  {key}: {'-' if value is None else f'{value:+.{digits}f}' if isinstance(value, float) else value}")
    return "\n".join(lines)
