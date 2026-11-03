"""Label / feature leakage audit (V6.4.3), four checks a dataset can fail without any test noticing:

(a) tail NaN: a feature computed with a forward-looking window is NaN on each ticker's last rows only;
(b) label shuffle: with each target shuffled within its date, no feature may keep an IC (a nonzero one means the
    pipeline aligns targets by something other than date and ticker);
(c) single-feature IC: one raw feature with |IC| > 0.15 against a forward rank is implausible and gets reviewed;
(d) identity: how much IC a pure asset-identity prior (each ticker's mean train target) and the class one-hots carry -
    a model that cannot beat them has learned who the asset is, not what it will do.
Pure; operates on an in-memory frame.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from evaluation.gate_audit import daily_rank_ic


def _mean_ic(frame: pd.DataFrame, score: str, target: str, date_column: str, min_names: int) -> float | None:
    ic = daily_rank_ic(frame, score_column=score, target_column=target, date_column=date_column, min_names_per_date=min_names)
    return float(np.mean(list(ic.values()))) if ic else None


def tail_nan_check(frame: pd.DataFrame, feature_columns, *, ticker_column: str = "ticker", date_column: str = "date",
                   horizon: int = 20, threshold: float = 0.05) -> dict:
    ordered = frame.sort_values([ticker_column, date_column])
    position_from_end = ordered.groupby(ticker_column).cumcount(ascending=False)
    tail = position_from_end < horizon
    result = {}
    for column in feature_columns:
        missing = ordered[column].isna()
        tail_rate, body_rate = float(missing[tail].mean()), float(missing[~tail].mean()) if (~tail).any() else 0.0
        result[column] = {"tail_nan_rate": tail_rate, "body_nan_rate": body_rate, "flag": tail_rate - body_rate > threshold}
    return result


def label_shuffle_check(frame: pd.DataFrame, feature_columns, target_column: str, *, date_column: str = "date",
                        min_names: int = 20, seed: int = 7, max_abs_t: float = 3.0) -> dict:
    """A shuffled target's IC is sampling noise around 0; |t| above `max_abs_t` is not."""
    rng = np.random.default_rng(seed)
    shuffled = frame[[date_column, target_column, *feature_columns]].copy()
    shuffled[target_column] = shuffled.groupby(date_column)[target_column].transform(lambda s: rng.permutation(s.to_numpy()))
    result = {}
    for column in feature_columns:
        ic = list(daily_rank_ic(shuffled, score_column=column, target_column=target_column, date_column=date_column,
                                min_names_per_date=min_names).values())
        mean = float(np.mean(ic)) if ic else None
        t = float(mean / (np.std(ic, ddof=1) / np.sqrt(len(ic)))) if len(ic) > 2 and np.std(ic, ddof=1) > 0 else 0.0
        result[column] = {"shuffled_ic": mean, "t": t, "flag": abs(t) > max_abs_t}
    return result


def single_feature_ic(frame: pd.DataFrame, feature_columns, target_column: str, *, date_column: str = "date",
                      min_names: int = 20, threshold: float = 0.15) -> dict:
    result = {}
    for column in feature_columns:
        value = _mean_ic(frame, column, target_column, date_column, min_names)
        result[column] = {"ic": value, "flag": value is not None and abs(value) > threshold}
    return result


def centre_by_group(frame: pd.DataFrame, target_column: str, group_column: str, *, date_column: str = "date") -> pd.Series:
    """`target_column` minus its mean over the same (date, group). A percentile rank in a group of n names averages
    (n+1)/2n, so with separate rank groups or small sectors the raw label means differ by group size alone (V6.4.4)."""
    return frame[target_column] - frame.groupby([date_column, group_column])[target_column].transform("mean")


