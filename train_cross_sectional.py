"""The new-architecture track of V6.5.0: rank models that see the whole cross-section of a date, walked forward by year.

The installed MLP and TCN score each asset alone. A set transformer reads all of a date's assets at once, so an asset's
score can depend on the others; a gradient-boosted ranker is the non-neural comparison. Both read within-class ranks of the
scaled features (a rank is unchanged by a scaler fitted on later data, so a window needs no scaler of its own) and
learn the 20-day sector-neutral rank centred per (date, class), so knowing an asset's group earns nothing (Problems.md #259).

    python train_cross_sectional.py --dataset ml/datasets/full_dataset.csv --model set_transformer --variant a \\
        --seeds 1,2,3 --out ml/evaluation/v650/scores/t5_st_a.csv --score-end 2023-06-30

`--score-end` is the guard of the selection window: nothing later is written to the score file.

V6.6.0 adds the wide universe. `--panel` reads `scripts/v660_build_panel.py`'s parquet of one side's names, so a rank or a label can't
see the other side, and `--score-panel` scores another panel (the held-out side) with the same yearly models. `mlp_multitask` is the
installed model's own network family, on its rank head.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd

LOGGER = logging.getLogger("train_cross_sectional")
TARGET = "target_sector_neutral_rank_20d"
PURGE_DAYS = 20
EARLY_STOP_GAP_SESSIONS = 22
FIRST_TEST_YEAR = 2019
SET_TRANSFORMER_VARIANTS = {"a": {"d": 32, "layers": 2, "heads": 2, "dropout": 0.3}, "b": {"d": 64, "layers": 2, "heads": 4, "dropout": 0.4}}
GBM_VARIANTS = {"a": {"max_depth": 3, "learning_rate": 0.03, "max_iter": 300}, "b": {"max_depth": 5, "learning_rate": 0.02, "max_iter": 400}}


def annual_windows(dates: list[str], *, first_test_year: int = FIRST_TEST_YEAR, purge_days: int = PURGE_DAYS) -> list[dict]:
    """Expanding windows: each test year is scored by a model trained on everything up to `purge_days` before it, since a
    20-day label of a row closer than that is still open on the test year's first day."""
    last_year = int(max(dates)[:4])
    windows = []
    for year in range(first_test_year, last_year + 1):
        test_start = f"{year}-01-01"
        train_end = (pd.Timestamp(test_start) - pd.Timedelta(days=purge_days + 1)).strftime("%Y-%m-%d")
        if any(date <= train_end for date in dates):
            windows.append({"train_end": train_end, "test_start": test_start, "test_end": f"{year}-12-31"})
    return windows


