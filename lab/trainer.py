"""`aq lab train`: fit a lab model on a dataset's train split, early-stop on validation, score every out-of-sample row,
and record the run, its scores, weights and pins, and one trial per seed in the lab's ledger.

The networks, losses and training mechanics are the production ones (`lab.architectures`, `lab.losses`,
`lab.training_utils`), so a lab model trains the way the shipped models do. The inputs are within-date percentile ranks,
which need no fitted scaler and so carry no scaler look-ahead. Sealed holdout rows never reach a fit or a score.

Folds: `split` trains on `train`, stops on `validation` and scores `validation` and `backtest`; `annual` retrains each
year on everything up to 21 days before it (an expanding walk-forward) and scores that year.
"""

from __future__ import annotations

import datetime as _datetime
import hashlib
import importlib.util
import json
import platform
import sys
import time
import types
import warnings
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from evaluation.rank_ic_core import rank_ic_from_arrays
from json_safety import atomic_write_json
from lab import lab_dataset, run_registry
from lab import spec as lab_spec

LEDGER = "trials.jsonl"
TRACK = "lab"


class TorchMissing(RuntimeError):
    """A neural template without torch installed."""



def progress(message: str) -> None:
    """Progress lines go to stderr, so a --json result on stdout stays parseable."""
    print(message, file=sys.stderr)

def head_of(target: str) -> str:
    """target_rank_20d -> rank_20d (the production head that predicts it)."""
    return target.removeprefix("target_")


def load_model_module(model_dir: Path) -> types.ModuleType:
    """The model's own `model.py` (its `build(n_features, heads, **hparams)`), imported from its file."""
    path = model_dir / "model.py"
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing: aq lab new {model_dir.name} --template ...")
    module_spec = importlib.util.spec_from_file_location(f"aq_lab_model_{model_dir.name}", path)
    module = importlib.util.module_from_spec(module_spec)
    try:
        module_spec.loader.exec_module(module)
    except ModuleNotFoundError as error:
        if error.name == "torch":
            require_torch()  # raises TorchMissing with the install line
        raise
    return module


def require_torch() -> types.ModuleType:
    """torch, or TorchMissing with the install line."""
    try:
        import torch
    except ImportError as error:
        raise TorchMissing('the neural templates need torch: pip install "aether-quant[train]" (the linear template runs without it)') from error
    return torch


# ---------------------------------------------------------------------------
# folds
# ---------------------------------------------------------------------------


def make_folds(frame: pd.DataFrame, kind: str) -> list[dict]:
    """[{name, fit: bool mask, stop: bool mask, score: bool mask}] over `frame`'s rows."""
    split = frame["split"].astype(str)
    if kind == "split":
        return [{"name": "split", "fit": (split == "train").to_numpy(), "stop": (split == "validation").to_numpy(),
                 "score": split.isin(["validation", "backtest"]).to_numpy()}]
    if kind != "annual":
        raise ValueError(f"folds must be split or annual, not {kind!r}")
    from features.training_splits import annual_windows

    dates = frame["date"].astype(str)
    years = sorted({date[:4] for date in dates})
    windows = annual_windows(sorted(set(dates)), first_test_year=int(years[1]) if len(years) > 1 else int(years[0]))
    folds = []
    for window in windows:
        fit = ((dates <= window["train_end"]) & (frame["split"].astype(str) != "purged")).to_numpy()
        score = ((dates >= window["test_start"]) & (dates <= window["test_end"])).to_numpy()
        if fit.sum() and score.sum():
            cut = np.quantile(np.flatnonzero(fit), 0.8).astype(int)
            stop = fit & (np.arange(len(frame)) > cut)
            folds.append({"name": window["test_start"][:4], "fit": fit & ~stop, "stop": stop, "score": score})
    if not folds:
        raise ValueError("annual folds need at least two calendar years of rows")
    return folds


# ---------------------------------------------------------------------------
# the linear template (numpy only)
# ---------------------------------------------------------------------------


