"""lab/lab_dataset.py: datasets in the production columns, purged splits, the sealed holdout, info and the leakage audit."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from lab import lab_dataset as ld


def _closes(rows: int = 400, names: int = 6, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = [str(day.date()) for day in pd.bdate_range("2021-01-04", periods=rows)]
    return pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.02, (rows, names)), axis=0)), index=index, columns=[f"T{i}" for i in range(names)])


def test_a_dataset_has_the_production_columns_and_purged_splits():
    closes = _closes()
    frame = ld.build_dataset(closes, features="example", targets=(5, 20))
    assert list(frame.columns[:3]) == ["date", "ticker", "close"] and frame.columns[-1] == "split"
    assert {"target_rank_20d", "target_return_20d", "target_direction_20d", "target_rank_5d"} <= set(frame.columns)
    assert ld.feature_columns(frame) == ["ret_1", "ret_5", "ret_20", "ret_60", "vol_20", "vol_60"]
    assert set(ld.target_columns(frame)) == {column for column in frame.columns if column.startswith("target_")}
    order = sorted(closes.index)
    for split in ("train", "validation"):
        last = frame.loc[frame["split"] == split, "date"].max()
        window_end = ld.default_splits(order)[split][1]
        assert order.index(last) + 20 <= order.index(window_end), "a label never reaches past its split's end"
    assert frame.groupby("date")["ticker"].count().min() >= 3


def test_split_windows_parse_and_bad_ones_say_how_to_write_them():
    assert ld.parse_splits("train:2021-01-04..2021-06-30, holdout:2022-01-01..2022-06-30") == {"train": ("2021-01-04", "2021-06-30"), "holdout": ("2022-01-01", "2022-06-30")}
    with pytest.raises(ValueError, match="NAME:START..END"):
        ld.parse_splits("training:2021-01-01..2021-02-01")
    with pytest.raises(ValueError, match="at least 10 dates"):
        ld.default_splits(["2021-01-01"])


def test_explicit_splits_with_a_holdout_are_sealed_on_every_read(tmp_path):
    closes = _closes()
    windows = ld.parse_splits("train:2021-01-04..2021-09-30,validation:2021-10-01..2022-01-31,holdout:2022-02-01..2022-06-30")
    frame = ld.build_dataset(closes, features=["ret_5", "vol_20"], targets=(20,), splits=windows)
    assert "holdout" in set(frame["split"])
    path = tmp_path / "d.csv"
    frame.to_csv(path, index=False)
    assert "holdout" not in set(ld.load_dataset(path)["split"])
    assert "holdout" in set(ld.load_dataset(path, allow_holdout=True)["split"])
    info = ld.dataset_info(frame)
    assert info["holdout_rows"] > 0 and set(info["splits"]) == {"train", "validation", "holdout", "purged"} and info["features"]["ret_5"] < 0.5


def test_the_project_holdout_window_is_found_by_key_and_dropped_by_date(tmp_path):
    config = {"phase1": {"data": {"splits": {"training": {"start": "2020-01-01"}, "validation": {"start": "2021"}, "holdout": {"start": "2021-06-01", "end": "2021-12-31"}}}}}
    assert ld.holdout_window(config) == ("2021-06-01", "2021-12-31")
    assert ld.holdout_window({"phase1": {"holdout": {"start": "x", "end": "y"}}}) is None, "a holdout key beside no split windows is something else"
    frame = pd.DataFrame({"date": ["2021-05-31", "2021-06-01", "2022-01-01"], "ticker": "A", "split": "backtest"})
    assert ld.seal(frame, window=("2021-06-01", "2021-12-31"))["date"].tolist() == ["2021-05-31", "2022-01-01"]
    path = tmp_path / "d.csv"
    frame.to_csv(path, index=False)
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    assert len(ld.load_dataset(path, project_config=tmp_path / "config.json")) == 2
    assert len(ld.load_dataset(path, project_config=tmp_path / "missing.json")) == 3
    assert len(ld.seal(frame.drop(columns=["split", "date"]))) == 3


def test_rank_features_are_within_date_ranks_and_the_leakage_audit_runs():
    frame = ld.build_dataset(_closes(), features="example", targets=(20,))
    ranked = ld.rank_features(frame, ["ret_5", "vol_20"])
    assert ranked.dtype == np.float32 and ranked.min() >= -0.5 and ranked.max() <= 0.5
    report = ld.leakage_report(frame)
    assert {"tail_nan", "label_shuffle", "single_feature_ic", "identity", "flagged"} <= set(report)
    assert ld.dataset_info(frame.drop(columns=["split"]))["splits"] == {}
