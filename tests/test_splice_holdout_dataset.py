"""Tests for scripts/splice_holdout_dataset.py (V6.4.2): the narrow windows config, the streamed overlap guard and the splice."""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HEADER = ["timestamp", "date", "ticker", "feature", "target_return_20d", "split"]


def _load():
    spec = importlib.util.spec_from_file_location("_splice_holdout_dataset", ROOT / "scripts" / "splice_holdout_dataset.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, rows: list[list[str]], header: list[str] = HEADER) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    return path


def _old(tmp_path: Path) -> Path:
    return _write(tmp_path / "full.csv", [
        ["1", "2025-06-27", "AAA", "0.1", "0.01", "backtest"],
        ["1", "2025-06-30", "AAA", "0.2", "0.02", "backtest"],
        ["1", "2025-07-01", "AAA", "0.3", "0.03", "holdout"],
        ["1", "2025-07-01", "BBB", "0.4", "", "holdout"],
        ["1", "2025-07-02", "AAA", "0.5", "", "holdout"],
    ])


def _window(tmp_path: Path, feature_0701: str = "0.3") -> Path:
    return _write(tmp_path / "window.csv", [
        ["1", "2015-01-05", "AAA", "9", "9", "validation"],
        ["1", "2025-06-30", "AAA", "0.2", "0.02", "backtest"],
        ["1", "2025-07-01", "AAA", feature_0701, "0.03", "backtest"],
        ["1", "2025-07-01", "BBB", "0.4", "", "backtest"],
        ["1", "2025-07-02", "AAA", "0.5", "0.07", "backtest"],
        ["1", "2025-07-03", "AAA", "0.6", "0.08", "backtest"],
    ])


def test_the_narrow_windows_keep_the_purge_and_set_the_holdout():
    splice = _load()
    config = {"phase1": {"windows": {"training": {"start": "2014-12-01", "end": "2021-12-31"}, "purge_label_horizon_days": 20}}}
    windows = splice.narrow_windows_config(config, "2025-03-01", "2026-10-16")["phase1"]["windows"]
    assert windows["training"] == splice.NARROW_TRAINING and windows["validation"] == splice.NARROW_VALIDATION
    assert windows["holdout"] == {"start": "2025-03-01", "end": "2026-10-16"} and windows["purge_label_horizon_days"] == 20


def test_values_equal_tolerates_float_noise_only():
    splice = _load()
    assert splice.values_equal("0.1", "0.1") and splice.values_equal("", "")
    assert splice.values_equal("0.30000000000000004", "0.3") and splice.values_equal("nan", "NaN")
    assert not splice.values_equal("0.3", "0.31") and not splice.values_equal("", "0.3") and not splice.values_equal("AAA", "BBB")


def test_splice_replaces_the_holdout_rows_after_the_guard(tmp_path):
    splice = _load()
    out = tmp_path / "out.csv"
    result = splice.splice(_old(tmp_path), _window(tmp_path), out, "2025-07-01", "2025-07-01")
    rows = list(csv.reader(out.open(encoding="utf-8")))
    assert rows[0] == HEADER
    assert [row[1] for row in rows[1:]] == ["2025-06-27", "2025-06-30", "2025-07-01", "2025-07-01", "2025-07-02", "2025-07-03"]
    assert {row[5] for row in rows[3:]} == {"holdout"}
    assert rows[5][4] == "0.07"  # a label the old build could not resolve yet
    assert result["kept"] == 2 and result["dropped_old_holdout"] == 3 and result["new_holdout"] == 4
    assert result["compared"] == 2 and result["last_date"] == "2025-07-03"


def test_the_guard_refuses_a_feature_difference_or_a_missing_row(tmp_path):
    splice = _load()
    with pytest.raises(ValueError, match="overlap guard failed"):
        splice.splice(_old(tmp_path), _window(tmp_path, feature_0701="0.35"), tmp_path / "out.csv", "2025-07-01", "2025-07-01")
    window = _write(tmp_path / "short.csv", [["1", "2025-07-01", "AAA", "0.3", "0.03", "backtest"]])
    with pytest.raises(ValueError, match="1 rows missing"):
        splice.splice(_old(tmp_path), window, tmp_path / "out.csv", "2025-07-01", "2025-07-01")
    assert not (tmp_path / "out.csv").exists()


def test_the_guard_refuses_other_columns_or_a_late_backtest_row(tmp_path):
    splice = _load()
    other = _write(tmp_path / "other.csv", [], header=HEADER + ["extra"])
    with pytest.raises(ValueError, match="columns differ"):
        splice.splice(_old(tmp_path), other, tmp_path / "out.csv", "2025-07-01", "2025-07-01")
    with pytest.raises(ValueError, match="sits after --splice-from"):
        splice.splice(_old(tmp_path), _window(tmp_path), tmp_path / "out.csv", "2025-06-28", "2025-06-27")


def test_the_default_build_start_leaves_a_whole_sensitivity_lookback():
    """A build from 2025-03 left the trailing 252-row sens_* betas at 0.0 on the holdout's first months (the guard caught it)."""
    splice = _load()
    config = {"phase1": {"features": {"cross_asset_sensitivity": {"lookback_days": 252}}}}
    assert splice.default_build_start(config, "2025-07-01") == "2024-05-31"
    assert splice.default_build_start({}, "2025-07-01") == "2024-05-31"


def test_whole_history_beta_labels_may_move_and_are_counted(tmp_path):
    """The beta-neutral / residual rank labels use one whole-history beta per asset, so any rebuild moves them."""
    splice = _load()
    header = HEADER + ["target_residual_rank_20d"]
    old = _write(tmp_path / "full.csv", [["1", "2025-06-30", "AAA", "0.2", "0.02", "backtest", "0.5"],
                                         ["1", "2025-07-01", "AAA", "0.3", "0.03", "holdout", "0.5"]], header=header)
    window = _write(tmp_path / "window.csv", [["1", "2025-07-01", "AAA", "0.3", "0.03", "backtest", "0.6"]], header=header)
    result = splice.splice(old, window, tmp_path / "out.csv", "2025-07-01", "2025-07-01")
    assert result["sample_dependent_cells_moved"] == 1 and result["new_holdout"] == 1
    feature_moved = _write(tmp_path / "w2.csv", [["1", "2025-07-01", "AAA", "0.4", "0.03", "backtest", "0.5"]], header=header)
    with pytest.raises(ValueError, match="overlap guard failed"):
        splice.splice(old, feature_moved, tmp_path / "out2.csv", "2025-07-01", "2025-07-01")
