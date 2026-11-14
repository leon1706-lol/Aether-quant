"""scripts/gate_value_compare.py (V6.6.6): the live gate's reading against the offline one, with a stand-in harness."""

from __future__ import annotations

import json
import sys
import types

from script_loader import load_script, run_script


def test_live_values_keep_the_last_reading_of_a_date_and_drop_non_finite():
    module = load_script("gate_value_compare")
    history = [
        {"date": "2024-01-02T00:00", "rolling_ic": {"rolling_mean_ic": 0.1, "num_resolved_dates": 25}},
        {"date": "2024-01-02", "rolling_ic": {"rolling_mean_ic": 0.2, "num_resolved_dates": 26}, "gate_veto_reason": "low"},
        {"date": "2024-01-03", "rolling_ic": {"rolling_mean_ic": float("nan")}},
        {"date": "2024-01-04", "rolling_ic": "missing"},
    ]
    assert module.live_gate_values(history) == {
        "2024-01-02": {"value": 0.2, "resolved": 26, "veto_reason": "low"},
        "2024-01-03": {"value": None, "resolved": 0, "veto_reason": None},
    }


def test_compare_needs_three_dates_and_reports_agreement():
    module = load_script("gate_value_compare")
    live = {f"2024-01-0{day}": {"value": value, "resolved": 30} for day, value in ((1, 0.1), (2, 0.2), (3, 0.3), (4, 0.4))}
    assert module.compare_values(live, {"2024-01-01": 0.1}, 0.0, 20) == {"dates": 1}
    report = module.compare_values(live, {"2024-01-01": 0.1, "2024-01-02": 0.2, "2024-01-03": 0.3, "2024-01-04": -0.4}, 0.0, 20)
    assert report["dates"] == 4 and report["same_side_of_floor_share"] == 0.75 and report["largest_differences"][0]["date"] == "2024-01-04"
    flat = module.compare_values(live, dict.fromkeys(live, 0.5), 0.0, 20)
    assert flat["correlation"] is None


def test_main_scores_the_book_history_with_the_harness(tmp_path, monkeypatch, capsys):
    module = load_script("gate_value_compare")
    history = tmp_path / "book.jsonl"
    rows = [{"date": f"2024-01-0{day}", "rolling_ic": {"rolling_mean_ic": 0.1 * day, "num_resolved_dates": 30}} for day in range(1, 5)]
    history.write_text("\n".join(json.dumps(row) for row in rows) + "\n\n", encoding="utf-8")

    class Harness:
        def __init__(self, splits, *, dataset_path, config, gate_warmup_days):
            self.lagged_frame = object()
            self._states = {}

        def gate_for(self, frame):
            self._states[(id(frame), "x")] = lambda date: {"rolling_mean_ic": 0.05} if date != "2024-01-04" else None

    monkeypatch.setitem(sys.modules, "as_live_levers", types.SimpleNamespace(AsLiveHarness=Harness))
    out = tmp_path / "out" / "report.json"
    monkeypatch.setattr(module.sys, "argv", ["x", "--book-history", str(history), "--out", str(out)])
    assert module.main() == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["dates"] == 3 and report["splits"] == ["backtest", "holdout"] and '"dates": 3' in capsys.readouterr().out


def test_help_runs_as_a_script(monkeypatch, capsys):
    assert run_script("gate_value_compare", ["--help"], monkeypatch) == 0
    assert "--book-history" in capsys.readouterr().out
