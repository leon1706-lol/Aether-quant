"""Tests for evaluation/ablation.py - V5.1 Phase 5 (item 9)."""

import numpy as np
import pandas as pd
import pytest

from evaluation.ablation import (
    ABLATION_VARIANTS,
    NOT_OFFLINE_MEASURABLE_VARIANTS,
    compare_static_vs_retrained,
    run_ablation,
    simulate_static_baseline,
)
from evaluation.rank_book_simulator import simulate_rank_book


def _synthetic_frame(num_tickers=20, num_days=60, seed=0):
    """Same known-IC fixture convention as tests/test_rank_book_simulator.py -
    a per-ticker fixed "skill" score baked into both prediction and forward
    return, so a well-formed book shows genuine positive gross Sharpe."""
    rng = np.random.default_rng(seed)
    tickers = [f"T{i}" for i in range(num_tickers)]
    dates = pd.bdate_range("2020-01-01", periods=num_days)

    rows = []
    for date in dates:
        for index, ticker in enumerate(tickers):
            skill = (index - num_tickers / 2) / (num_tickers / 2)
            prediction = skill + rng.normal(0, 0.4)
            forward_return = skill * 0.003 + rng.normal(0, 0.01)
            rows.append(
                {
                    "date": date,
                    "ticker": ticker,
                    "pred": prediction,
                    "target_return_1d": forward_return,
                    "liquidity_log_dollar_volume": np.log(1e7 + index * 1e6),
                }
            )
    return pd.DataFrame(rows)


def _base_kwargs(**overrides):
    kwargs = dict(
        prediction_column="pred",
        forward_return_column="target_return_1d",
        ticker_column="ticker",
        date_column="date",
        top_n=4,
        bottom_n=4,
        rebalance_every_bars=5,
        cost_bps_per_side=5.0,
        commission_bps=1.0,
        gross_exposure=1.0,
        dollar_neutral=True,
        sector_neutral=False,
        hysteresis_rank_margin=0.05,
        max_weight_per_name=0.5,
        min_universe_size=10,
    )
    kwargs.update(overrides)
    return kwargs


# ---------------------------------------------------------------------------
# simulate_static_baseline
# ---------------------------------------------------------------------------


def test_simulate_static_baseline_zero_turnover_and_zero_cost():
    frame = _synthetic_frame()
    result = simulate_static_baseline(frame, min_universe_size=10)

    assert result["annualized_turnover"] == 0.0
    assert result["cost_drag_annual_bps"] == 0.0
    assert result["num_rebalances"] == 1


def test_simulate_static_baseline_gross_equals_net():
    # No cost ever charged (buy-and-hold, single entry) - gross and net must
    # be identical, unlike simulate_rank_book() where cost_bps=0 is required
    # to get the same property.
    frame = _synthetic_frame()
    result = simulate_static_baseline(frame, min_universe_size=10)

    assert result["gross_sharpe"] == result["net_sharpe"]
    assert result["gross_total_return"] == result["net_total_return"]


def test_simulate_static_baseline_random_predictions_produces_finite_sane_result():
    # Predictions are irrelevant to the static baseline (it never ranks
    # anything) - confirmed here by using pure noise and checking the
    # result is still well-formed (finite, not NaN/inf - a short random
    # sample's annualized Sharpe estimate is naturally high-variance, so
    # this deliberately does not assert a tight bound on the value itself).
    rng = np.random.default_rng(7)
    tickers = [f"T{i}" for i in range(15)]
    dates = pd.bdate_range("2020-01-01", periods=80)
    rows = []
    for date in dates:
        for ticker in tickers:
            rows.append(
                {
                    "date": date,
                    "ticker": ticker,
                    "pred": rng.normal(),
                    "target_return_1d": rng.normal(0, 0.01),
                }
            )
    frame = pd.DataFrame(rows)

    result = simulate_static_baseline(frame, min_universe_size=10)

    assert np.isfinite(result["net_sharpe"])
    assert result["num_dates_used"] > 0