def rank_inputs(frame: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    """Within-(date, class) percentile rank minus one half; a missing value reads as the middle of its group."""
    grouped = frame.groupby(["date", "_class"], sort=False)
    ranked = grouped[features].rank(pct=True) - 0.5
    return ranked.fillna(0.0).astype("float32")


def centred_label(frame: pd.DataFrame, target: str = TARGET) -> pd.Series:
    return (frame[target] - frame.groupby(["date", "_class"], sort=False)[target].transform("mean")).astype("float32")


def load_frame(dataset: Path, config: dict, schema: dict) -> tuple[pd.DataFrame, list[str]]:
    from features.cross_sectional_inputs import asset_class_by_ticker

    features = [name for name in schema["scaled_feature_names"]]
    usecols = ["date", "ticker", TARGET, *features]
    frame = pd.read_csv(dataset, usecols=usecols, dtype={name: "float32" for name in [TARGET, *features]})
    frame["date"] = frame["date"].astype(str).str[:10]
    classes = asset_class_by_ticker(config)
    frame["_class"] = frame["ticker"].astype(str).map(lambda ticker: classes.get(ticker, "unknown"))
    frame[features] = rank_inputs(frame, features)
    frame["_label"] = centred_label(frame)
    return frame.sort_values(["date", "ticker"]).reset_index(drop=True), features


def fit_predict_gbm(train: pd.DataFrame, test: pd.DataFrame, features: list[str], variant: str, seed: int) -> np.ndarray:
    from evaluation.research_probes import fit_hgb_rank, predict_scores

    usable = train[train["_label"].notna()]
    model = fit_hgb_rank(
        usable[features].to_numpy(np.float32), usable["_label"].to_numpy(np.float64),
        min_samples_leaf=200, l2_regularization=1.0, random_state=seed, **GBM_VARIANTS[variant],
    )
    return predict_scores(model, test[features].to_numpy(np.float64))


def _set_ranker(num_features: int, num_classes: int, spec: dict):
    import torch
    from torch import nn

    class SetRanker(nn.Module):
        """Self-attention over one date's assets. No positional encoding: the assets are a set, so the score of an asset
        must not depend on the order they are listed in."""

        def __init__(self):
            super().__init__()
            self.classes = nn.Embedding(num_classes, 4)
            self.project = nn.Linear(num_features + 4, spec["d"])
            layer = nn.TransformerEncoderLayer(
                spec["d"], spec["heads"], dim_feedforward=2 * spec["d"], dropout=spec["dropout"], batch_first=True, activation="gelu"
            )
            self.encoder = nn.TransformerEncoder(layer, spec["layers"], enable_nested_tensor=False)
            self.head = nn.Linear(spec["d"], 1)

        def forward(self, inputs: torch.Tensor, class_ids: torch.Tensor) -> torch.Tensor:
            hidden = self.project(torch.cat([inputs, self.classes(class_ids)], dim=-1))
            return self.head(self.encoder(hidden)).squeeze(-1)

    return SetRanker()


def _date_batches(frame: pd.DataFrame, features: list[str], class_index: dict[str, int]) -> list[dict]:
    import torch

    batches = []
    for date, group in frame.groupby("date", sort=True):
        labels = group["_label"].to_numpy(np.float32)
        batches.append({
            "date": date,
            "x": torch.from_numpy(group[features].to_numpy(np.float32)).unsqueeze(0),
            "c": torch.tensor([class_index.get(name, 0) for name in group["_class"]], dtype=torch.long).unsqueeze(0),
            "y": torch.from_numpy(np.nan_to_num(labels)),
            "mask": torch.from_numpy(np.isfinite(labels)),
            "index": group.index.to_numpy(),
        })
    return batches


def _date_ic(scores: np.ndarray, labels: np.ndarray) -> float | None:
    keep = np.isfinite(labels)
    if keep.sum() < 10:
        return None
    ranked = pd.Series(scores[keep]).rank().to_numpy()
    target = pd.Series(labels[keep]).rank().to_numpy()
    if ranked.std() == 0.0 or target.std() == 0.0:
        return None
    return float(np.corrcoef(ranked, target)[0, 1])


def fit_predict_set_transformer(
    train: pd.DataFrame, test: pd.DataFrame, features: list[str], variant: str, seed: int,
    *, max_epochs: int = 20, patience: int = 3, learning_rate: float = 1e-3, weight_decay: float = 0.04, accumulate: int = 8,
) -> np.ndarray:
    import torch

    from train import soft_spearman_loss

    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    classes = sorted(set(train["_class"]) | set(test["_class"]))
    class_index = {name: i for i, name in enumerate(classes)}
    model = _set_ranker(len(features), len(classes), SET_TRANSFORMER_VARIANTS[variant])
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=weight_decay)

    batches = _date_batches(train, features, class_index)
    # the tail of the training span, kept out by the same purge, decides when to stop
    split = max(1, int(len(batches) * 0.85))
    fit_batches, stop_batches = batches[: max(1, split - EARLY_STOP_GAP_SESSIONS)], batches[split:]
    best_ic, best_state, stale = -math.inf, None, 0
    for epoch in range(max_epochs):
        model.train()
        optimizer.zero_grad()
        for position, index in enumerate(rng.permutation(len(fit_batches))):
            batch = fit_batches[int(index)]
            scores = model(batch["x"], batch["c"]).squeeze(0)
            groups = torch.zeros_like(scores, dtype=torch.long)
            loss = soft_spearman_loss(scores, batch["y"], groups, batch["mask"], 0.1)
            loss = loss + 0.1 * ((scores[batch["mask"]] - batch["y"][batch["mask"]]) ** 2).mean()
            (loss / accumulate).backward()
            if (position + 1) % accumulate == 0:
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                optimizer.zero_grad()
        model.eval()
        with torch.no_grad():
            ics = [_date_ic(model(b["x"], b["c"]).squeeze(0).numpy(), np.where(b["mask"].numpy(), b["y"].numpy(), np.nan)) for b in stop_batches]
        finite = [value for value in ics if value is not None]
        score = float(np.mean(finite)) if finite else -math.inf
        LOGGER.info("epoch %d stopping-span IC %.4f", epoch, score)
        if score > best_ic:
            best_ic, stale = score, 0
            best_state = {key: value.clone() for key, value in model.state_dict().items()}
        else:
            stale += 1
            if stale >= patience:
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    predictions = np.full(len(test), np.nan)
    positions = {index: i for i, index in enumerate(test.index)}
    with torch.no_grad():
        for batch in _date_batches(test, features, class_index):
            scores = model(batch["x"], batch["c"]).squeeze(0).numpy()
            for index, value in zip(batch["index"], scores):
                predictions[positions[index]] = float(value)
    return predictions