def fit_linear(x: np.ndarray, y: np.ndarray, ridge: float) -> np.ndarray:
    """Ridge regression of `y` on `x` with an intercept (intercept unpenalised); returns [intercept, coefficients...]."""
    keep = np.isfinite(y)
    design = np.column_stack([np.ones(int(keep.sum())), x[keep]])
    penalty = np.eye(design.shape[1]) * float(ridge)
    penalty[0, 0] = 0.0
    return np.linalg.solve(design.T @ design + penalty, design.T @ y[keep])


def predict_linear(x: np.ndarray, coefficients: np.ndarray) -> np.ndarray:
    """A linear model's scores: its coefficients applied to the ranked inputs."""
    return coefficients[0] + x @ coefficients[1:]


# ---------------------------------------------------------------------------
# the torch templates
# ---------------------------------------------------------------------------


def model_outputs(output: Any, head: str) -> Any:
    """The tensor for `head` from a model's output: a dict's head, a tuple's first item, or the tensor itself."""
    if isinstance(output, dict):
        if head not in output:
            raise KeyError(f"the model has no {head!r} head (it has {', '.join(output)})")
        return output[head]
    if isinstance(output, (tuple, list)):
        return output[0]
    return output


def _inputs(x: np.ndarray, rows: np.ndarray, windows: np.ndarray | None):
    from retraining.slicing import gather_windows

    torch = require_torch()
    if windows is None:
        return torch.from_numpy(np.ascontiguousarray(x[rows]))
    return torch.from_numpy(gather_windows(x, windows[rows]))


def fit_torch(module: types.ModuleType, x: np.ndarray, y: np.ndarray, dates: np.ndarray, folds_fit: np.ndarray, folds_stop: np.ndarray, *, spec: Mapping[str, Any],
              seed: int, head: str, windows: np.ndarray | None, log: Callable[[str], None] = progress, checkpoint: Path | None = None) -> tuple[Any, list[dict[str, Any]]]:
    """Train `module.build(...)` on the fit rows with whole-date batches and the chosen ranking loss; keep the epoch with the best
    smoothed validation rank IC. Returns (model, history)."""
    torch = require_torch()
    from lab.losses import compute_cross_sectional_ranking_loss
    from lab.training_utils import (
        build_cross_sectional_date_batches,
        build_date_group_ids,
        build_lr_scheduler,
        build_optimizer,
        is_new_best_epoch,
        select_device,
        set_seed,
        smoothed_metric,
    )

    train, model_spec = spec["train"], spec["model"]
    set_seed(seed)
    device = select_device(train["device"])
    hparams = {key: value for key, value in model_spec.items() if key not in {"template", "name"}}
    model = module.build(x.shape[1], [head], **hparams).to(device)
    optimizer = build_optimizer(model, {"optimizer": train["optimizer"], "learning_rate": train["lr"], "weight_decay": train["weight_decay"]})
    scheduler = build_lr_scheduler(optimizer, {"lr_schedule": train["lr_schedule"]}, train["epochs"])
    fit_rows, stop_rows = np.flatnonzero(folds_fit & np.isfinite(y)), np.flatnonzero(folds_stop & np.isfinite(y))
    loss_config = {"objective": train["loss"], "temperature": train["temperature"]}
    history: list[dict] = []
    best_state, best_epoch, best_smoothed = None, -1, None
    start_epoch = 0
    if checkpoint is not None and checkpoint.exists():
        saved = torch.load(checkpoint, weights_only=False)
        model.load_state_dict(saved["model"])
        optimizer.load_state_dict(saved["optimizer"])
        history, best_state, best_epoch, start_epoch = saved["history"], saved["best_state"], saved["best_epoch"], saved["epoch"] + 1
        best_smoothed = saved["best_smoothed"]
    for epoch in range(start_epoch, train["epochs"]):
        model.train()
        batches = build_cross_sectional_date_batches(dates[fit_rows], batch_dates=train["batch_dates"], min_group_size=2, shuffle=True, seed=seed + epoch)
        losses = []
        for batch in batches:
            rows = fit_rows[batch]
            group_ids = torch.from_numpy(build_date_group_ids(dates[rows]).astype(np.int64)).to(device)
            prediction = model_outputs(model(_inputs(x, rows, windows).to(device)), head)
            loss = compute_cross_sectional_ranking_loss(prediction, torch.from_numpy(y[rows].astype(np.float32)).to(device), group_ids, loss_config)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach()))
        if scheduler is not None:
            scheduler.step()
        ic = rank_ic_from_arrays(predict_torch(model, x, stop_rows, windows, head), y[stop_rows], dates[stop_rows])["mean_ic"] if len(stop_rows) else None
        history.append({"epoch": epoch, "train_loss": float(np.mean(losses)) if losses else None, "validation_rank_ic": ic})
        smoothed = smoothed_metric(history, "validation_rank_ic", train["early_stop_smoothing_epochs"])
        history[-1]["smoothed"] = smoothed
        improved = smoothed is not None and (best_smoothed is None or is_new_best_epoch(smoothed, best_smoothed, epoch, train["min_best_epoch"]))
        if best_state is None or improved or smoothed is None:  # without validation rows the last epoch is kept
            best_state = {key: value.detach().clone() for key, value in model.state_dict().items()}
            best_epoch, best_smoothed = epoch, smoothed if improved else best_smoothed
        log(f"  epoch {epoch + 1}/{train['epochs']}: loss {history[-1]['train_loss']:.4f}, validation rank IC " + ("-" if ic is None else f"{ic:+.4f}"))
        if checkpoint is not None:
            torch.save({"model": model.state_dict(), "optimizer": optimizer.state_dict(), "history": history, "best_state": best_state,
                        "best_epoch": best_epoch, "best_smoothed": best_smoothed, "epoch": epoch}, checkpoint)
        if epoch - best_epoch >= train["patience"]:
            log(f"  early stop: no better validation IC for {train['patience']} epochs (best epoch {best_epoch + 1})")
            break
    model.load_state_dict(best_state)
    return model, history