def test_simulate_static_baseline_empty_frame_is_degenerate_not_raise():
    frame = pd.DataFrame(columns=["date", "ticker", "target_return_1d"])
    result = simulate_static_baseline(frame, min_universe_size=10)

    assert result["net_sharpe"] == 0.0
    assert result["num_dates_used"] == 0


def test_simulate_static_baseline_skips_thin_dates_before_first_valid_universe():
    frame = _synthetic_frame(num_tickers=20, num_days=60)
    # Corrupt the first 3 dates to be too thin to seed the universe.
    thin_dates = sorted(frame["date"].unique())[:3]
    frame = frame[~((frame["date"].isin(thin_dates)) & (frame["ticker"] != "T0"))]

    result = simulate_static_baseline(frame, min_universe_size=10)

    assert result["num_dates_used"] > 0
    assert result["per_date"][0] not in [str(d) for d in thin_dates]


# ---------------------------------------------------------------------------
# run_ablation - measurable variants
# ---------------------------------------------------------------------------


def test_run_ablation_no_op_variant_reproduces_base_result_exactly():
    # A variant whose override dict is empty must reproduce simulate_rank_book()'s
    # own base result exactly.
    frame = _synthetic_frame()
    base_kwargs = _base_kwargs()
    ABLATION_VARIANTS["_test_noop"] = {}
    try:
        results = run_ablation(frame, base_kwargs, ["_test_noop"])
        direct = simulate_rank_book(frame, **base_kwargs)
        assert results["_test_noop"]["net_sharpe"] == pytest.approx(direct.net_sharpe)
        assert results["_test_noop"]["gross_sharpe"] == pytest.approx(direct.gross_sharpe)
    finally:
        del ABLATION_VARIANTS["_test_noop"]


def test_run_ablation_no_cost_model_zeroes_cost_drag():
    frame = _synthetic_frame()
    results = run_ablation(frame, _base_kwargs(), ["no_cost_model"])

    assert results["no_cost_model"]["cost_drag_annual_bps"] == 0.0


def test_run_ablation_no_hysteresis_matches_zero_margin_kwarg():
    frame = _synthetic_frame()
    results = run_ablation(frame, _base_kwargs(), ["no_hysteresis"])
    direct = simulate_rank_book(frame, **{**_base_kwargs(), "hysteresis_rank_margin": 0.0})

    assert results["no_hysteresis"]["net_sharpe"] == pytest.approx(direct.net_sharpe)


def test_run_ablation_no_neutrality_matches_flags_disabled():
    frame = _synthetic_frame()
    results = run_ablation(frame, _base_kwargs(), ["no_neutrality"])
    direct = simulate_rank_book(frame, **{**_base_kwargs(), "dollar_neutral": False, "sector_neutral": False})

    assert results["no_neutrality"]["net_sharpe"] == pytest.approx(direct.net_sharpe)


def test_run_ablation_includes_delta_vs_static_baseline():
    frame = _synthetic_frame()
    results = run_ablation(frame, _base_kwargs(), ["static_baseline", "no_cost_model"])

    assert results["static_baseline"]["delta_vs_static_baseline"] == 0.0
    expected_delta = results["no_cost_model"]["net_sharpe"] - results["static_baseline"]["net_sharpe"]
    assert results["no_cost_model"]["delta_vs_static_baseline"] == pytest.approx(expected_delta)


# ---------------------------------------------------------------------------
# run_ablation - honesty-contract sentinel (V5.1 Phase 5's core guardrail)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("variant_name", sorted(NOT_OFFLINE_MEASURABLE_VARIANTS))
def test_run_ablation_unmeasurable_variants_return_sentinel_never_a_number(variant_name):
    frame = _synthetic_frame()
    results = run_ablation(frame, _base_kwargs(), [variant_name])

    assert results[variant_name]["status"] == "not_offline_measurable"
    assert results[variant_name]["reason"]
    assert "net_sharpe" not in results[variant_name]


