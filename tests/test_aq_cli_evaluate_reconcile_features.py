"""aq evaluate --reconcile-features (V6.6.6, #359): the live path's logged feature snapshots against the dataset row, on a tiny book
history and dataset. The real reconciliation code runs; only the files are synthetic."""

from __future__ import annotations

import argparse
import json

import pandas as pd

import aq_cli
from test_aq_cli_evaluate_lean import env, ns  # noqa: F401  (the fixture and the namespace builder)


def _history(path, runs, symbol="AAPL", snapshot=True):
    lines = []
    for run in runs:
        for date in run:
            record = {"date": date, "run_id": f"r{run[0]}"}
            if snapshot:
                record["feature_snapshot"] = {symbol: {"rsi_14": 55.0, "momentum_20": 0.1}, "OTHER": {"rsi_14": 1.0}}
            lines.append(json.dumps(record))
    path.write_text("\n".join(lines) + "\n\nnot json\n", encoding="utf-8")


def _dataset(path, symbol="AAPL", dates=("2025-01-02", "2025-01-03", "2025-01-06")):
    pd.DataFrame({"date": dates, "ticker": symbol, "rsi_14": [55.0, 56.0, 57.0], "momentum_20": 0.1, "split": "backtest"}).to_csv(path, index=False)


def _args(env, **extra):
    return ns(reconcile_features=True, symbol="AAPL", book_history_path=str(env.root / "book.jsonl"), dataset=str(env.root / "full.csv"), **extra)


def test_errors_are_explained_before_any_work_is_done(env, capsys):
    assert aq_cli.cmd_evaluate(ns(reconcile_features=True)) == 1 and "requires --symbol" in capsys.readouterr().err
    assert aq_cli.cmd_evaluate(ns(reconcile_features=True, symbol="AAPL", book_history_path=str(env.root / "none.jsonl"))) == 1 and "not found" in capsys.readouterr().err
    (env.root / "book.jsonl").write_text("\n\n", encoding="utf-8")
    assert aq_cli.cmd_evaluate(_args(env)) == 1 and "no usable records" in capsys.readouterr().err
    _history(env.root / "book.jsonl", [["2025-01-02", "2025-01-03"]])
    assert aq_cli.cmd_evaluate(_args(env, reconcile_run_index=5)) == 1 and "out of range" in capsys.readouterr().err
    assert aq_cli.cmd_evaluate(_args(env)) == 1 and "full.csv" in capsys.readouterr().err


def test_a_matching_snapshot_is_reconciled_and_printed(env, capsys):
    _history(env.root / "book.jsonl", [["2025-01-02", "2025-01-03"]])
    _dataset(env.root / "full.csv")
    assert aq_cli.cmd_evaluate(_args(env)) == 0
    text = capsys.readouterr().out
    assert "2 record(s) carried a feature_snapshot" in text and "divergent_dates=" in text and env.refreshed
    payload = json.loads((env.out / "feature_reconciliation.json").read_text(encoding="utf-8"))
    assert payload["run_metadata"]["num_dates_reconciled"] == 2


def test_a_diverging_feature_is_named_as_an_offender(env, capsys):
    _history(env.root / "book.jsonl", [["2025-01-02", "2025-01-03"]])
    _dataset(env.root / "full.csv")
    frame = pd.read_csv(env.root / "full.csv")
    frame["rsi_14"] = [60.0, 61.0, 62.0]
    frame["momentum_20"] = 0.1
    frame.to_csv(env.root / "full.csv", index=False)
    assert aq_cli.cmd_evaluate(_args(env)) == 0
    assert "Worst offenders by divergence count" in capsys.readouterr().out


def test_every_run_can_be_reconciled_and_json_is_printed(env, capsys):
    _history(env.root / "book.jsonl", [["2025-01-03", "2025-01-06"], ["2025-01-02", "2025-01-03"]])
    _dataset(env.root / "full.csv")
    assert aq_cli.cmd_evaluate(_args(env, reconcile_all_runs=True)) == 0
    assert len(json.loads((env.out / "feature_reconciliation.json").read_text(encoding="utf-8"))["all_runs"]) == 2
    assert aq_cli.cmd_evaluate(argparse.Namespace(**{**vars(_args(env)), "json": True})) == 0
    assert '"run_metadata"' in capsys.readouterr().out