def predict_torch(model: Any, x: np.ndarray, rows: np.ndarray, windows: np.ndarray | None, head: str, chunk: int = 4096) -> np.ndarray:
    """A network's scores for the given rows (with their windows for a sequence model), in batches, without gradients."""
    torch = require_torch()
    device = next(model.parameters()).device
    model.eval()
    out = []
    with torch.no_grad():
        for start in range(0, len(rows), chunk):
            out.append(model_outputs(model(_inputs(x, rows[start:start + chunk], windows).to(device)), head).float().cpu().numpy().reshape(-1))
    return np.concatenate(out) if out else np.array([], dtype=np.float32)


# ---------------------------------------------------------------------------
# one run
# ---------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    """A file's sha256 hex digest."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def spread_sharpe(scores: pd.Series, frame: pd.DataFrame, *, quantile: float = 0.2) -> tuple[float | None, int]:
    """The annualised Sharpe of a daily top-minus-bottom quintile book on `target_return_1d` (252 sessions, 365 if weekends
    trade), and its number of days: the series a trial is counted by."""
    data = frame.assign(_score=scores.to_numpy()).dropna(subset=["_score", "target_return_1d"])
    daily = []
    for _, group in data.groupby("date"):
        if len(group) < 4:
            continue
        ranked = group["_score"].rank(pct=True)
        daily.append(group.loc[ranked > 1 - quantile, "target_return_1d"].mean() - group.loc[ranked <= quantile, "target_return_1d"].mean())
    series = np.asarray(daily, dtype=float)
    if len(series) < 2 or float(series.std(ddof=1)) == 0.0:
        return None, int(len(series))
    weekends = pd.to_datetime(data["date"].unique()).day_of_week.max() >= 5
    return float(series.mean() / series.std(ddof=1) * np.sqrt(365.0 if weekends else 252.0)), int(len(series))


