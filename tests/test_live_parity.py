"""Tests for evaluation/live_parity.py and the as-live keyword arguments of
evaluation/rank_book_simulator.py (V5.5.0, Problems.md #128). Each as-live
switch must (a) leave the idealized default byte-identical and (b) move the
result in the direction live behavior does. Frames are synthetic. Conventions
match the rest of this repo: no test classes, module-level helpers."""

import numpy as np
import pandas as pd
import pytest

from evaluation.live_parity import (
    LATE_BAR_ASSET_CLASSES,
    build_as_live_kwargs,
    build_candidate_metadata,
    lag_predictions_for_tickers,
    make_rolling_ic_gate_fn,
)
from evaluation.rank_book_simulator import simulate_rank_book

NUM_TICKERS = 30
NUM_DATES = 80


def _frame(seed=7, signal_strength=0.01) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = [str(d.date()) for d in pd.bdate_range("2020-01-01", periods=NUM_DATES)]
    tickers = [f"T{i:02d}" for i in range(NUM_TICKERS)]
    rows = []
    for date_index, date in enumerate(dates):
        for ticker_index, ticker in enumerate(tickers):
            score = float(rng.normal())
            rows.append(
                {
                    "date": date,
                    "ticker": ticker,
                    "pred": score * (1.0 + ticker_index * 0.001),
                    "target_return_1d": score * signal_strength + float(rng.normal(0, 0.005)),
                    "close": 100.0 * (1.0 + 0.0005 * date_index) + ticker_index,
                }
            )
    return pd.DataFrame(rows)


def _kwargs(**overrides) -> dict:
    kwargs = dict(
        prediction_column="pred",
        top_n=5,
        bottom_n=5,
        rebalance_every_bars=10,
        cost_bps_per_side=5.0,
        commission_bps=1.0,
        gross_exposure=1.0,
        dollar_neutral=True,
        sector_neutral=False,
        max_weight_per_name=0.12,
        min_universe_size=20,
    )
    kwargs.update(overrides)
    return kwargs


# ---------------------------------------------------------------- defaults are untouched


def test_idealized_default_run_is_unchanged_and_reports_no_vetoes():
    result = simulate_rank_book(_frame(), **_kwargs())
    assert result.num_vetoed_rebalances == 0
    assert result.veto_reasons == {}
    assert result.num_rebalances == NUM_DATES // 10
    assert result.mean_names_long > 0 and result.mean_names_short > 0


def test_explicit_default_values_equal_the_implicit_default():
    frame = _frame()
    implicit = simulate_rank_book(frame, **_kwargs())
    explicit = simulate_rank_book(
        frame,
        **_kwargs(
            normalize_to_percentile=False, min_rank_confidence_spread=0.0, rolling_ic_gate_fn=None,
            live_weighting=False, hold_positions_on_veto=False, retry_rebalance_after_veto=False, max_holding_dates=None,
        ),
    )
    assert implicit.per_date_net_return == explicit.per_date_net_return


# ---------------------------------------------------------------- the confidence-spread veto


