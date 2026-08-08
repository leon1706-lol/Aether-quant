import json

from monitoring.evaluation_state import build_evaluation_state


def test_every_section_degrades_to_not_evaluated_on_a_fresh_checkout(tmp_path):
    state = build_evaluation_state(ml_dir=tmp_path)

    for key in (
        "rank_book", "capacity", "stress", "ablation", "walk_forward",
        "book_spread_calibration", "book_history_reconciliation",
    ):
        assert state[key]["status"] == "not_evaluated"
        assert "hint" in state[key]


def test_never_raises_when_ml_dir_does_not_exist(tmp_path):
    missing_dir = tmp_path / "does_not_exist_at_all"
    state = build_evaluation_state(ml_dir=missing_dir)
    assert state["rank_book"]["status"] == "not_evaluated"


def test_rank_book_section_reads_the_real_report_file(tmp_path):
    evaluation_dir = tmp_path / "evaluation"
    evaluation_dir.mkdir(parents=True)
    payload = {"gross_sharpe": 1.1, "net_sharpe": 0.4, "num_dates_used": 250}
    (evaluation_dir / "rank_book_simulation.json").write_text(json.dumps(payload), encoding="utf-8")

    state = build_evaluation_state(ml_dir=tmp_path)

    assert state["rank_book"] == payload
    assert state["capacity"]["status"] == "not_evaluated"


def test_capacity_section_reads_the_real_report_file(tmp_path):
    evaluation_dir = tmp_path / "evaluation"
    evaluation_dir.mkdir(parents=True)
    payload = {"capacity_usd": 500000.0, "binding_ticker": "XYZ", "per_top_n": []}
    (evaluation_dir / "capacity_report.json").write_text(json.dumps(payload), encoding="utf-8")

    state = build_evaluation_state(ml_dir=tmp_path)

    assert state["capacity"] == payload


def test_stress_section_wraps_the_bare_list_in_an_entries_key(tmp_path):
    evaluation_dir = tmp_path / "evaluation"
    evaluation_dir.mkdir(parents=True)
    payload = {"stress": [{"cost_multiplier": 1.0, "net_sharpe": 0.5}]}
    (evaluation_dir / "cost_stress_report.json").write_text(json.dumps(payload), encoding="utf-8")

    state = build_evaluation_state(ml_dir=tmp_path)

    assert state["stress"] == {"entries": payload["stress"]}


def test_walk_forward_section_picks_the_most_recently_modified_summary(tmp_path):
    versions_dir = tmp_path / "versions"
    older_dir = versions_dir / "walk-forward-aaa"
    newer_dir = versions_dir / "walk-forward-bbb"
    older_dir.mkdir(parents=True)
    newer_dir.mkdir(parents=True)

    (older_dir / "walk_forward_summary.json").write_text(json.dumps({"run_id": "aaa"}), encoding="utf-8")
    newer_path = newer_dir / "walk_forward_summary.json"
    newer_path.write_text(json.dumps({"run_id": "bbb"}), encoding="utf-8")

    # Force distinct mtimes so "most recent" is unambiguous regardless of
    # filesystem timestamp resolution.
    import os
    import time

    time.sleep(0.05)
    os.utime(newer_path, None)

    state = build_evaluation_state(ml_dir=tmp_path)

    assert state["walk_forward"]["run_id"] == "bbb"


def test_malformed_json_report_degrades_to_not_evaluated_never_raises(tmp_path):
    evaluation_dir = tmp_path / "evaluation"
    evaluation_dir.mkdir(parents=True)
    (evaluation_dir / "rank_book_simulation.json").write_text("{not valid json", encoding="utf-8")

    state = build_evaluation_state(ml_dir=tmp_path)

    assert state["rank_book"]["status"] == "not_evaluated"


def test_book_spread_calibration_section_reads_the_real_report_file(tmp_path):
    evaluation_dir = tmp_path / "evaluation"
    evaluation_dir.mkdir(parents=True)
    payload = {"calibrated_min_rank_confidence_spread": 0.5, "num_dates_used": 10}
    (evaluation_dir / "book_spread_calibration.json").write_text(json.dumps(payload), encoding="utf-8")

    state = build_evaluation_state(ml_dir=tmp_path)

    assert state["book_spread_calibration"] == payload


def test_book_history_reconciliation_section_reads_the_real_report_file(tmp_path):
    evaluation_dir = tmp_path / "evaluation"
    evaluation_dir.mkdir(parents=True)
    payload = {
        "mode": "independent",
        "per_date": [],
        "summary": {"num_dates": 0},
        "universe_summary": {"num_dates_with_universe_data": 0, "by_security_type": {}},
    }
    (evaluation_dir / "book_history_reconciliation.json").write_text(json.dumps(payload), encoding="utf-8")

    state = build_evaluation_state(ml_dir=tmp_path)

    assert state["book_history_reconciliation"] == payload