def ledger_count(lab_dir: Path, project_ledger: Path | None = None) -> int:
    """N: every candidate trial in the lab's ledger (and the project's, when the run is filed there)."""
    from evaluation.trial_ledger import candidate_ids, read_ledger

    ids = set()
    for path in [lab_dir / LEDGER, *( [project_ledger] if project_ledger else [])]:
        if path.exists():
            ids |= candidate_ids(read_ledger(path))
    return len(ids)


def train_run(lab_dir: Path, model_name: str, *, overrides: Mapping[str, Any] | None = None, seeds: Sequence[int] | None = None, folds: str = "split",
              resume: str | None = None, dry_run: bool = False, project_ledger: Path | None = None, project_config: Path | None = None,
              log: Callable[[str], None] = progress) -> dict[str, Any]:
    """Train one lab model for each seed and record the run; returns its run.json record."""
    from retraining import run_resume

    model_dir = lab_dir / "models" / model_name
    if not model_dir.is_dir():
        raise FileNotFoundError(f"no model {model_name!r} in {lab_dir / 'models'}: aq lab new {model_name} --template multitask")
    spec = lab_spec.load_spec(model_dir, lab_dir=lab_dir, overrides=overrides)
    if seeds:
        spec["train"]["seeds"] = list(seeds)
    dataset_path = Path(spec["data"]["dataset"])
    dataset_path = dataset_path if dataset_path.is_absolute() else lab_dir / dataset_path
    if not dataset_path.exists():
        raise FileNotFoundError(f"no dataset at {dataset_path}: aq dataset build --prices closes.csv --out {dataset_path}")
    frame = lab_dataset.load_dataset(dataset_path, project_config=project_config).sort_values(["ticker", "date"]).reset_index(drop=True)
    target = spec["data"]["target"]
    if target not in frame.columns:
        raise ValueError(f"the dataset has no {target} column (it has {', '.join(lab_dataset.target_columns(frame))})")
    features = lab_dataset.feature_columns(frame) if spec["data"]["features"] == "all" else [name for name in spec["data"]["features"] if name in frame.columns]
    template = spec["model"]["template"]
    plan = {"model": model_name, "template": template, "dataset": str(dataset_path), "rows": len(frame), "features": features, "target": target,
            "loss": spec["train"]["loss"], "seeds": spec["train"]["seeds"], "folds": folds}
    if dry_run:
        return {"dry_run": True, **plan}
    module = None if template == "linear" else load_model_module(model_dir)
    if module is not None:
        require_torch()
    runs_root = lab_dir / "runs"
    if resume:
        run_dir = run_resume.find_resumable(runs_root, "", None if resume == "latest" else resume)
        if run_dir is None:
            raise FileNotFoundError("no stopped lab run to resume (aq lab runs)")
    else:
        run_dir = runs_root / run_registry.new_run_id(model_name)
        run_resume.start_record(run_dir, {"settings": {"model": model_name, "seeds": spec["train"]["seeds"], "folds": folds, "overrides": dict(overrides or {})}})
    started = time.time()
    run_registry.write_run(run_dir, {**plan, "status": "running", "started": _datetime.datetime.now(_datetime.timezone.utc).isoformat(timespec="seconds")})
    atomic_write_json(run_dir / "config.json", spec, indent=2)
    x = lab_dataset.rank_features(frame, features)
    y = frame[target].to_numpy(dtype=float)
    dates = frame["date"].astype(str).to_numpy()
    windows = None
    if template == "tcn":
        from retraining.slicing import sequence_window_index

        windows = sequence_window_index(frame["ticker"].to_numpy(), int(spec["model"]["window"]))
    fold_list = make_folds(frame, folds)
    head = head_of(target)
    done = set(run_resume.done_steps(run_dir))
    seed_scores: dict[int, np.ndarray] = {}
    fold_metrics: list[dict] = []
    for seed in spec["train"]["seeds"]:
        step = f"seed_{seed}"
        scores_path = run_dir / f"scores_seed_{seed}.npy"
        if step in done and scores_path.exists():
            seed_scores[seed] = np.load(scores_path)
            log(f"seed {seed}: done earlier, loaded")
            continue
        log(f"seed {seed}: {template} on {len(features)} features, {len(fold_list)} fold(s)")
        scores = np.full(len(frame), np.nan)
        for fold in fold_list:
            if template == "linear":
                coefficients = fit_linear(x[fold["fit"]], y[fold["fit"]], float(spec["model"]["ridge"]))
                scores[fold["score"]] = predict_linear(x[fold["score"]], coefficients)
                atomic_write_json(run_dir / f"linear_{fold['name']}_seed_{seed}.json", {"features": features, "coefficients": coefficients.tolist(), "target": target})
                history = []
            else:
                torch = require_torch()
                model, history = fit_torch(module, x, y, dates, fold["fit"], fold["stop"], spec=spec, seed=seed, head=head, windows=windows, log=log,
                                           checkpoint=run_dir / f"checkpoint_{fold['name']}_seed_{seed}.pt")
                rows = np.flatnonzero(fold["score"])
                scores[rows] = predict_torch(model, x, rows, windows, head)
                torch.save(model.state_dict(), run_dir / f"model_{fold['name']}_seed_{seed}.pt")
            score_rows = np.flatnonzero(fold["score"])
            ic = rank_ic_from_arrays(scores[score_rows], y[score_rows], dates[score_rows])
            fold_metrics.append({"seed": seed, "fold": fold["name"], "oof_ic": ic["mean_ic"], "t_stat": ic["t_stat"], "dates": ic["num_dates"],
                                 "epochs": len(history), "best_validation_ic": max((row["validation_rank_ic"] for row in history if row["validation_rank_ic"] is not None), default=None)})
        np.save(scores_path, scores)
        seed_scores[seed] = scores
        sharpe, n_obs = spread_sharpe(pd.Series(scores), frame)
        from evaluation.trial_ledger import append_trial

        for ledger in [lab_dir / LEDGER, *([project_ledger] if project_ledger else [])]:
            append_trial(ledger, trial_id=f"{run_dir.name}:seed_{seed}", track=TRACK, window="lab_oof", role="candidate",
                         annualised_sharpe=sharpe if sharpe is not None else 0.0, n_obs=n_obs, config_sha=hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16],
                         engine="aq lab train", detail={"model": model_name, "template": template, "seed": seed})
        run_resume.mark_done(run_dir, step, {"sharpe": sharpe})
    with warnings.catch_warnings():  # a row no fold scored (purged, train-only) stays NaN without a warning
        warnings.simplefilter("ignore", RuntimeWarning)
        mean_scores = np.nanmean(np.vstack(list(seed_scores.values())), axis=0) if seed_scores else np.array([])
    out = frame[["date", "ticker", "split"]].assign(**{f"score_{head}": mean_scores})
    out = out[np.isfinite(mean_scores)]
    out.to_csv(run_dir / "scores.csv", index=False)
    per_seed = [rank_ic_from_arrays(scores[np.isfinite(scores)], y[np.isfinite(scores)], dates[np.isfinite(scores)])["mean_ic"] for scores in seed_scores.values()]
    metrics = {"oof_ic_mean": float(np.mean(per_seed)) if per_seed else None, "oof_ic_seed_std": float(np.std(per_seed)) if len(per_seed) > 1 else None,
               "per_seed_ic": dict(zip([str(seed) for seed in seed_scores], per_seed, strict=False)), "folds": fold_metrics}
    pins = {path.name: sha256_file(path) for path in sorted(run_dir.glob("*")) if path.suffix in {".pt", ".json", ".csv", ".npy"} and path.name != "run.json"}
    record = run_registry.write_run(run_dir, {
        "status": "finished", "metrics": metrics, "trials_n": ledger_count(lab_dir, project_ledger), "duration_s": round(time.time() - started, 1),
        "pins": pins, "environment": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
                                      "torch": sys.modules["torch"].__version__ if "torch" in sys.modules else None},
    })
    run_resume.mark_done(run_dir, "report", None)
    run_resume.update_record(run_dir, finished=True)
    return {"id": run_dir.name, **record}
