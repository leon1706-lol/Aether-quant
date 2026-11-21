"""`aq lab sweep`: a grid or random search over a model's settings, every point a full `aq lab train` run counted in the
ledger (a failed point counts too), judged together by the probability of backtest overfitting across the sweep.
"""

from __future__ import annotations

import itertools
import json
import random
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from json_safety import atomic_write_json
from lab.trainer import progress


def parse_grid(text: str) -> dict[str, list[Any]]:
    """'train.lr=1e-3,3e-4 model.hidden=[64],[128]' -> {'train.lr': [0.001, 0.0003], 'model.hidden': [[64], [128]]}.
    A bare key without a section goes to train (lr) or model (hidden, dropout, channels, kernel_size, window, ridge)."""
    model_keys = {"hidden", "dropout", "channels", "kernel_size", "window", "ridge"}
    grid: dict[str, list[Any]] = {}
    for part in text.split():
        key, _, raw = part.partition("=")
        if not key or not raw:
            raise ValueError(f"bad grid item {part!r}: write key=v1,v2")
        if "." not in key:
            key = f"{'model' if key in model_keys else 'train'}.{key}"
        values = []
        depth, current = 0, ""
        for char in raw:
            depth += char == "["
            depth -= char == "]"
            if char == "," and depth == 0:
                values.append(current)
                current = ""
            else:
                current += char
        values.append(current)
        parsed = []
        for value in values:
            try:
                parsed.append(json.loads(value))
            except ValueError:
                parsed.append(value)
        grid[key] = parsed
    if not grid:
        raise ValueError("the grid is empty")
    return grid


def grid_points(grid: Mapping[str, Sequence[Any]], *, random_k: int | None = None, seed: int = 7) -> list[dict[str, Any]]:
    """Every combination, or `random_k` of them drawn without replacement."""
    keys = list(grid)
    points = [dict(zip(keys, values, strict=False)) for values in itertools.product(*(grid[key] for key in keys))]
    if random_k is not None and random_k < len(points):
        points = random.Random(seed).sample(points, random_k)
    return points


def as_overrides(point: Mapping[str, Any]) -> dict[str, Any]:
    """A grid point's dotted keys as the nested override a run takes."""
    out: dict[str, Any] = {}
    for dotted, value in point.items():
        node = out
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return out


def _record_failed_trial(lab_dir: Path, model: str, point: Mapping[str, Any], error: BaseException) -> None:
    """A point that failed counts toward N like one that finished (Sharpe 0, no observations): a search is judged by all it tried."""
    from evaluation.trial_ledger import append_trial
    from lab.trainer import LEDGER, TRACK

    append_trial(lab_dir / LEDGER, trial_id=f"sweep_{model}:{json.dumps(dict(point), sort_keys=True)}", track=TRACK, window="lab_oof", role="candidate",
                 annualised_sharpe=0.0, n_obs=0, engine="aq lab sweep", detail={"model": model, "point": dict(point), "failed": str(error)[:200]})


def run_sweep(lab_dir: Path, model: str, grid: Mapping[str, Sequence[Any]], *, train: Callable[..., dict], random_k: int | None = None, seed: int = 7,
              max_trials: int | None = None, trials_now: int = 0, log: Callable[[str], None] = progress) -> dict[str, Any]:
    """Train every grid point (skipping points a resumed sweep already has), then compute the sweep's PBO."""
    points = grid_points(grid, random_k=random_k, seed=seed)
    if max_trials is not None and max_trials > 0 and trials_now + len(points) > max_trials:
        raise ValueError(f"{len(points)} points would take N from {trials_now} past --max-trials {max_trials}")
    state_path = lab_dir / "runs" / f"sweep_{model}.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"model": model, "points": []}
    seen = {json.dumps(item["point"], sort_keys=True) for item in state["points"]}
    for index, point in enumerate(points):
        key = json.dumps(point, sort_keys=True)
        if key in seen:
            log(f"point {index + 1}/{len(points)} {point}: done earlier")
            continue
        log(f"point {index + 1}/{len(points)} {point}")
        try:
            record = train(lab_dir, model, overrides=as_overrides(point), log=log)
            state["points"].append({"point": point, "run": record["id"], "status": "finished", "oof_ic": (record.get("metrics") or {}).get("oof_ic_mean")})
        except Exception as error:  # a failed point is still a trial: recorded in the ledger, never retried silently
            state["points"].append({"point": point, "run": None, "status": f"failed: {error}", "oof_ic": None})
            _record_failed_trial(lab_dir, model, point, error)
        atomic_write_json(state_path, state, indent=2)
    state["pbo"] = sweep_pbo(lab_dir, [item["run"] for item in state["points"] if item["run"]])
    finished = [item for item in state["points"] if item["oof_ic"] is not None]
    state["best"] = max(finished, key=lambda item: item["oof_ic"]) if finished else None
    atomic_write_json(state_path, state, indent=2)
    return state


def sweep_pbo(lab_dir: Path, runs: Sequence[str]) -> dict | None:
    """PBO (CSCV) over the runs' daily quintile-book returns, aligned on their common dates."""
    from evaluation.pbo import probability_of_backtest_overfitting
    from lab.run_evaluation import load_run_frame, spread_returns

    series = {}
    for run in runs:
        frame, column, _ = load_run_frame(lab_dir / "runs" / run)
        series[run] = spread_returns(frame, column)
    if len(series) < 2:
        return None
    matrix = pd.concat(series, axis=1, join="inner").dropna()
    if len(matrix) < 32:
        return {"value": None, "reason": f"only {len(matrix)} common days; PBO needs at least 32"}
    blocks = 16 if len(matrix) >= 64 else 8
    result = probability_of_backtest_overfitting(matrix.to_numpy(dtype=float), blocks=blocks)
    return {"value": result.get("pbo"), "combinations": result.get("num_combinations"), "trials": result.get("num_trials"), "days": len(matrix), "blocks": blocks}