def test_run_ablation_no_retraining_returns_sentinel_not_a_fabricated_number():
    # no_retraining is genuinely measurable, but only via
    # compare_static_vs_retrained() with Phase 4 walk-forward artifacts -
    # run_ablation() alone (single frame/base_kwargs) must never fabricate
    # a number for it.
    frame = _synthetic_frame()
    results = run_ablation(frame, _base_kwargs(), ["no_retraining"])

    assert results["no_retraining"]["status"] == "not_offline_measurable"
    assert "net_sharpe" not in results["no_retraining"]


def test_run_ablation_unknown_variant_name_returns_sentinel():
    frame = _synthetic_frame()
    results = run_ablation(frame, _base_kwargs(), ["totally_made_up_variant"])

    assert results["totally_made_up_variant"]["status"] == "unknown_variant"


def test_run_ablation_every_named_variant_is_either_measurable_or_documented_unmeasurable():
    # Regression guard: every variant name this module claims to support
    # (ABLATION_VARIANTS keys + NOT_OFFLINE_MEASURABLE_VARIANTS keys +
    # "no_retraining" + "static_baseline") must not silently fall through
    # to "unknown_variant" - catches a future variant name typo/drift.
    frame = _synthetic_frame()
    all_names = sorted(set(ABLATION_VARIANTS) | set(NOT_OFFLINE_MEASURABLE_VARIANTS) | {"no_retraining", "static_baseline"})
    results = run_ablation(frame, _base_kwargs(), all_names)

    for name in all_names:
        assert results[name].get("status") != "unknown_variant", f"{name} unexpectedly unrecognized"


# ---------------------------------------------------------------------------
# compare_static_vs_retrained (the "no_retraining" ablation)
# ---------------------------------------------------------------------------


def _net_perf_entry(net_sharpe: float) -> dict:
    return {"simulation": {"net_sharpe": net_sharpe}}


def test_compare_static_vs_retrained_insufficient_windows_returns_sentinel():
    # Only window 0 (excluded by construction) plus one other window is not
    # enough to satisfy the default min_windows=2 (window 0 doesn't count).
    frozen = {0: _net_perf_entry(1.0), 1: _net_perf_entry(0.5)}
    retrained = {0: _net_perf_entry(1.0), 1: _net_perf_entry(0.6)}

    result = compare_static_vs_retrained(frozen, retrained)

    assert result["status"] == "insufficient_windows"
    assert "net_sharpe" not in result


def test_compare_static_vs_retrained_computes_delta_across_windows():
    frozen = {0: _net_perf_entry(1.0), 1: _net_perf_entry(0.2), 2: _net_perf_entry(0.1)}
    retrained = {0: _net_perf_entry(1.0), 1: _net_perf_entry(0.5), 2: _net_perf_entry(0.4)}

    result = compare_static_vs_retrained(frozen, retrained)

    assert result["status"] == "walk_forward_derived"
    assert result["num_windows"] == 2
    assert result["mean_delta_retrained_minus_frozen"] == pytest.approx(0.3)


def test_compare_static_vs_retrained_excludes_window_0_from_comparison():
    frozen = {0: _net_perf_entry(1.0), 1: _net_perf_entry(0.5), 2: _net_perf_entry(0.4)}
    retrained = {0: _net_perf_entry(999.0), 1: _net_perf_entry(0.5), 2: _net_perf_entry(0.4)}

    result = compare_static_vs_retrained(frozen, retrained)

    # Window 0's absurd retrained value (999.0) must never leak into the
    # comparison - it is the frozen model itself, not a retraining target.
    assert result["mean_delta_retrained_minus_frozen"] == pytest.approx(0.0)
    assert all(row["window_index"] != 0 for row in result["per_window"])


def test_compare_static_vs_retrained_only_compares_windows_present_in_both():
    frozen = {0: _net_perf_entry(1.0), 1: _net_perf_entry(0.5), 3: _net_perf_entry(0.3)}
    retrained = {0: _net_perf_entry(1.0), 1: _net_perf_entry(0.6), 2: _net_perf_entry(0.9)}

    result = compare_static_vs_retrained(frozen, retrained)

    assert result["status"] == "insufficient_windows"  # only window 1 overlaps (excl. window 0)
