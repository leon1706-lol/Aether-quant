from portfolio.rank_signal import (
    cross_sectional_rank_scores,
    resolve_rank_signal_policy,
    select_raw_rank_score,
)


def _config(**overrides):
    rank_signal = {
        "heads": {"rank_20d": 1.0, "rank_5d": 0.0},
        "model_priority": ["sequence", "multitask"],
        "demote_not_promotable_heads": True,
        "min_promotion_status": ["promotable", "watchlist"],
        "normalization": "cross_sectional",
    }
    rank_signal.update(overrides)
    return {"phase_v2": {"rank_signal": rank_signal}}


def _metrics(status_by_head, model="sequence"):
    return {model: {"backtest": {f"{head}_ranking_quality": {"quality_status": status} for head, status in status_by_head.items()}}}


# ---------------------------------------------------------------------------
# resolve_rank_signal_policy
# ---------------------------------------------------------------------------


def test_resolve_rank_signal_policy_demotes_not_promotable_head_and_redistributes_weight():
    config = _config(heads={"rank_20d": 0.5, "rank_5d": 0.5})
    metrics = _metrics({"rank_20d": "not_promotable", "rank_5d": "promotable"})

    policy = resolve_rank_signal_policy(metrics, config)

    assert policy["demoted"] == ["rank_20d"]
    assert policy["heads"]["rank_20d"] == 0.0
    assert policy["heads"]["rank_5d"] == 1.0
    assert policy["reason"] == "demoted:rank_20d"


def test_resolve_rank_signal_policy_watchlist_head_survives():
    config = _config(heads={"rank_20d": 1.0})
    metrics = _metrics({"rank_20d": "watchlist"})

    policy = resolve_rank_signal_policy(metrics, config)

    assert policy["demoted"] == []
    assert policy["heads"]["rank_20d"] == 1.0


def test_resolve_rank_signal_policy_all_heads_demoted_leaves_policy_unchanged():
    config = _config(heads={"rank_20d": 1.0})
    metrics = _metrics({"rank_20d": "not_promotable"})

    policy = resolve_rank_signal_policy(metrics, config)

    assert policy["heads"] == {"rank_20d": 1.0}
    assert policy["demoted"] == []
    assert policy["reason"] == "all_heads_would_be_demoted_policy_unchanged"


def test_resolve_rank_signal_policy_missing_metrics_leaves_heads_unchanged():
    config = _config(heads={"rank_20d": 1.0})

    policy = resolve_rank_signal_policy({"sequence": None, "multitask": None}, config)

    assert policy["heads"] == {"rank_20d": 1.0}
    assert policy["demoted"] == []
    assert policy["reason"] == "no_demotion_needed"


def test_resolve_rank_signal_policy_demotion_disabled_is_a_no_op():
    config = _config(heads={"rank_20d": 1.0}, demote_not_promotable_heads=False)
    metrics = _metrics({"rank_20d": "not_promotable"})

    policy = resolve_rank_signal_policy(metrics, config)

    assert policy["heads"] == {"rank_20d": 1.0}
    assert policy["reason"] == "demotion_disabled_or_no_heads_configured"


def test_resolve_rank_signal_policy_model_priority_order_wins_for_status_lookup():
    # sequence (first in model_priority) says not_promotable, multitask says
    # promotable - sequence's verdict must win, matching select_raw_rank_score()'s
    # own precedence for the VALUE.
    config = _config(heads={"rank_20d": 0.5, "rank_5d": 0.5})
    metrics = {
        "sequence": {"backtest": {"rank_20d_ranking_quality": {"quality_status": "not_promotable"}}},
        "multitask": {"backtest": {"rank_20d_ranking_quality": {"quality_status": "promotable"}}},
    }

    policy = resolve_rank_signal_policy(metrics, config)

    assert policy["demoted"] == ["rank_20d"]


def test_resolve_rank_signal_policy_never_raises_on_malformed_metrics():
    config = _config(heads={"rank_20d": 1.0})
    policy = resolve_rank_signal_policy({"sequence": {}, "multitask": {"backtest": None}}, config)
    assert policy["heads"]["rank_20d"] == 1.0


# ---------------------------------------------------------------------------
# select_raw_rank_score
# ---------------------------------------------------------------------------


def test_select_raw_rank_score_blends_across_heads_with_model_priority():
    policy = {"heads": {"rank_5d": 0.6, "rank_20d": 0.4}, "model_priority": ["sequence", "multitask"]}
    score, source = select_raw_rank_score({"rank_5d": 0.8, "rank_20d": 0.6}, {"rank_20d": 0.5}, policy)

    assert score == 0.6 * 0.8 + 0.4 * 0.6
    assert "sequence:0.6*rank_5d" in source
    assert "sequence:0.4*rank_20d" in source


def test_select_raw_rank_score_falls_back_to_multitask_when_sequence_missing():
    policy = {"heads": {"rank_20d": 1.0}, "model_priority": ["sequence", "multitask"]}
    score, source = select_raw_rank_score(None, {"rank_20d": 0.7}, policy)

    assert score == 0.7
    assert source == "multitask:1*rank_20d"


def test_select_raw_rank_score_returns_none_when_no_head_available():
    policy = {"heads": {"rank_20d": 1.0}, "model_priority": ["sequence", "multitask"]}
    score, source = select_raw_rank_score(None, None, policy)

    assert score is None
    assert source == "no_rank_available"


def test_select_raw_rank_score_skips_zero_weight_heads():
    policy = {"heads": {"rank_5d": 0.0, "rank_20d": 1.0}, "model_priority": ["sequence", "multitask"]}
    score, source = select_raw_rank_score({"rank_5d": 0.99, "rank_20d": 0.4}, None, policy)

    assert score == 0.4
    assert "rank_5d" not in source


# ---------------------------------------------------------------------------
# cross_sectional_rank_scores
# ---------------------------------------------------------------------------


def test_cross_sectional_rank_scores_orders_correctly():
    ranks = cross_sectional_rank_scores({"A": 0.9, "B": 0.5, "C": 0.1})

    assert ranks["A"] == 1.0
    assert ranks["C"] == 1 / 3
    assert ranks["B"] == 2 / 3


def test_cross_sectional_rank_scores_ties_get_the_average_rank():
    ranks = cross_sectional_rank_scores({"A": 0.5, "B": 0.5, "C": 0.9})

    assert ranks["A"] == ranks["B"]
    assert ranks["C"] == 1.0
    # Two symbols tied for positions 1-2 (of 3) average to (1+2)/2/3.
    assert abs(ranks["A"] - 0.5) < 1e-9


def test_cross_sectional_rank_scores_single_symbol_returns_empty():
    assert cross_sectional_rank_scores({"A": 0.5}) == {}


def test_cross_sectional_rank_scores_empty_input_returns_empty():
    assert cross_sectional_rank_scores({}) == {}


def test_cross_sectional_rank_scores_all_tied_matches_pandas_rank_pct_true():
    # pandas.Series([0.5]*4).rank(pct=True) == [0.625]*4 (average rank
    # (1+2+3+4)/4 = 2.5, percentile 2.5/4 = 0.625) - cross_sectional_rank_scores()
    # is a from-scratch reimplementation of that exact semantics (no pandas
    # import on the runtime hot path), so it must match pandas bit for bit.
    ranks = cross_sectional_rank_scores({"A": 0.5, "B": 0.5, "C": 0.5, "D": 0.5})
    assert all(abs(value - 0.625) < 1e-9 for value in ranks.values())
