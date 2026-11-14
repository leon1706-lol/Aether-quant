"""aq evaluate --reconcile-book-history (V6.6.6, #359): the logged book against an offline re-derivation, with the model and the
reconciliation maths stubbed. The test checks the segmentation, the context, the mode and everything the command prints."""

from __future__ import annotations

import argparse
import json

import pandas as pd

import aq_cli
from test_aq_cli_evaluate_lean import env, ns  # noqa: F401  (the fixture and the namespace builder)

SUMMARY = {
    "num_dates": 2, "num_dates_live_vetoed": 1, "live_veto_reasons": {"gate": 1}, "num_dates_exact_match": 1, "num_dates_compared": 1, "mean_overlap_fraction": 0.5,
    "mean_raw_score_delta_abs": 0.01, "mean_weight_delta_abs": 0.02, "num_dates_with_weight_logged": 1, "num_symbols_only_logged_total": 0, "num_symbols_only_offline_total": 1,
}
UNIVERSE = {"num_dates_with_universe_data": 2, "by_security_type": {"equity": {"mean_raw_rank_score": 0.5, "feature_ready_rate": 1.0, "trading_eligible_rate": 0.9, "num_symbol_dates": 8}}}
DIVERSION = {"num_records_with_decisions": 1, "total_book_member_dates": 3, "action_counts": {"hold": 2, "trade": 1}, "reason_counts": {"cooldown": 1}}
PRESENCE = {"num_runs_detected": 1, "runs": [{"absence_rate_by_symbol": {"AAA": 0.25, "BBB": 0.0}}]}


def _log(path, runs):
    lines = [json.dumps({"date": date, "run_id": index}) for index, run in enumerate(runs) for date in run]
    path.write_text("\n".join(lines) + "\n\nnot json\n", encoding="utf-8")


def _setup(env, monkeypatch, runs=(("2025-01-02", "2025-01-03"),)):
    import evaluation
    import portfolio.rank_signal as rank_signal

    _log(env.root / "book.jsonl", runs)
    dates = ["2024-12-30", "2025-01-02", "2025-01-03"]
    frame = pd.DataFrame({"date": dates * 2, "ticker": ["AAA"] * 3 + ["BBB"] * 3, "training_eligible": True, "split": "backtest"})
    frame.to_csv(env.root / "full.csv", index=False)
    (env.root / "ml" / "multitask_model.json").write_text("{}", encoding="utf-8")
    (env.root / "ml" / "multitask_feature_schema.json").write_text(json.dumps({"model_input_names": ["x"]}), encoding="utf-8")
    (env.root / "ml" / "multitask_training_metrics.json").write_text("{}", encoding="utf-8")
    calls = {"independent": 0, "replay": 0}
    monkeypatch.setattr(rank_signal, "resolve_rank_signal_policy", lambda metrics, config: {"heads": {"rank_20d": 1.0, "off": 0.0}, "model_priority": ["multitask", "sequence"]})
    monkeypatch.setattr(evaluation, "predict_heads", lambda dataset, export, names, heads, **kwargs: {"rank_20d": [0.0] * len(dataset)})
    monkeypatch.setattr(evaluation, "compute_blended_raw_scores", lambda dataset, predictions, policy: [0.1 * (index % 3) for index in range(len(dataset))])
    monkeypatch.setattr(evaluation, "select_context_date_range", lambda dataset, recorded, window_size: ("2024-12-30", "2025-01-03"))
    monkeypatch.setattr(evaluation, "reconcile_book_history_date", lambda record, scores, top_n, bottom_n: calls.__setitem__("independent", calls["independent"] + 1) or {"date": record["date"]})
    monkeypatch.setattr(evaluation, "replay_book_history_reconciliation", lambda records, scores, **kwargs: calls.__setitem__("replay", calls["replay"] + 1) or [{"date": r["date"]} for r in records])
    monkeypatch.setattr(evaluation, "summarize_book_history_reconciliation", lambda results: dict(SUMMARY))
    monkeypatch.setattr(evaluation, "summarize_universe_snapshot_by_security_type", lambda records: dict(UNIVERSE))
    monkeypatch.setattr(evaluation, "summarize_book_member_diversion", lambda records: dict(DIVERSION))
    monkeypatch.setattr(evaluation, "summarize_universe_presence_by_symbol", lambda records: dict(PRESENCE))
    return calls


