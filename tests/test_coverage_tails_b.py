"""More last branches of small modules (V6.6.6, #359): malformed numbers, empty groups, short inputs and unknown labels, each with the output the module gives for them."""

from __future__ import annotations

import datetime
import json
import math

import numpy as np
import pandas as pd
import pytest

from audit import status_export
from evaluation import (
    ablation,
    class_ic_audit,
    factor_spanning,
    gate_audit,
    gate_replica_audit,
    generation_ledger,
    generation_registry,
    head_audit,
    impact_model,
    kill_switch_replay,
    lean_statistics,
    model_predictions,
    overfit_diagnostics,
    power_analysis,
    rank_ic_core,
    trade_bootstrap,
    trial_registry,
    volatility_threshold_calibration,
)
from execution import cost_model, cost_models, lean_config_render, live_credentials_io, order_gate, reconciliation, secrets
from features import training_splits
from portfolio import sleeve_guard


# ---- generation registry and ledger --------------------------------------------------------------------------------------


def generation(**changes):
    base = dict(id="g", kind="rule", tier="tier1", stage="shadow", born="2020-01-01", procedure_sha256="x", definition={}, needs="host")
    return generation_registry.Generation(**{**base, "definition": {"asset_class": {"A": "crypto"}, "initial_weights": {"A": 1.0}}, **changes})