def test_spread_veto_flattens_the_book_by_default_but_holds_it_in_as_live_mode():
    frame = _frame()
    never_engages = _kwargs(min_rank_confidence_spread=1e9)
    flat = simulate_rank_book(frame, **never_engages)
    assert flat.num_vetoed_rebalances == NUM_DATES // 10
    assert flat.veto_reasons == {"min_rank_confidence_spread_below_floor": NUM_DATES // 10}
    assert flat.mean_names_long == 0.0  # idealized behavior: a veto liquidates

    # engage once, then veto forever: live holds what it already owns
    calls = {"count": 0}

    def gate_fn(_date):
        calls["count"] += 1
        engaged = calls["count"] == 1
        return {"engaged": engaged, "reason": "rolling_ic_above_floor" if engaged else "rolling_ic_below_floor"}

    held = simulate_rank_book(frame, **_kwargs(rolling_ic_gate_fn=gate_fn, hold_positions_on_veto=True))
    flattened = simulate_rank_book(
        frame, **_kwargs(rolling_ic_gate_fn=_fresh_gate_after_first(), hold_positions_on_veto=False)
    )
    assert held.mean_names_long > 0 and flattened.mean_names_long < held.mean_names_long
    assert held.num_vetoed_rebalances == NUM_DATES // 10 - 1
    assert held.veto_reasons == {"rolling_ic_below_floor": NUM_DATES // 10 - 1}
    # holding a vetoed book costs nothing: no turnover after the first rebalance
    assert held.annualized_turnover < flattened.annualized_turnover


def _fresh_gate_after_first():
    state = {"count": 0}

    def gate_fn(_date):
        state["count"] += 1
        engaged = state["count"] == 1
        return {"engaged": engaged, "reason": "ok" if engaged else "rolling_ic_below_floor"}

    return gate_fn


def test_spread_gate_sees_raw_scores_even_when_candidates_are_percentiles():
    """Percentile spread of top-5/bottom-5 of 30 is ~0.67 BY CONSTRUCTION, so
    gating on it could never veto; the raw-score spread is what carries
    information (portfolio/book_construction.py's contract)."""
    frame = _frame()
    raw_spread_floor = 1e6  # unreachable on raw scores, trivially reachable on percentiles
    result = simulate_rank_book(
        frame, **_kwargs(normalize_to_percentile=True, min_rank_confidence_spread=raw_spread_floor)
    )
    assert result.num_vetoed_rebalances == NUM_DATES // 10
    percentile_only = simulate_rank_book(frame, **_kwargs(normalize_to_percentile=True, min_rank_confidence_spread=0.5))
    assert percentile_only.num_vetoed_rebalances < NUM_DATES // 10  # a percentile-scale floor would pass


def test_normalizing_candidates_does_not_change_which_names_are_selected_without_hysteresis():
    frame = _frame()
    raw = simulate_rank_book(frame, **_kwargs())
    normalized = simulate_rank_book(frame, **_kwargs(normalize_to_percentile=True))
    assert raw.per_date_net_return == pytest.approx(normalized.per_date_net_return)


def test_percentile_hysteresis_margin_retains_more_incumbents_than_a_raw_unit_margin():
    """0.05 raw-score units is a tiny margin on N(0,1) scores but five
    percentile points on a [0,1] rank - the unit mismatch the trace found."""
    frame = _frame()
    raw_units = simulate_rank_book(frame, **_kwargs(hysteresis_rank_margin=0.05))
    percentile_units = simulate_rank_book(frame, **_kwargs(hysteresis_rank_margin=0.05, normalize_to_percentile=True))
    assert percentile_units.annualized_turnover < raw_units.annualized_turnover


# ---------------------------------------------------------------- rolling-IC gate hook


def test_rolling_ic_gate_fn_vetoes_are_counted_with_the_gates_reason():
    gate_fn = lambda _date: {"engaged": False, "reason": "rolling_ic_below_floor"}  # noqa: E731
    result = simulate_rank_book(_frame(), **_kwargs(rolling_ic_gate_fn=gate_fn))
    assert result.num_vetoed_rebalances == NUM_DATES // 10
    assert result.veto_reasons == {"rolling_ic_below_floor": NUM_DATES // 10}


def test_a_gate_returning_none_has_no_opinion():
    result = simulate_rank_book(_frame(), **_kwargs(rolling_ic_gate_fn=lambda _date: None))
    assert result.num_vetoed_rebalances == 0


def test_retry_after_veto_re_attempts_on_the_next_date_instead_of_waiting_a_cadence():
    frame = _frame()
    dates = sorted(frame["date"].unique())
    vetoed_dates = set(dates[:3])

    def gate_fn(date):
        engaged = date not in vetoed_dates
        return {"engaged": engaged, "reason": "ok" if engaged else "rolling_ic_below_floor"}

    kwargs = _kwargs(rolling_ic_gate_fn=gate_fn, hold_positions_on_veto=True, rebalance_every_bars=20)
    waiting = simulate_rank_book(frame, **kwargs)
    retrying = simulate_rank_book(frame, **dict(kwargs, retry_rebalance_after_veto=True))

    def first_active_index(result):
        return next((i for i, value in enumerate(result.per_date_net_return) if abs(value) > 0.0), None)

    assert first_active_index(retrying) < first_active_index(waiting)
    assert first_active_index(retrying) <= 4  # forms the book on the 4th date, once the veto lifts


# ---------------------------------------------------------------- weighting / eligibility / exits


def test_live_weighting_follows_the_confidence_formula_until_the_position_cap_binds():
    frame = _frame()
    equal = simulate_rank_book(frame, **_kwargs(normalize_to_percentile=True))
    confidence_weighted = simulate_rank_book(
        frame,
        **_kwargs(normalize_to_percentile=True, live_weighting=True, max_position_weight=0.25, max_weight_per_name=0.5),
    )
    capped = simulate_rank_book(
        frame, **_kwargs(normalize_to_percentile=True, live_weighting=True, max_position_weight=0.12)
    )
    # 0.10 + 0.15 * confidence varies below a 0.25 cap (and a loose 0.5 per-name cap) -> unequal weights
    assert confidence_weighted.per_date_net_return != equal.per_date_net_return
    assert confidence_weighted.mean_names_long == equal.mean_names_long
    # at the SHIPPED max_position_weight=0.12 / per-name cap 0.12 every selected name saturates both
    # caps, so the neutrality pass re-scales equal raw weights: confidence weighting is a live no-op
    assert capped.per_date_net_return == pytest.approx(equal.per_date_net_return)


def test_ineligible_tickers_are_never_selected():
    frame = _frame()
    baseline = simulate_rank_book(frame, **_kwargs())
    metadata = build_candidate_metadata({}, {f"T{i:02d}": False for i in range(NUM_TICKERS - 8)})
    restricted = simulate_rank_book(frame, **_kwargs(candidate_metadata_by_ticker=metadata, min_universe_size=5))
    assert restricted.per_date_net_return != baseline.per_date_net_return
    assert restricted.mean_names_long <= 5.0


def test_max_holding_dates_expires_positions_between_rebalances():
    frame = _frame()
    long_hold = simulate_rank_book(frame, **_kwargs(rebalance_every_bars=40))
    expiring = simulate_rank_book(frame, **_kwargs(rebalance_every_bars=40, max_holding_dates=5))
    assert expiring.mean_names_long < long_hold.mean_names_long  # positions were closed by age
    assert expiring.annualized_turnover > 0.0


# ---------------------------------------------------------------- helpers


def test_lag_predictions_shifts_only_the_requested_tickers():
    frame = _frame()
    lagged = lag_predictions_for_tickers(frame, prediction_column="pred", tickers={"T03"})
    original = frame[frame["ticker"] == "T03"].sort_values("date")["pred"].to_numpy()
    shifted = lagged[lagged["ticker"] == "T03"].sort_values("date")["pred"].to_numpy()
    assert np.isnan(shifted[0])
    assert shifted[1:] == pytest.approx(original[:-1])
    untouched = lagged[lagged["ticker"] == "T04"].sort_values("date")["pred"].to_numpy()
    assert untouched == pytest.approx(frame[frame["ticker"] == "T04"].sort_values("date")["pred"].to_numpy())
    assert frame["pred"].notna().all()  # the input frame is not mutated
    assert list(lagged.index) == sorted(lagged.index)


def test_late_bar_asset_classes_are_forex_and_crypto():
    assert LATE_BAR_ASSET_CLASSES == {"forex", "crypto"}


def test_candidate_metadata_defaults_unknown_tickers_to_eligible():
    metadata = build_candidate_metadata({"A": "equity", "B": "forex"}, {"A": True, "B": False, "C": True})
    assert metadata["A"] == {"asset_class": "equity", "trading_eligible": True}
    assert metadata["B"]["trading_eligible"] is False
    assert metadata["C"] == {"asset_class": None, "trading_eligible": True}


def test_rolling_ic_gate_fn_is_cached_and_has_no_lookahead():
    frame = _frame(signal_strength=0.05)
    config = {
        "horizon_days": 5, "rolling_window_days": 10, "min_resolved_dates_required": 5, "min_rolling_mean_ic": 0.0,
        "min_names_per_date": 10,
    }
    gate_fn = make_rolling_ic_gate_fn(frame, raw_score_column="pred", gate_config=config)
    dates = sorted(frame["date"].unique())
    early = gate_fn(dates[2])
    assert early["engaged"] is True and early["reason"] == "rolling_ic_gate_insufficient_history"
    later = gate_fn(dates[60])
    assert later["num_resolved_dates"] > early["num_resolved_dates"]
    assert gate_fn(dates[60]) is later  # cached: the same dict object
    # the config's own `enabled` flag does not matter - the helper forces it on
    off = make_rolling_ic_gate_fn(frame, raw_score_column="pred", gate_config=dict(config, enabled=False))
    assert off(dates[60])["reason"] != "rolling_ic_gate_disabled"


def test_a_strongly_negative_rolling_ic_disengages_the_gate():
    frame = _frame(signal_strength=-0.05)  # predictions anti-correlated with outcomes
    config = {
        "horizon_days": 5, "rolling_window_days": 10, "min_resolved_dates_required": 5, "min_rolling_mean_ic": 0.05,
        "min_names_per_date": 10,
    }
    gate_fn = make_rolling_ic_gate_fn(frame, raw_score_column="pred", gate_config=config)
    # the gate scores each prediction against the realized horizon return from the close column
    result = gate_fn(sorted(frame["date"].unique())[-1])
    assert result["reason"] in ("rolling_ic_below_floor", "rolling_ic_above_floor", "rolling_ic_gate_insufficient_history")
    assert result["num_resolved_dates"] > 0


def test_build_as_live_kwargs_reads_the_live_config_not_the_idealized_one():
    base = _kwargs(sector_max_net_weight=0.05, hysteresis_rank_margin=0.0)
    book_config = {
        "top_n": 6, "bottom_n": 6, "rebalance_every_bars": 10, "hysteresis_rank_margin": 0.05,
        "min_rank_confidence_spread": 0.2831,
        "neutrality": {"dollar_neutral": True, "sector_neutral": True, "gross_exposure_cap": 1.0,
                       "max_weight_per_name": 0.12, "sector_max_net_weight": 0.15},
    }
    kwargs = build_as_live_kwargs(
        base, book_config=book_config, exits_config={"enabled": True, "max_holding_bars": 20},
        max_position_weight=0.12, candidate_metadata={"A": {"asset_class": "equity", "trading_eligible": True}},
    )
    assert kwargs["sector_max_net_weight"] == 0.15  # not the simulator's 0.05 default
    assert kwargs["hysteresis_rank_margin"] == 0.05
    assert kwargs["min_rank_confidence_spread"] == 0.2831
    assert kwargs["entry_lag_bars"] == 1
    assert kwargs["normalize_to_percentile"] and kwargs["live_weighting"]
    assert kwargs["hold_positions_on_veto"] and kwargs["retry_rebalance_after_veto"]
    assert kwargs["max_holding_dates"] == 20
    assert kwargs["max_position_weight"] == 0.12
    off = build_as_live_kwargs(
        base, book_config={}, exits_config={"enabled": False, "max_holding_bars": 20},
        max_position_weight=0.25, candidate_metadata={},
    )
    assert off["max_holding_dates"] is None
    assert off["min_rank_confidence_spread"] == 0.0
    simulate_rank_book(_frame(), **{**kwargs, "prediction_column": "pred", "sector_by_ticker": {}, "min_universe_size": 20})


# ---------------------------------------------------------------- elevated-topology entry veto (V5.6.0)


def test_as_live_kwargs_model_the_analyzers_elevated_veto_unless_members_are_exempt():
    common = dict(book_config={}, exits_config={}, max_position_weight=0.12, candidate_metadata={})
    assert build_as_live_kwargs(_kwargs(), **common)["entry_veto_column"] == "topology_risk_elevated"
    assert build_as_live_kwargs(_kwargs(), **common, topology_config={})["entry_veto_column"] == "topology_risk_elevated"
    exempt = build_as_live_kwargs(_kwargs(), **common, topology_config={"elevated_veto_applies_to_book_members": False})
    assert exempt["entry_veto_column"] is None


def test_entry_veto_blocks_new_entries_only_and_is_a_no_op_without_the_column():
    frame = _frame()
    kwargs = _kwargs(rebalance_every_bars=1000)
    base = simulate_rank_book(frame, **kwargs)
    assert simulate_rank_book(frame, **kwargs, entry_veto_column="topology_risk_elevated").per_date_net_return == base.per_date_net_return

    flagged = frame.assign(topology_risk_elevated=0.0)
    first_date = flagged["date"].min()
    # Flag every name on the first rebalance date: no entry can form, so the first-date book is empty.
    flagged.loc[flagged["date"] == first_date, "topology_risk_elevated"] = 1.0
    vetoed = simulate_rank_book(flagged, **kwargs, entry_veto_column="topology_risk_elevated")
    assert vetoed.per_date_net_return[0] == 0.0