def _args(env, **extra):
    return ns(reconcile_book_history=True, book_history_path=str(env.root / "book.jsonl"), dataset=str(env.root / "full.csv"), **extra)


def test_the_most_recent_run_is_reconciled_independently_and_printed(env, monkeypatch, capsys):
    calls = _setup(env, monkeypatch)
    assert aq_cli.cmd_evaluate(_args(env)) == 0
    text = capsys.readouterr().out
    for fragment in ("replays NO hysteresis", "Reconciled run (", "live VETOED 1/2 dates", "exact_match=1/1", "Universe snapshot", "equity: mean_raw_rank_score", "Book-member diversion", "action=hold: 2",
                     "reason=cooldown: 1", "AAA: absent from universe on 25.0%"):
        assert fragment in text, fragment
    assert "BBB:" not in text and calls["independent"] == 2 and calls["replay"] == 0 and env.refreshed
    assert json.loads((env.out / "book_history_reconciliation.json").read_text(encoding="utf-8"))["mode"] == "independent"


def test_the_hysteresis_replay_and_every_run_and_json_output(env, monkeypatch, capsys):
    calls = _setup(env, monkeypatch, runs=(("2025-01-02", "2025-01-03"), ("2025-01-02",)))
    assert aq_cli.cmd_evaluate(_args(env, replay_hysteresis=True, reconcile_all_runs=True, hysteresis_survives_veto=True)) == 0
    text = capsys.readouterr().out
    assert "REPLAYS hysteresis" in text and "Run 1/2 (" in text and "Run 2/2 (" in text and calls["replay"] == 2
    assert len(json.loads((env.out / "book_history_reconciliation.json").read_text(encoding="utf-8"))["all_runs"]) == 2
    assert aq_cli.cmd_evaluate(argparse.Namespace(**{**vars(_args(env)), "json": True})) == 0
    assert '"mode": "independent"' in capsys.readouterr().out


def test_a_run_with_nothing_to_show_prints_only_the_headline(env, monkeypatch, capsys):
    import evaluation

    _setup(env, monkeypatch)
    monkeypatch.setattr(evaluation, "summarize_book_history_reconciliation", lambda results: {**SUMMARY, "num_dates_live_vetoed": 0})
    monkeypatch.setattr(evaluation, "summarize_universe_snapshot_by_security_type", lambda records: {"num_dates_with_universe_data": 0, "by_security_type": {}})
    monkeypatch.setattr(evaluation, "summarize_book_member_diversion", lambda records: {**DIVERSION, "num_records_with_decisions": 0})
    monkeypatch.setattr(evaluation, "summarize_universe_presence_by_symbol", lambda records: {"num_runs_detected": 0, "runs": []})
    assert aq_cli.cmd_evaluate(_args(env)) == 0
    text = capsys.readouterr().out
    assert "live VETOED" not in text and "Universe snapshot" not in text and "Book-member diversion" not in text


def test_bad_inputs_are_explained(env, monkeypatch, capsys):
    _setup(env, monkeypatch)
    assert aq_cli.cmd_evaluate(ns(reconcile_book_history=True, book_history_path=str(env.root / "none.jsonl"))) == 1 and "not found" in capsys.readouterr().err
    (env.root / "empty.jsonl").write_text("\n", encoding="utf-8")
    assert aq_cli.cmd_evaluate(ns(reconcile_book_history=True, book_history_path=str(env.root / "empty.jsonl"))) == 1 and "no usable records" in capsys.readouterr().err
    (env.root / "undated.jsonl").write_text(json.dumps({"x": 1}) + "\n", encoding="utf-8")
    assert aq_cli.cmd_evaluate(ns(reconcile_book_history=True, book_history_path=str(env.root / "undated.jsonl"))) == 1
    assert aq_cli.cmd_evaluate(_args(env, reconcile_run_index=9)) == 1 and "out of range" in capsys.readouterr().err
    assert aq_cli.cmd_evaluate(ns(reconcile_book_history=True, book_history_path=str(env.root / "book.jsonl"), dataset=str(env.root / "gone.csv"))) == 1
    assert "aq train --dataset-only" in capsys.readouterr().err


def test_a_model_without_artifacts_is_skipped_quietly(env, monkeypatch, capsys):
    _setup(env, monkeypatch)
    (env.root / "ml" / "multitask_model.json").unlink()
    assert aq_cli.cmd_evaluate(_args(env)) == 0 and "Reconciled run" in capsys.readouterr().out