MLP_VARIANTS = {"a": {"hidden_layers": [128, 64], "dropout": 0.15}, "b": {"hidden_layers": [64, 32], "dropout": 0.3}}


def fit_predict_mlp_multitask(
    train: pd.DataFrame, test: pd.DataFrame, features: list[str], variant: str, seed: int,
    *, max_epochs: int = 20, patience: int = 3, learning_rate: float = 1e-3, weight_decay: float = 0.04,
) -> np.ndarray:
    """`AetherNetMultiTaskHorizons`, the installed family, fitted on its rank_20d head by date: the same soft Spearman plus MSE anchor
    and the same early stop as the set transformer. It scores each asset alone."""
    import torch

    from train import AetherNetMultiTaskHorizons, soft_spearman_loss

    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    spec = MLP_VARIANTS[variant]
    model = AetherNetMultiTaskHorizons(len(features), spec["hidden_layers"], spec["dropout"], "relu", "layernorm")
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    classes = {name: i for i, name in enumerate(sorted(set(train["_class"]) | set(test["_class"])))}
    batches = _date_batches(train, features, classes)
    split = max(1, int(len(batches) * 0.85))
    fit_batches, stop_batches = batches[: max(1, split - EARLY_STOP_GAP_SESSIONS)], batches[split:]

    def rank_scores(inputs: torch.Tensor) -> torch.Tensor:
        return model(inputs)["rank_20d"].reshape(-1)

    best_ic, best_state, stale = -math.inf, None, 0
    for _ in range(max_epochs):
        model.train()
        for index in rng.permutation(len(fit_batches)):
            batch = fit_batches[int(index)]
            optimizer.zero_grad()
            scores = rank_scores(batch["x"].squeeze(0))
            groups = torch.zeros_like(scores, dtype=torch.long)
            loss = soft_spearman_loss(scores, batch["y"], groups, batch["mask"], 0.1)
            loss = loss + 0.1 * ((scores[batch["mask"]] - batch["y"][batch["mask"]]) ** 2).mean()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
        model.eval()
        with torch.no_grad():
            ics = [_date_ic(rank_scores(b["x"].squeeze(0)).numpy(), np.where(b["mask"].numpy(), b["y"].numpy(), np.nan)) for b in stop_batches]
        finite = [value for value in ics if value is not None]
        score = float(np.mean(finite)) if finite else -math.inf
        if score > best_ic:
            best_ic, stale = score, 0
            best_state = {key: value.clone() for key, value in model.state_dict().items()}
        else:
            stale += 1
            if stale >= patience:
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        return rank_scores(torch.from_numpy(test[features].to_numpy(np.float32))).numpy().astype(np.float64)


FITTERS = {"gbm": fit_predict_gbm, "set_transformer": fit_predict_set_transformer, "mlp_multitask": fit_predict_mlp_multitask}