def identity_check(train: pd.DataFrame, evaluation: pd.DataFrame, target_column: str, *, ticker_column: str = "ticker",
                   date_column: str = "date", class_columns=(), model_score_column: str | None = None, min_names: int = 20,
                   group_column: str | None = None) -> dict:
    """IC of an asset-identity prior (each ticker's mean train target) and an asset-class prior against the model's.
    With `group_column` (V6.4.4) the same figures are also computed on the group-centred target ("group_centred"): the
    raw priors mostly read the group-size artifact of percentile ranks, which a book ranking within groups cannot trade."""
    out = _identity_figures(train, evaluation, target_column, ticker_column=ticker_column, date_column=date_column,
                            class_columns=class_columns, model_score_column=model_score_column, min_names=min_names)
    if group_column and group_column in train.columns and group_column in evaluation.columns:
        centred = "_target_group_centred"
        out["group_centred"] = _identity_figures(
            train.assign(**{centred: centre_by_group(train, target_column, group_column, date_column=date_column)}),
            evaluation.assign(**{centred: centre_by_group(evaluation, target_column, group_column, date_column=date_column)}),
            centred, ticker_column=ticker_column, date_column=date_column, class_columns=class_columns,
            model_score_column=model_score_column, min_names=min_names)
        out["group_column"] = group_column
    return out


def _identity_figures(train: pd.DataFrame, evaluation: pd.DataFrame, target_column: str, *, ticker_column: str, date_column: str,
                      class_columns, model_score_column: str | None, min_names: int) -> dict:
    prior = train.groupby(ticker_column)[target_column].mean()
    scored = evaluation.assign(_identity_prior=evaluation[ticker_column].map(prior))
    out = {"identity_prior_ic": _mean_ic(scored, "_identity_prior", target_column, date_column, min_names)}
    present = [c for c in class_columns if c in evaluation.columns]
    if present:
        train_class = train[present].to_numpy(dtype=float).argmax(axis=1)
        class_mean = pd.Series(train[target_column].to_numpy(dtype=float), index=train_class).groupby(level=0).mean()
        eval_class = pd.Series(evaluation[present].to_numpy(dtype=float).argmax(axis=1), index=evaluation.index)
        scored = scored.assign(_class_prior=eval_class.map(class_mean))
        out["class_prior_ic"] = _mean_ic(scored, "_class_prior", target_column, date_column, min_names)
    if model_score_column and model_score_column in evaluation.columns:
        out["model_ic"] = _mean_ic(evaluation, model_score_column, target_column, date_column, min_names)
        if out["identity_prior_ic"] is not None and out["model_ic"] is not None:
            out["model_minus_identity"] = out["model_ic"] - out["identity_prior_ic"]
    return out


def audit_leakage(frame: pd.DataFrame, *, feature_columns, target_column: str = "target_rank_20d", ticker_column: str = "ticker",
                  date_column: str = "date", split_column: str = "split", horizon: int = 20, class_columns=(),
                  model_score_column: str | None = None, min_names: int = 20, seed: int = 7, group_column: str | None = None) -> dict:
    """All four checks; (b) and (c) on the validation split, (d) fit on train and read on validation."""
    validation = frame[frame[split_column] == "validation"] if split_column in frame else frame
    train = frame[frame[split_column] == "train"] if split_column in frame else frame
    report = {
        "tail_nan": tail_nan_check(frame, feature_columns, ticker_column=ticker_column, date_column=date_column, horizon=horizon),
        "label_shuffle": label_shuffle_check(validation, feature_columns, target_column, date_column=date_column,
                                             min_names=min_names, seed=seed),
        "single_feature_ic": single_feature_ic(validation, feature_columns, target_column, date_column=date_column, min_names=min_names),
        "identity": identity_check(train, validation, target_column, ticker_column=ticker_column, date_column=date_column,
                                   class_columns=class_columns, model_score_column=model_score_column, min_names=min_names,
                                   group_column=group_column),
    }
    report["flagged"] = sorted(
        {column for check in ("tail_nan", "label_shuffle", "single_feature_ic") for column, row in report[check].items() if row["flag"]}
    )
    return report
