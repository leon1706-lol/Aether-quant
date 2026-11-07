"""How a dataset is split for training, with nothing of the training stack (V6.6.1): walls between train, validation and backtest, label purges, purged folds, yearly walk-forward windows and
ranked inputs. Moved unchanged from `train.py` and `train_cross_sectional.py`, which import them from here, so `aether_quant` can offer them without torch or sklearn."""

from __future__ import annotations

import numpy as np
import pandas as pd

_SPLIT_ORDER = {"train": 0, "validation": 1, "backtest": 2}
TARGET = "target_sector_neutral_rank_20d"
PURGE_DAYS = 20
FIRST_TEST_YEAR = 2019


def purge_label_overlap(splits: list, horizon_rows: int) -> list:
    """V5.7.0: relabel "purged" every row whose forward label window reaches into a LATER split. A row labelled
    `horizon_rows` bars ahead (the 20-day return / rank targets) carries information from the next split's prices, so the
    last `horizon_rows` rows of train (and of validation) leak the validation (and backtest) period into the data the model
    is fitted, early-stopped and selected on. `splits` is one asset's per-row split labels in date order (None / NaN rows
    are outside every window and stay as they are); purged rows are kept in the frame as feature context but match no
    split filter. `horizon_rows <= 0` returns the labels unchanged."""
    result = list(splits)
    if horizon_rows <= 0:
        return result
    first_index: dict[str, int] = {}
    for index in range(len(splits) - 1, -1, -1):
        label = splits[index]
        if not isinstance(label, str) or label not in _SPLIT_ORDER:
            continue
        rank = _SPLIT_ORDER[label]
        later_starts = [start for name, start in first_index.items() if _SPLIT_ORDER[name] > rank]
        if later_starts and min(later_starts) - index <= horizon_rows:
            result[index] = "purged"
        first_index[label] = index
    return result


def purge_label_overlap_calendar(splits: list, dates: list, calendar_days: int) -> list:
    """`purge_label_overlap` in calendar days. A pooled rank mixes classes: 20 crypto bars are 20 days but 20 equity sessions are
    about 28, so a crypto row kept by a 20-row purge can have a rank built from equity returns past the boundary.
    `calendar_days <= 0` returns the labels unchanged."""
    result = list(splits)
    if calendar_days <= 0:
        return result
    stamps = [pd.Timestamp(date) for date in dates]
    first_date: dict[str, pd.Timestamp] = {}
    for index in range(len(splits) - 1, -1, -1):
        label = splits[index]
        if not isinstance(label, str) or label not in _SPLIT_ORDER:
            continue
        rank = _SPLIT_ORDER[label]
        later_starts = [start for name, start in first_date.items() if _SPLIT_ORDER[name] > rank]
        if later_starts and (min(later_starts) - stamps[index]).days <= calendar_days:
            result[index] = "purged"
        first_date[label] = stamps[index]
    return result


def assign_split(date_value: pd.Timestamp, windows: dict) -> str | None:
    date_stamp = pd.Timestamp(date_value)
    training = windows["training"]
    validation = windows["validation"]
    backtest = windows["backtest"]

    if pd.Timestamp(training["start"]) <= date_stamp <= pd.Timestamp(training["end"]):
        return "train"
    if pd.Timestamp(validation["start"]) <= date_stamp <= pd.Timestamp(validation["end"]):
        return "validation"
    if pd.Timestamp(backtest["start"]) <= date_stamp <= pd.Timestamp(backtest["end"]):
        return "backtest"
    return None


def assign_split_series(dates: pd.Series, windows: dict) -> pd.Series:
    """assign_split() for a whole column at once (V5.8.0: the per-row apply ran once per dataset row); same inclusive
    bounds and precedence, None outside every window."""
    stamps = pd.to_datetime(dates)
    labels = pd.Series([None] * len(stamps), index=dates.index, dtype=object)
    for split_name, key in (("backtest", "backtest"), ("validation", "validation"), ("train", "training")):
        window = windows[key]
        inside = (stamps >= pd.Timestamp(window["start"])) & (stamps <= pd.Timestamp(window["end"]))
        labels[inside.to_numpy()] = split_name  # earlier splits written last win on overlap, as in assign_split()
    return labels


