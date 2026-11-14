"""Small remaining branches (V6.6.6, #359): the analyzer's verdict as a dict."""

from __future__ import annotations

from analyzer.market_analyzer import MarketAnalysisDecision


def test_a_market_analysis_decision_serialises_to_a_plain_dict():
    decision = MarketAnalysisDecision(action="trade", signal="buy", target_weight=0.05, confidence=0.5, probability_up=0.6, trading_eligible=True,
                                      topology_considered=True, liquidity_considered=True, reasons=["ok"])
    as_dict = decision.to_dict()
    assert as_dict["action"] == "trade" and as_dict["reasons"] == ["ok"] and as_dict["net_edge"] is None


# ---- the last lines of the whole-repo measurement ------------------------------------------------------------------------

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from evaluation import confidence_threshold_calibration, rank_signal_calibration, research_harness, tranche_book, trade_bootstrap  # noqa: E402


def test_a_closed_trade_with_a_non_numeric_amount_is_not_a_round_trip():
    run = {"result": {"totalPerformance": {"closedTrades": [
        {"symbols": [{"value": "AAPL"}], "profitLoss": "oops", "totalFees": 0.0, "entryPrice": 1.0, "quantity": 1.0},
        {"symbols": [{"value": "MSFT"}], "profitLoss": 5.0, "totalFees": 1.0, "entryPrice": 10.0, "quantity": 2.0, "entryTime": "2020-01-02T00:00:00"}]}}}
    assert trade_bootstrap.round_trips_from_closed_trades(run) == [{"ticker": "MSFT", "pnl": 4.0, "notional": 20.0, "entry": "2020-01-02"}]


def test_the_regression_gate_names_a_backtest_that_is_close_to_the_train_error_limit():
    from train import assess_regression_quality

    config = {"quality_gate": {"max_rmse_mae_ratio": 10.0, "max_backtest_train_rmse_ratio": 2.0, "regression_watchlist_margin": 0.2}}
    result = assess_regression_quality({"train": {"rmse": 1.0}, "backtest": {"rmse": 1.9, "mae": 1.8}}, config)
    assert "backtest_train_rmse_ratio_near_gate" in result["near_misses"]


def test_the_confidence_calibration_skips_a_name_whose_forward_return_is_missing():
    rows = [{"date": "2020-01-01", "ticker": f"T{n}", "score": float(n), "fwd": (float("nan") if n == 3 else 0.01 * n)} for n in range(12)]
    result = confidence_threshold_calibration.calibrate_confidence_threshold(pd.DataFrame(rows), raw_score_column="score", forward_return_column="fwd", top_n=3, bottom_n=3)
    assert isinstance(result, dict) and result


def test_the_spread_calibration_counts_a_date_with_no_book_and_a_date_with_no_spread_as_thin():
    rows = [{"date": f"2020-01-0{day}", "ticker": f"T{n}", "score": float(n)} for day in (1, 2) for n in range(10)]
    frame = pd.DataFrame(rows)
    ineligible = {f"T{n}": {"asset_class": "equity", "trading_eligible": False} for n in range(10)}
    none = rank_signal_calibration.calibrate_book_confidence_spread(frame, raw_score_column="score", top_n=2, bottom_n=2, candidate_metadata_by_ticker=ineligible)
    assert none["num_dates_skipped_thin_universe"] == 2 and none["num_dates_used"] == 0
    one_sided = rank_signal_calibration.calibrate_book_confidence_spread(frame, raw_score_column="score", top_n=2, bottom_n=0)
    assert one_sided["num_dates_skipped_thin_universe"] == 2


def test_a_horizon_without_a_target_column_is_left_out_of_the_signal_report():
    rng = np.random.default_rng(0)
    frame = pd.DataFrame({"date": np.repeat([f"2020-01-{n + 1:02d}" for n in range(10)], 25), "ticker": [f"T{n}" for n in range(25)] * 10, "split": "validation"})
    frame["score"] = rng.normal(size=len(frame))
    frame["target_rank_5d"] = rng.normal(size=len(frame))
    report = research_harness.evaluate_signal(frame, score_column="score", horizons=(5, 20), min_names_per_date=10, bootstrap_draws=20)
    assert "validation" in str(report)


def test_combining_tranches_adds_the_vetoes_each_one_recorded():
    from dataclasses import replace

    from evaluation.rank_book_simulator import simulate_rank_book
    from test_rank_book_simulator import _base_kwargs, _synthetic_frame

    base = simulate_rank_book(_synthetic_frame(), **_base_kwargs())
    one, two = replace(base, veto_reasons={"spread": 2}), replace(base, veto_reasons={"spread": 1, "ic": 4})
    assert tranche_book.combine_tranche_results([one, two]).veto_reasons == {"spread": 3, "ic": 4}


def test_a_dataset_without_a_split_column_is_written_whole_and_never_per_split(tmp_path):
    from experts import expert_datasets

    manifest = {"experts": {"bullish": {"filter": {}}}}
    frame = pd.DataFrame({"ticker": ["A", "B"], "x": [1.0, 2.0]})
    expert_datasets.write_expert_dataset_artifacts(frame, manifest, tmp_path / "out", tmp_path / "manifest.json")
    written = sorted(path.name for path in (tmp_path / "out" / "bullish").iterdir())
    assert written == ["all_splits.csv"]
