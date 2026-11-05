"""evaluation/trial_registry.py (moved from scripts/build_trial_registry.py in V6.4.3)."""

from __future__ import annotations

import json

from evaluation.trial_registry import build_registry, collect_trials, dedupe


def test_collects_backtest_summaries_and_dedupes_repeats(tmp_path):
    phase = tmp_path / "v999"
    phase.mkdir()
    payload = {"stage": {"a": {"backtest": {"median_net_sharpe": 0.3}, "validation": {"median_net_sharpe": 9.0}},
                         "b": {"backtest": {"median_net_sharpe": 0.3}}, "c": [{"backtest": {"median_net_sharpe": -0.1}}]}}
    (phase / "research.json").write_text(json.dumps(payload), encoding="utf-8")
    registry = build_registry(tmp_path)
    assert registry["num_trials"] == 2
    assert sorted(trial["median_sharpe"] for trial in registry["trials"]) == [-0.1, 0.3]


def test_non_finite_summaries_are_ignored():
    assert collect_trials({"x": {"backtest": {"median_net_sharpe": float("nan")}}}, "v1") == []
    assert dedupe([]) == []


def test_a_phase_ledger_adds_its_candidates_and_no_nulls(tmp_path):
    from evaluation.trial_ledger import append_trial
    from evaluation.trial_registry import build_registry

    path = tmp_path / "v650" / "trial_ledger.jsonl"
    append_trial(path, trial_id="a", track="T3", window="selection", role="candidate", annualised_sharpe=0.1, n_obs=10)
    append_trial(path, trial_id="a", track="T3", window="selection", role="candidate", annualised_sharpe=0.2, n_obs=10)
    append_trial(path, trial_id="b", track="T3", window="selection", role="candidate", annualised_sharpe=None, n_obs=10)
    append_trial(path, trial_id="c", track="T3", window="selection", role="placebo", annualised_sharpe=5.0, n_obs=10)
    append_trial(path, trial_id="d", track="T3", window="plumbing", role="plumbing", annualised_sharpe=5.0, n_obs=10)

    registry = build_registry(tmp_path)

    assert registry["num_trials"] == 1
    assert registry["trials"][0]["trial"] == "a"
    assert registry["trials"][0]["median_sharpe"] == 0.2