def purged_embargoed_folds(
    dates,
    n_folds: int,
    horizon_days: int,
    embargo_days: int = 0,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Phase 2 of the 5/10 -> 9/10 roadmap: a standard purged/embargoed
    K-fold split (Lopez de Prado-style) over `dates` (any array-like of
    orderable date values, one entry per dataset row - duplicates expected,
    since every asset shares each date). Layered *inside* the existing
    fixed phase1.windows train split as an additional diagnostic for
    hyperparameter/early-stopping robustness and a more honest in-sample IC
    distribution - it does NOT replace the top-level train/validation/backtest
    wall (that stays the single no-lookahead-across-the-wall boundary; see
    assign_split()), nor does it change which rows actually get promoted.

    For each of `n_folds` contiguous, equal-width date-range folds (assigned
    by unique date, not by row, so every asset's same-date rows always fall
    in the same fold together): the *validation* fold is exactly that
    date-range; the *training* rows are every row from the OTHER folds,
    minus (a) any row whose own forward-return window (horizon_days ahead)
    would overlap the validation fold's date range at all ("purge" - a
    training row labeled using information that reaches into the validation
    window leaks), and (b) any row falling within `embargo_days` immediately
    AFTER the validation fold's end date ("embargo" - guards against
    lookback-feature leakage, e.g. rolling_volatility_20d/momentum_20d
    computed just after the validation window still partially "sees" it).

    Returns a list of (train_row_indices, validation_row_indices) index
    arrays into `dates` itself (positional, 0-based) - same shape
    convention as sklearn's KFold.split(), so this composes with any
    existing sklearn-based tooling without adapting a different interface.
    Returns [] (never raises) when there are fewer unique dates than
    `n_folds`, matching this codebase's "guard against thin data" convention
    throughout train.py (e.g. build_cross_sectional_rank_targets()'s
    min_universe_size gate)."""
    # pd.to_datetime(), not np.asarray(): `dates` in real callers (e.g.
    # assess_ranking_quality_from_predictions(), fed train_multitask.py/
    # train_sequence.py's `frame["date"]`) is a plain string array -
    # build_feature_dataset() stringifies the date column
    # (dataset["date"].dt.strftime(...)) before any trainer ever reads it.
    # A raw np.asarray() on strings stays strings, and `era_start + Timedelta`
    # below would then raise "can only concatenate str to str" - explicit
    # datetime coercion here makes this function robust to string,
    # Timestamp, or datetime64 input alike, matching every other
    # date-accepting function in this file (e.g. assign_split()'s own
    # pd.Timestamp(date_value) coercion).
    #
    # np.unique(), not sorted(set(dates_array.tolist())): for a raw
    # datetime64[ns] numpy array (as opposed to a pandas Series, whose
    # .tolist() preserves Timestamp objects), .tolist() silently degrades
    # to plain nanosecond ints - Python's stdlib datetime can't represent
    # nanosecond precision - which would then compare incompatibly against
    # the still-datetime64 dates_array below. np.unique() preserves dtype
    # natively and needs no such workaround.
    dates_array = pd.to_datetime(np.asarray(dates))
    unique_dates = np.unique(dates_array)
    if len(unique_dates) < n_folds:
        return []

    fold_boundaries = np.array_split(unique_dates, n_folds)
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    horizon = pd.Timedelta(horizon_days, unit="D")
    embargo = pd.Timedelta(embargo_days, unit="D")

    for fold_dates in fold_boundaries:
        if len(fold_dates) == 0:
            continue
        validation_start = fold_dates[0]
        validation_end = fold_dates[-1]
        validation_mask = (dates_array >= validation_start) & (dates_array <= validation_end)

        # Purge: a training row's own forward-return window (up to
        # horizon_days ahead of its own date) must not reach into the
        # validation date range - equivalently, exclude any row whose date
        # falls within horizon_days BEFORE the validation window starts.
        purge_start = validation_start - horizon
        purged_mask = (dates_array >= purge_start) & (dates_array < validation_start)

        # Embargo: exclude rows in the embargo_days immediately after the
        # validation window ends.
        embargo_end = validation_end + embargo
        embargoed_mask = (dates_array > validation_end) & (dates_array <= embargo_end)

        excluded_mask = validation_mask | purged_mask | embargoed_mask
        train_indices = np.where(~excluded_mask)[0]
        validation_indices = np.where(validation_mask)[0]
        if len(train_indices) == 0 or len(validation_indices) == 0:
            continue
        folds.append((train_indices, validation_indices))

    return folds


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