def test_missing_snapshots_and_missing_dataset_rows_are_reported(env, capsys):
    _history(env.root / "book.jsonl", [["2025-01-02"]], symbol="MSFT")
    _dataset(env.root / "full.csv")
    assert aq_cli.cmd_evaluate(_args(env)) == 0
    err = capsys.readouterr().err
    assert "NO comparable snapshots found for AAPL" in err and "snapshot keys seen" in err
    _history(env.root / "book.jsonl", [["2030-01-02"]])
    assert aq_cli.cmd_evaluate(_args(env)) == 0
    assert "had no matching" in capsys.readouterr().out


def test_a_late_bar_symbol_is_compared_with_the_previous_dataset_row(env, capsys):
    _history(env.root / "book.jsonl", [["2025-01-03", "2025-01-06"]], symbol="BTCUSD")
    _dataset(env.root / "full.csv", symbol="BTCUSD")
    args = ns(reconcile_features=True, symbol="BTCUSD", book_history_path=str(env.root / "book.jsonl"), dataset=str(env.root / "full.csv"))
    assert aq_cli.cmd_evaluate(args) == 0
    assert "is a crypto symbol" in capsys.readouterr().out


def test_the_default_history_is_the_newest_per_run_file(env, capsys):
    per_run = env.root / "visualization" / "book_history"
    per_run.mkdir(parents=True)
    _history(per_run / "2025-01-01.jsonl", [["2025-01-02"]])
    _dataset(env.root / "full.csv")
    assert aq_cli.cmd_evaluate(ns(reconcile_features=True, symbol="aapl", dataset=str(env.root / "full.csv"))) == 0
    assert "1 record(s) carried a feature_snapshot" in capsys.readouterr().out


def test_undated_records_fold_into_a_run_and_a_non_mapping_snapshot_is_skipped(env, capsys):
    _dataset(env.root / "full.csv")
    (env.root / "book.jsonl").write_text(json.dumps({"x": 1}) + "\n", encoding="utf-8")
    assert aq_cli.cmd_evaluate(_args(env)) == 0
    (env.root / "book.jsonl").write_text(json.dumps({"date": "2025-01-02", "feature_snapshot": {"AAPL": 5}}) + "\n", encoding="utf-8")
    _dataset(env.root / "full.csv")
    assert aq_cli.cmd_evaluate(_args(env)) == 0


def test_a_feature_the_offline_row_never_had_is_named(env, capsys):
    (env.root / "book.jsonl").write_text(json.dumps({"date": "2025-01-02", "feature_snapshot": {"AAPL": {"rsi_14": 55.0, "mystery_feature": 3.0}}}) + "\n", encoding="utf-8")
    _dataset(env.root / "full.csv")
    assert aq_cli.cmd_evaluate(_args(env)) == 0
    assert "NEVER in the offline row" in capsys.readouterr().out


def test_a_forex_tick_on_a_fill_forward_bar_keeps_only_the_payload(env, monkeypatch, capsys):
    import evaluation.live_parity as live_parity

    config = json.loads((env.root / "config.json").read_text(encoding="utf-8"))
    config["phase1"]["universe"]["assets"].append({"ticker": "EURUSD", "security_type": "forex", "asset_class": "forex"})
    (env.root / "config.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(live_parity, "forex_tick_holds_fill_forward_bar", lambda date, previous, holidays: True)
    seen = []
    monkeypatch.setattr(live_parity, "forex_monday_payload_only", lambda row, prefixes: seen.append(True) or row)
    _history(env.root / "book.jsonl", [["2025-01-03", "2025-01-06"]], symbol="EURUSD")
    _dataset(env.root / "full.csv", symbol="EURUSD")
    args = ns(reconcile_features=True, symbol="EURUSD", book_history_path=str(env.root / "book.jsonl"), dataset=str(env.root / "full.csv"))
    assert aq_cli.cmd_evaluate(args) == 0 and seen and "is a forex symbol" in capsys.readouterr().out
