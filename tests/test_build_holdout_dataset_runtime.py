"""scripts/build_holdout_dataset.py's `main()` (V6.6.6, #359): the holdout window of the default mode, the four-split file with its per-split files, and a refusal when no
window exists. train.py's dataset builders are stood in; the window logic, the labelling and the writing are the script's own."""

from __future__ import annotations

import json
import sys

import pandas as pd
import pytest

from script_loader import load_script

WINDOWS = {"training": {"start": "2014-12-01", "end": "2019-12-31"}, "validation": {"start": "2020-01-01", "end": "2023-06-30"}, "backtest": {"start": "2023-07-01", "end": "2025-06-30"},
           "holdout": {"start": "2025-07-01", "end": "2026-09-30"}}


@pytest.fixture
def module(monkeypatch, tmp_path):
    import train

    script = load_script("build_holdout_dataset")
    monkeypatch.setattr(script, "ROOT_DIR", tmp_path)
    (tmp_path / "ml").mkdir()
    (tmp_path / "ml" / "scaler_stats.json").write_text("{}", encoding="utf-8")
    (tmp_path / "ml" / "dataset_manifest.json").write_text(json.dumps({"asset_quality": {"AAA": "ok"}}), encoding="utf-8")
    seen = {}
    dataset = pd.DataFrame({"date": ["2024-01-02", "2025-08-01", "2025-09-01", "2020-05-01", "2019-05-01"], "ticker": ["AAA"] * 5, "split": ["backtest", "backtest", "backtest", "validation", "train"]})
    monkeypatch.setattr(train, "build_holdout_config", lambda config, root, start, end: (seen.update(root=root, start=start, end=end) or {"phase1": {"universe": {"assets": [{"ticker": "AAA"}]}}}, ["GONE"]))
    monkeypatch.setattr(train, "build_feature_dataset", lambda config: (dataset.copy(), {}))
    monkeypatch.setattr(train, "apply_asset_quality_flags", lambda frame, quality: frame)
    monkeypatch.setattr(train, "apply_scaler_stats", lambda frame, stats: frame)
    monkeypatch.setattr(train, "add_asset_context_features", lambda frame, tickers: (frame, None))
    monkeypatch.setattr(train, "add_asset_class_context_features", lambda frame, classes: (frame, None))
    monkeypatch.setattr(train, "asset_class_by_ticker_from_config", lambda config: {})
    script.seen = seen
    return script


def _config(tmp_path, *, holdout=True, name="config.json"):
    windows = dict(WINDOWS) if holdout else {key: value for key, value in WINDOWS.items() if key != "holdout"}
    (tmp_path / name).write_text(json.dumps({"phase1": {"windows": windows, "universe": {"assets": []}}}), encoding="utf-8")
    return str(tmp_path / name)


def test_rows_of_the_extended_backtest_window_from_the_holdout_start_become_the_holdout(module):
    frame = pd.DataFrame({"date": ["2024-01-02", "2025-07-01", "2025-08-01"], "split": ["backtest", "backtest", "validation"]})
    assert module.label_holdout_rows(frame, "2025-07-01")["split"].tolist() == ["backtest", "holdout", "validation"]


def test_the_full_split_window_runs_from_the_backtest_start_to_the_holdout_end(module):
    assert module.full_split_window(WINDOWS) == ("2023-07-01", "2026-09-30")
    with pytest.raises(ValueError, match="needs phase1.windows.holdout"):
        module.full_split_window({"backtest": {}})


def test_the_default_mode_builds_the_holdout_window_of_the_config(module, monkeypatch, tmp_path, capsys):
    config = _config(tmp_path)
    out = tmp_path / "out" / "holdout.csv"
    monkeypatch.setattr(sys, "argv", ["build_holdout_dataset", "--config-path", config, "--windows-config", config, "--output", str(out), "--root", "stage"])
    assert module.main() == 0
    assert module.seen == {"root": "stage", "start": "2025-07-01", "end": "2026-09-30"} and len(pd.read_csv(out)) == 5 and "dropped (no holdout zip): ['GONE']" in capsys.readouterr().out


def test_the_four_split_file_labels_the_holdout_and_writes_the_per_split_files(module, monkeypatch, tmp_path, capsys):
    config = _config(tmp_path)
    out = tmp_path / "out" / "full.csv"
    monkeypatch.setattr(sys, "argv", ["build_holdout_dataset", "--config-path", config, "--windows-config", config, "--output", str(out), "--full-splits", "--write-split-files"])
    assert module.main() == 0
    written = pd.read_csv(out)
    assert set(written["split"]) == {"backtest", "holdout", "validation", "train"} and module.seen["start"] == "2023-07-01"
    assert {path.name for path in out.parent.iterdir()} == {"full.csv", "train_dataset.csv", "validation_dataset.csv", "backtest_dataset.csv"} and "rows per split" in capsys.readouterr().out


def test_without_a_holdout_window_or_explicit_dates_the_command_refuses(module, monkeypatch, tmp_path):
    config = _config(tmp_path, holdout=False)
    monkeypatch.setattr(sys, "argv", ["build_holdout_dataset", "--config-path", config, "--windows-config", config, "--output", str(tmp_path / "x.csv")])
    with pytest.raises(SystemExit):
        module.main()
    monkeypatch.setattr(sys, "argv", ["build_holdout_dataset", "--config-path", config, "--windows-config", config, "--output", str(tmp_path / "x.csv"), "--start", "2025-07-01", "--end", "2025-12-31"])
    assert module.main() == 0 and module.seen["start"] == "2025-07-01"
