"""evaluation/dataset_io.py: chunked reads that equal a plain read on what they keep (#389)."""

import numpy as np
import pandas as pd
import pytest

from evaluation.dataset_io import read_dataset_columns, read_dataset_rows


@pytest.fixture
def csv(tmp_path):
    rng = np.random.default_rng(3)
    frame = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=40).strftime("%Y-%m-%d"), "ticker": ["A", "B"] * 20,
        "split": ["train"] * 20 + ["backtest"] * 20, "x": rng.normal(size=40), "y": rng.normal(size=40), "n": np.arange(40),
    })
    path = tmp_path / "full_dataset.csv"
    frame.to_csv(path, index=False)
    return path, frame


def test_columns_read_in_small_chunks_equal_a_plain_read_as_float32(csv):
    path, frame = csv
    got = read_dataset_columns(path, ["date", "ticker", "x"], chunk_rows=7)
    assert list(got.columns) == ["date", "ticker", "x"]
    assert got["x"].dtype == np.float32
    np.testing.assert_allclose(got["x"], frame["x"], rtol=1e-6)
    assert got["date"].tolist() == frame["date"].tolist()


def test_a_date_floor_is_applied_per_chunk_even_when_the_date_is_not_asked_for(csv):
    path, frame = csv
    got = read_dataset_columns(path, ["ticker", "y"], start="2024-01-31", chunk_rows=9)
    assert list(got.columns) == ["ticker", "y"]
    assert len(got) == int((frame["date"] >= "2024-01-31").sum())


def test_a_missing_column_is_an_error_and_an_empty_floor_gives_an_empty_frame(csv):
    path, _ = csv
    with pytest.raises(KeyError, match="nope"):
        read_dataset_columns(path, ["x", "nope"])
    assert read_dataset_columns(path, ["x"], start="2030-01-01").empty


def test_rows_of_one_split_equal_a_plain_filtered_read(csv):
    path, frame = csv
    got = read_dataset_rows(path, split="backtest", chunk_rows=6)
    pd.testing.assert_frame_equal(got, frame[frame["split"] == "backtest"].reset_index(drop=True))
    assert len(read_dataset_rows(path, chunk_rows=6)) == len(frame)
    assert read_dataset_rows(path, split="nothing").empty


def test_a_header_only_file_reads_as_an_empty_frame(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("date,ticker,split,x\n", encoding="utf-8")
    assert read_dataset_rows(path).empty
    assert read_dataset_columns(path, ["x"], start="2024-01-01").empty