def test_a_registry_entry_with_an_unknown_tier_is_refused(tmp_path):
    entry = {"id": "g", "kind": "rule", "tier": "gold", "stage": "shadow", "born": "2020", "procedure_sha256": "x"}
    (tmp_path / "registry.json").write_text(json.dumps({"generations": [entry]}), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown tier"):
        generation_registry.load_registry(tmp_path / "registry.json")


def test_a_stage_or_tier_outside_the_known_ones_changes_nothing_and_holds_no_share():
    evidence = generation_registry.AdmissionEvidence()
    assert generation_registry.next_stage(generation(stage="limbo"), evidence) == "limbo"
    assert generation_registry.share_cap(generation(tier="bronze", stage="active"), evidence) == 0.0


def test_a_holding_with_no_mark_counts_against_coverage_and_a_decision_cannot_earn_its_own_bar():
    marks = pd.DataFrame({"A": [1.0, 1.1]}, index=["d1", "d2"])
    result = generation_ledger.session_return_covered({"A": 0.5, "Z": 0.5}, marks, "d1", "d2", classes={"A": "crypto"}, traded={})
    assert result["coverage"] == pytest.approx(0.5) and result["session_return"] is None
    with pytest.raises(ValueError, match="can't earn the bar"):
        generation_ledger._lagged([], 0, {})


def test_the_first_session_of_a_generation_earns_nothing_and_is_fully_covered():
    marks = pd.DataFrame({"A": [1.0]}, index=["2020-01-02"])
    payload = generation_ledger.row_for_generation(generation(), [], "2020-01-02", ["2020-01-02"], marks, {})
    assert payload["session_return"] == 0.0 and payload["coverage"] == 1.0 and payload["status"] == "ok"


# ---- number guards -------------------------------------------------------------------------------------------------------


def test_a_malformed_sleeve_guard_setting_falls_back_to_its_default():
    config = sleeve_guard.resolve_sleeve_guard_config({"max_loss_fraction_nav": "abc", "lookback_bars": float("nan"), "cooldown_bars": None})
    assert config.max_loss_fraction_nav == 0.01 and config.lookback_bars == 60 and config.cooldown_bars == 60


def test_a_secret_is_only_equal_to_another_secret_and_hashes_by_length():
    assert secrets.SecretValue("abc") == secrets.SecretValue("abc") and secrets.SecretValue("abc") != "abc"
    assert hash(secrets.SecretValue("abc")) == hash(secrets.SecretValue("xyz")) != hash(secrets.SecretValue("abcd"))


def test_numbers_that_do_not_parse_are_dropped_by_each_guard():
    report = reconciliation.reconcile_positions({"A": "not a number", "B": 0.1}, {"A": 0.1, "B": 0.1}, weight_tolerance=0.01, value_tolerance_usd=10.0, portfolio_value=1000.0, max_tolerated_drift=0.5)
    assert report.breach and report.max_abs_weight_drift == math.inf and report.matched == ["B"]
    assert order_gate.resolve_slippage_bps("A", {"A": "abc"}) == 0.0
    assert cost_models._finite_non_negative("abc") is None and cost_models._finite_non_negative(-1.0) is None
    assert head_audit._finite("abc") is None and head_audit._finite(float("inf")) is None


def test_a_spearman_needs_two_observations_and_some_variance():
    assert class_ic_audit._spearman(np.array([1.0]), np.array([1.0])) is None
    assert class_ic_audit._spearman(np.array([1.0, 1.0, 1.0]), np.array([1.0, 2.0, 3.0])) is None


def test_dates_leave_the_dashboard_export_as_text_and_tuples_as_lists():
    assert status_export._json_safe({"when": datetime.date(2020, 1, 2), "pair": (datetime.datetime(2020, 1, 2, 3), 1)}) == {"when": "2020-01-02", "pair": ["2020-01-02T03:00:00", 1]}


def test_a_zero_volume_has_no_participation_and_no_history_has_no_confidence_to_report():
    assert impact_model.compute_participation_rate(trade_size_fraction=0.1, portfolio_value=100.0, avg_daily_dollar_volume=0.0) == 0.0
    assert kill_switch_replay.percentile([], 0.5) is None
    assert math.isinf(power_analysis.excluded_alpha_sharpe(2.0, 0.0))
    assert cost_model.expected_edge_bps(None, edge_bps_per_rank_unit=10.0, holding_bars=5, horizon_days=20) == 0.0


# ---- files and registries ------------------------------------------------------------------------------------------------


def test_an_unreadable_research_file_is_left_out_of_the_trial_registry(tmp_path):
    (tmp_path / "v1").mkdir()
    (tmp_path / "v1" / "research.json").write_text("{broken", encoding="utf-8")
    registry = trial_registry.build_registry(tmp_path)
    assert registry["sources"] == [] and registry["trials"] == []


def test_a_trade_with_a_non_numeric_amount_is_not_a_round_trip():
    run = {"totalPerformance": {"closedTrades": [{"symbols": [{"value": "AAPL"}], "profitLoss": "oops", "totalFees": 0.0, "entryPrice": 1.0, "quantity": 1.0}]}}
    assert trade_bootstrap.round_trips_from_closed_trades(run) == []


def test_an_interest_rate_row_that_is_not_a_date_is_skipped(tmp_path):
    path = tmp_path / "rates.csv"
    path.write_text("date,rate\nshort\n2020-01-02,5.0\nnot-a-date,1.0\n", encoding="utf-8")
    assert lean_statistics.load_interest_rate_changes(path) == [(datetime.date(2020, 1, 2), 0.05)]


def test_an_env_file_line_with_no_key_is_skipped():
    assert lean_config_render.parse_env_file("=orphan\nexport KEY = value\n# comment\n") == {"KEY": "value"}


def test_coinbase_credentials_resolve_like_the_other_broker_fields(monkeypatch):
    monkeypatch.setattr(live_credentials_io, "secret_env", lambda name, default, account_id=None: f"{name}:{account_id}")
    assert live_credentials_io.load_coinbase_credentials("acct") == {"coinbase_api_key": "COINBASE_API_KEY:acct", "coinbase_api_secret": "COINBASE_API_SECRET:acct"}


# ---- evaluation inputs ---------------------------------------------------------------------------------------------------


def test_a_rebalance_date_outside_the_sessions_is_kept_as_a_trade_day():
    profile = gate_replica_audit.trade_profile([], ["2020-02-01"], ["2020-01-01", "2020-01-02"], lag_sessions=1)
    assert profile["total"] == 0 and profile["median_sessions_between_trades"] is None


def test_rank_ic_skips_a_date_whose_predictions_are_all_equal():
    dates = np.array(["d1"] * 4 + ["d2"] * 4)
    predictions = np.array([1.0] * 4 + [1.0, 2.0, 3.0, 4.0])
    targets = np.array([1.0, 2.0, 3.0, 4.0] * 2)
    result = rank_ic_core.rank_ic_from_arrays(predictions, targets, dates, min_names_per_date=2)
    assert result["num_dates"] == 1


def test_a_context_window_that_starts_after_every_date_of_a_ticker_selects_nothing_from_it():
    dataset = pd.DataFrame({"ticker": ["A"] * 3, "date": ["2020-01-01", "2020-01-02", "2020-01-03"]})
    assert model_predictions.select_context_date_range(dataset, ["2021-01-01"], window_size=2) == ("2021-01-01", "2021-01-01")
    with pytest.raises(ValueError, match="at least one member"):
        model_predictions.predict_heads_ensemble(dataset, [], ["x"], ("rank_20d",))


def test_the_purged_folds_leave_out_the_horizon_before_and_the_embargo_after_each_validation_fold():
    dates = np.array(pd.date_range("2020-01-01", periods=20))
    folds = training_splits.purged_embargoed_folds(dates, n_folds=4, horizon_days=2, embargo_days=1)
    assert len(folds) == 4
    for train, validation in folds:
        assert set(train).isdisjoint(validation) and len(validation) == 5
    assert training_splits.purged_embargoed_folds(dates, n_folds=40, horizon_days=2) == []


def test_a_class_with_a_full_window_of_returns_gets_a_suggested_threshold_only_above_the_default():
    rng = np.random.default_rng(0)
    frame = pd.DataFrame({"ticker": ["A"] * 100 + ["B"] * 100, "date": list(pd.date_range("2020-01-01", periods=100).strftime("%Y-%m-%d")) * 2,
                          "close": list(100.0 * np.exp(np.cumsum(rng.normal(0, 0.05, 100)))) + list(100.0 * np.exp(np.cumsum(rng.normal(0, 0.001, 100))))})
    result = volatility_threshold_calibration.calibrate_elevated_volatility_thresholds(frame, {"A": "crypto", "B": "bond"}, min_samples=20, window=10)
    assert set(result["by_asset_class"]) == {"crypto", "bond"} and set(result["suggested_config"]) == {"default", "crypto"}
    assert volatility_threshold_calibration.calibrate_elevated_volatility_thresholds(frame.drop(columns=["close"]), {}, window=10)["status"] == "SKIPPED"


def test_the_learning_curve_skips_a_window_with_no_training_rows():
    frame = pd.DataFrame({"date": ["2015-01-01", "2022-03-01"], "split": ["train", "validation"]})
    curve = overfit_diagnostics.learning_curve(lambda train, evaluation: 0.5, frame, train_years=(1, 10), train_end="2021-12-31")
    assert curve == [{"train_years": 10, "train_rows": 1, "score": 0.5}]


def test_a_date_with_no_variance_in_the_score_has_no_daily_ic():
    frame = pd.DataFrame({"date": ["d"] * 12, "score": [1.0] * 12, "target": list(range(12))})
    assert gate_audit.daily_rank_ic(frame, score_column="score", target_column="target", min_names_per_date=5) == {}


def test_a_factor_with_too_few_names_a_day_has_no_return_that_day():
    frame = pd.DataFrame({"date": ["d1"] * 5, "factor": range(5), "target_return_1d": [0.01] * 5})
    assert factor_spanning.build_factor_returns(frame, ["factor"], min_names=20).empty


def test_the_static_baseline_waits_for_a_universe_of_enough_names_and_skips_a_day_none_of_them_trade():
    frame = pd.DataFrame({"date": ["d1"] * 3 + ["d2"] * 25 + ["d3"] * 2, "ticker": ["A", "B", "C"] + [f"T{n}" for n in range(25)] + ["X", "Y"], "target_return_1d": 0.01})
    result = ablation.simulate_static_baseline(frame, min_universe_size=20)
    assert result["num_dates_used"] == 1 and result["mean_names_long"] == 25.0 and result["per_date"] == ["d2"]
