"""scripts/lean_calibration.py (V6.0.0, rule R-CAL): the pure pieces of the offline-vs-Lean comparison."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("lean_calibration", ROOT / "scripts" / "lean_calibration.py")
calibration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calibration)


def test_window_spec():
    window = calibration.parse_window("bt=backtests/run@2023-07-01..2025-06-30:backtest+holdout")
    assert window == {"name": "bt", "run_dir": "backtests/run", "start": "2023-07-01", "end": "2025-06-30",
                      "splits": ("backtest", "holdout")}
    assert calibration.parse_window("p=@2023-07-01..2026-09-30:backtest")["run_dir"] is None
    with pytest.raises(ValueError):
        calibration.parse_window("broken")


def test_lean_calendar_days_are_summed_into_the_offline_return_buckets():
    lean = {"2024-01-05": 0.01, "2024-01-06": 0.002, "2024-01-07": 0.003, "2024-01-08": -0.004, "2024-01-04": 0.5}
    buckets = calibration.bucket_to_offline_dates(lean, ["2024-01-04", "2024-01-05", "2024-01-08"])
    # offline D covers (D, next D]: Friday's bucket holds the weekend and Monday
    assert buckets == {"2024-01-04": pytest.approx(0.01), "2024-01-05": pytest.approx(0.002 + 0.003 - 0.004), "2024-01-08": 0.0}


def test_live_decisions_need_a_formed_book_to_count_as_locked():
    reduce = {"action": "reduce_risk", "reasons": ["kill_switch_rolling_sharpe_below_floor"]}
    history = [
        {"date": "2023-06-30", "allocations": {}, "gate_veto_reason": "thin_universe_or_zero_top_n"},
        {"date": "2023-07-03", "allocations": {"A": {}}, "book_member_decisions": {"A": {"action": "trade", "reasons": []}}},
        {"date": "2023-07-17", "allocations": {"A": {}}, "book_member_decisions": {"A": reduce}},
        {"date": "2023-07-31", "allocations": {}, "gate_veto_reason": "rolling_ic_below_floor", "book_member_decisions": {"A": reduce}},
    ]
    assert calibration.live_decisions(history, "2023-07-01", "2023-12-31") == {
        "2023-07-03": "engaged", "2023-07-17": "locked", "2023-07-31": "vetoed"
    }


def test_agreement_is_binary_by_default_and_a_missing_date_disagrees():
    live = {"a": "engaged", "b": "locked", "c": "vetoed", "d": "engaged"}
    offline = {"a": "engaged", "b": "vetoed", "c": "locked"}
    assert calibration.decision_agreement(live, offline) == pytest.approx(3 / 4)
    assert calibration.decision_agreement(live, offline, binary=False) == pytest.approx(1 / 4)
    assert calibration.decision_agreement({}, offline) is None
    assert calibration.offline_decisions([
        {"date": "a", "engaged": True, "locked": False}, {"date": "b", "engaged": True, "locked": True},
        {"date": "c", "engaged": False, "locked": True},
    ]) == {"a": "engaged", "b": "locked", "c": "vetoed"}


def test_the_phase_puts_the_offline_cadence_on_lives_first_rebalance():
    dates = [f"d{index:02d}" for index in range(30)]
    assert calibration.rebalance_phase("d00", dates, 10) == 0
    assert calibration.rebalance_phase("d03", dates, 10) == 7  # counter 7 + 3 steps = 10 on d03
    assert calibration.rebalance_phase("missing", dates, 10) == 0


def test_comparison_and_the_rule():
    dates = ["a", "b", "c", "d"]
    row = calibration.compare({"a": 0.01, "b": -0.01, "c": 0.02, "d": 0.0}, dates, [0.012, -0.008, 0.018, 0.001])
    assert row["daily_correlation"] > 0.95 and row["days"] == 4
    passing = {"daily_correlation": 0.6, "annual_return_gap": -0.019, "decision_agreement": 0.8}
    assert calibration.window_passes(passing)
    assert not calibration.window_passes(dict(passing, decision_agreement=0.79))
    assert not calibration.window_passes(dict(passing, annual_return_gap=0.021))
    assert not calibration.window_passes(dict(passing, daily_correlation=None))


def test_disagreements_carry_the_offline_reason_and_missing_dates_are_counted_apart():
    live = {"d1": "engaged", "d2": "vetoed", "d3": "engaged", "d4": "engaged"}
    log = [
        {"date": "d1", "engaged": True, "reason": None, "locked": False},
        {"date": "d2", "engaged": True, "reason": None, "locked": False},
        {"date": "d3", "engaged": False, "reason": "rolling_ic_below_floor", "locked": False},
    ]
    table = calibration.disagreement_table(live, log)
    assert table["disagreements"] == {"vetoed->engaged (none)": 1, "engaged->vetoed (rolling_ic_below_floor)": 1}
    assert table["missing_offline"] == 1 and table["missing_offline_dates"] == ["d4"]


def test_a_window_is_simulated_with_its_own_run_config(tmp_path, monkeypatch):
    run = tmp_path / "backtests" / "run" / "code"
    run.mkdir(parents=True)
    (run / "config.json").write_text('{"snapshot": true}', encoding="utf-8")
    monkeypatch.setattr(calibration, "ROOT_DIR", tmp_path)
    assert calibration.window_config({"run_dir": "backtests/run"}, {"current": True}) == {"snapshot": True}
    assert calibration.window_config({"run_dir": None}, {"current": True}) == {"current": True}


def test_component_returns_follow_the_requested_components():
    components = {"2024-01-02": {"main_book": 10.0, "legacy": 5.0, "bond_sleeve": 100.0}}
    equity = [("2024-01-01", 1000.0), ("2024-01-02", 1015.0)]
    assert calibration.lean_book_returns(components, equity) == {"2024-01-02": pytest.approx(0.01)}
    assert calibration.lean_book_returns(components, equity, calibration.RCAL2_COMPONENTS) == {"2024-01-02": pytest.approx(0.015)}