def load_panel_frame(panel: Path, *, feature_set: str, target: str) -> tuple[pd.DataFrame, list[str]]:
    """One side's parquet. Ranks and labels are computed on what the file holds, so a file of one side's names can't leak the other."""
    from features.wide_panel import INFO_FEATURES, PRICE_FEATURES

    wanted = list(PRICE_FEATURES) if feature_set == "price" else [*PRICE_FEATURES, *INFO_FEATURES]
    frame = pd.read_parquet(panel)
    features = [name for name in wanted if name in frame.columns]
    frame = frame.rename(columns={"sector": "_class"})
    frame["date"] = frame["date"].astype(str).str[:10]
    frame[features] = rank_inputs(frame, features)
    frame["_label"] = frame[target].astype("float32")
    keep = ["date", "ticker", "_class", "_label", *features]
    return frame[keep].sort_values(["date", "ticker"]).reset_index(drop=True), features


def walk_forward_scores(
    frame: pd.DataFrame, features: list[str], model: str, variant: str, seeds: list[int], *, score_end: str | None,
    first_test_year: int = FIRST_TEST_YEAR, purge_days: int = PURGE_DAYS, score_frame: pd.DataFrame | None = None, max_epochs: int | None = None,
) -> pd.DataFrame:
    """date, ticker, score for every test year, averaged over the seeds. Test rows past `score_end` are never scored. With `score_frame`,
    training still reads `frame` alone and each year's model scores `score_frame`'s rows."""
    pieces = []
    scored = frame if score_frame is None else score_frame
    for window in annual_windows(sorted(scored["date"].unique()), first_test_year=first_test_year, purge_days=purge_days):
        if score_end is not None and window["test_start"] > score_end:
            break
        last = window["test_end"] if score_end is None else min(window["test_end"], score_end)
        train = frame[frame["date"] <= window["train_end"]]
        test = scored[(scored["date"] >= window["test_start"]) & (scored["date"] <= last)]
        if train.empty or test.empty:
            continue
        LOGGER.info("window %s: %d train rows, %d test rows", window["test_start"], len(train), len(test))
        extra = {"max_epochs": max_epochs} if max_epochs else {}
        predictions = np.mean([FITTERS[model](train, test, features, variant, seed, **extra) for seed in seeds], axis=0)
        pieces.append(pd.DataFrame({"date": test["date"].to_numpy(), "ticker": test["ticker"].to_numpy(), "score": predictions}))
    return pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame(columns=["date", "ticker", "score"])


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default="ml/datasets/full_dataset.csv")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--schema", default="ml/feature_schema.json")
    parser.add_argument("--model", choices=sorted(FITTERS), required=True)
    parser.add_argument("--variant", choices=["a", "b"], required=True)
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--out", required=True)
    parser.add_argument("--score-end", default=None)
    parser.add_argument("--panel", default=None, help="a side's parquet from scripts/v660_build_panel.py, instead of --dataset")
    parser.add_argument("--score-panel", default=None, help="score this panel's rows with the same yearly models")
    parser.add_argument("--feature-set", choices=["price", "all"], default="all")
    parser.add_argument("--target", default="target_wide_20d")
    parser.add_argument("--first-test-year", type=int, default=FIRST_TEST_YEAR)
    parser.add_argument("--purge-days", type=int, default=PURGE_DAYS)
    parser.add_argument("--max-epochs", type=int, default=None, help="neural models only: the compute fallback rules.json fixes in advance")
    args = parser.parse_args(argv)
    seeds = [int(seed) for seed in args.seeds.split(",")]
    if args.panel:
        frame, features = load_panel_frame(Path(args.panel), feature_set=args.feature_set, target=args.target)
        score_frame = load_panel_frame(Path(args.score_panel), feature_set=args.feature_set, target=args.target)[0] if args.score_panel else None
        scores = walk_forward_scores(
            frame, features, args.model, args.variant, seeds, score_end=args.score_end, first_test_year=args.first_test_year, purge_days=args.purge_days,
            score_frame=score_frame, max_epochs=args.max_epochs,
        )
    else:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
        frame, features = load_frame(Path(args.dataset), config, schema)
        scores = walk_forward_scores(frame, features, args.model, args.variant, seeds, score_end=args.score_end)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    scores.to_csv(out, index=False, lineterminator="\n", float_format="%.6f")
    LOGGER.info("wrote %d scores, %s..%s, to %s", len(scores), scores["date"].min(), scores["date"].max(), out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
