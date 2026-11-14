"""scripts/holdout_report.py's runtime (V6.6.6, #359): the IC summary of a holdout head and the one-look report with and without the book, with the model passes and
the as-live harness stood in. The report is written to a temporary path, so the real `ml/evaluation/holdout_report.json` is never overwritten."""

from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from script_loader import load_script

TICKERS = [f"E{n:02d}" for n in range(12)] + ["EURUSD", "GBPUSD", "BTCUSD"]
DATES = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2025-07-01", periods=60)]
CONFIG = {"phase1": {"windows": {"holdout": {"start": "2025-07-01", "end": "2026-09-30"}},
                     "universe": {"assets": [{"ticker": ticker, "asset_class": "equity"} for ticker in TICKERS[:12]] + [{"ticker": "EURUSD", "security_type": "forex"}, {"ticker": "GBPUSD", "security_type": "forex"}, {"ticker": "BTCUSD", "security_type": "crypto"}]},
                     }, "phase_v2": {"sequence_model": {"window_size": 5}}}


@pytest.fixture
def module(monkeypatch, tmp_path):
    report = load_script("holdout_report")
    ml = tmp_path / "ml"
    (ml / "evaluation").mkdir(parents=True)
    monkeypatch.setattr(report, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(report, "ML_DIR", ml)
    (tmp_path / "config.json").write_text(json.dumps(CONFIG), encoding="utf-8")
    for kind in ("multitask", "sequence"):
        (ml / f"{kind}_model.json").write_text("{}", encoding="utf-8")
        (ml / f"{kind}_feature_schema.json").write_text(json.dumps({"model_input_names": ["a"]}), encoding="utf-8")
    rng = np.random.default_rng(4)
    rows = [{"date": date, "ticker": ticker, "split": "holdout", "training_eligible": True, "target_rank_5d": rng.random(), "target_rank_20d": rng.random()} for date in DATES for ticker in TICKERS]
    rows += [{"date": "2025-06-01", "ticker": "E00", "split": "backtest", "training_eligible": True, "target_rank_5d": 0.5, "target_rank_20d": 0.5}]
    pd.DataFrame(rows).to_csv(tmp_path / "dataset.csv", index=False)
    return report


def test_the_ic_summary_gives_daily_and_non_overlapping_figures(module):
    rng = np.random.default_rng(1)
    frame = pd.DataFrame([{"date": date, "ticker": ticker, "p": rng.random(), "t": rng.random()} for date in DATES for ticker in TICKERS])
    summary = module.ic_summary(frame, "p", "t", 5)
    assert summary["num_dates"] == len(DATES) and summary["non_overlapping_dates"] < summary["num_dates"] and summary["hac_t"] is not None


def _stand_ins(monkeypatch, module):
    monkeypatch.setattr(module, "predict_heads", lambda frame, export, names, heads, model_kind, sequence_feature_schema, configured_window_size, batched: {head: np.random.default_rng(3).random(len(frame)) for head in heads})


def test_the_report_scores_each_model_head_overall_and_by_class_with_enough_names(module, monkeypatch, tmp_path, capsys):
    _stand_ins(monkeypatch, module)
    out = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["holdout_report", "--dataset", str(tmp_path / "dataset.csv"), "--output", str(out)])
    assert module.main() == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    by_class = written["models"]["multitask"]["rank_20d"]["by_asset_class"]
    assert written["split_label"] == "holdout" and written["tickers"] == 15 and set(written["models"]) == {"multitask", "sequence"} and set(by_class) == {"equity", "forex"} and "as_live_book" not in written
    assert "multitask/rank_5d" in capsys.readouterr().out


def test_the_book_is_added_on_request_and_the_readme_is_refreshed_only_for_the_real_report_path(module, monkeypatch, tmp_path, capsys):
    import evaluation.readme_research as readme_research

    _stand_ins(monkeypatch, module)
    levers = types.ModuleType("as_live_levers")
    levers.AsLiveHarness = lambda split, dataset_path, use_cache: SimpleNamespace(as_live=lambda: "as_live", idealized=lambda: "ideal")
    levers.summarize = lambda result: {"net_sharpe": 0.5, "which": result}
    monkeypatch.setitem(sys.modules, "as_live_levers", levers)
    refreshed = []
    monkeypatch.setattr(readme_research, "refresh_readme_best_effort", lambda: refreshed.append(True))
    monkeypatch.setattr(sys, "argv", ["holdout_report", "--dataset", str(tmp_path / "dataset.csv"), "--models", "multitask", "--book", "--output", str(tmp_path / "book.json")])
    assert module.main() == 0
    written = json.loads((tmp_path / "book.json").read_text(encoding="utf-8"))
    assert written["as_live_book"]["which"] == "as_live" and written["idealized_book"]["which"] == "ideal" and refreshed == [] and set(written["models"]) == {"multitask"}
    monkeypatch.setattr(sys, "argv", ["holdout_report", "--dataset", str(tmp_path / "dataset.csv"), "--models", "multitask"])
    assert module.main() == 0 and refreshed == [True] and (tmp_path / "ml" / "evaluation" / "holdout_report.json").exists()
