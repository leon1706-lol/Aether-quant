"""lab/run_evaluation.py: a run is judged on its out-of-sample rows (IC, decay, quintiles, the overfit gap, a cost-aware
book at N), runs are compared on common rows, and a model card states the run's own numbers."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lab import run_evaluation as ev
from lab import trainer
from lab_world import make_lab


@pytest.fixture(scope="module")
def evaluated(tmp_path_factory):
    lab = make_lab(tmp_path_factory.mktemp("lab") / "lab")
    first = trainer.train_run(lab, "lin", seeds=[1], log=lambda line: None)
    second = trainer.train_run(lab, "lin", overrides={"model": {"ridge": 100.0}, "data": {"features": ["ret_1", "vol_20"]}}, seeds=[1], log=lambda line: None)
    return lab, lab / "runs" / first["id"], lab / "runs" / second["id"]


def test_a_run_is_judged_on_its_out_of_sample_rows(evaluated):
    lab, run, _ = evaluated
    report = ev.evaluate_run(run, lab_dir=lab, book=True, cost_bps=5.0)
    assert report["ic"]["mean"] > 0.1 and report["ic"]["t_hac"] > 2 and len(report["ic"]["ci95"]) == 2
    assert set(report["ic_by_split"]) == {"validation", "backtest"} and set(report["ic_by_year"]) <= {"2020", "2021", "2022"}
    assert set(report["decay"]) == {1, 5, 20} and list(report["quintile_mean_return_1d"]) == [1, 2, 3, 4, 5]
    assert report["overfit_gap"]["best_validation_ic"] is None, "a linear run has no epochs"
    book = report["book"]
    assert book["sharpe"] is not None and 0.0 <= book["psr"] <= 1.0 and book["trials_n"] == 2 and "dsr" in book
    text = ev.render_eval(report)
    assert "out-of-sample IC" in text and "DSR at N=2" in text
    page = ev.render_eval_html(report)
    assert page.startswith("<!doctype html>") and "Quintile book after costs" in page
    assert ev.evaluate_run(run, lab_dir=lab)["book"] is None


def test_runs_are_compared_on_common_rows_against_the_best_and_a_baseline(evaluated):
    _, first, second = evaluated
    report = ev.compare_runs([first, second], baseline="momentum_20")
    names = [row["run"] for row in report["leaderboard"]]
    assert set(names) == {first.name, second.name, "momentum_20"} and report["rows"] > 1000
    best, *rest = report["leaderboard"]
    assert best["diff"] == 0.0 and best["t_hac"] is None and all(row["diff"] <= 0 for row in rest)
    assert all(row["ci95"] is not None for row in rest)
    assert "vs best" in ev.render_compare(report)
    with pytest.raises(KeyError, match="no baseline"):
        ev.baseline_scores(pd.DataFrame({"x": [1]}), "nothing")
    assert ev.baseline_scores(pd.DataFrame({"rev_5": [1.0]}), "reversal_5").tolist() == [1.0]
    assert ev.baseline_scores(pd.DataFrame({"own": [2.0]}), "own").tolist() == [2.0]


def test_the_model_card_states_the_runs_own_numbers(evaluated):
    _, run, _ = evaluated
    card = ev.model_card(run)
    assert card.startswith("# Model card: lin") and "Out-of-sample IC" in card and "Intended use" in card and "N = " in card


def test_the_statistics_handle_thin_and_flat_series():
    assert ev.half_life({1: 0.1, 5: 0.06, 20: 0.02}) == pytest.approx(5 + (0.06 - 0.05) / 0.04 * 15)
    assert ev.half_life({1: 0.1, 5: 0.1, 20: 0.05}) == 20.0
    assert ev.half_life({1: -0.1}) is None and ev.half_life({1: 0.1, 5: 0.09}) is None and ev.half_life({}) is None
    assert ev.ic_stats(pd.Series([0.1]), horizon=5) == {"mean": 0.1, "days": 1, "t_hac": None, "ci95": None}
    flat = ev.sharpe_block(pd.Series([0.01, 0.01, 0.01], index=["2024-01-01", "2024-01-02", "2024-01-03"]), trials_n=5, trial_variance=None)
    assert flat == {"days": 3, "sharpe": None}
    returns = pd.Series(np.random.default_rng(2).normal(0.001, 0.01, 300), index=[str(day.date()) for day in pd.date_range("2024-01-01", periods=300)])
    single = ev.sharpe_block(returns, trials_n=1, trial_variance=0.5)
    assert single["hurdle_sharpe"] == 0.0 and single["dsr"] is None, "one trial has no deflation"
    many = ev.sharpe_block(returns, trials_n=50, trial_variance=0.5)
    assert many["hurdle_sharpe"] > 0 and many["dsr"] is not None and many["min_track_record_days"] > 0
    frame = pd.DataFrame({"date": ["d1"] * 3, "ticker": ["a", "b", "c"], "s": [1, 2, 3], "target_return_1d": [0.1, 0.2, 0.3]})
    assert ev.spread_returns(frame, "s").empty, "fewer than four names a day make no quintile book"
    assert ev.daily_ic(frame["s"], frame["target_return_1d"], frame["date"], min_names=4).empty and len(ev.daily_ic(frame["s"], frame["target_return_1d"], frame["date"])) == 1


def test_the_trial_variance_reads_the_ledger_candidates(tmp_path):
    from evaluation.trial_ledger import append_trial

    ledger = tmp_path / "trials.jsonl"
    assert ev.trial_variance(ledger) is None
    for index, sharpe in enumerate((0.1, 0.5, 0.9)):
        append_trial(ledger, trial_id=f"t{index}", track="lab", window="w", role="candidate", annualised_sharpe=sharpe, n_obs=10)
    assert ev.trial_variance(ledger) == pytest.approx(np.var([0.1, 0.5, 0.9], ddof=1))
