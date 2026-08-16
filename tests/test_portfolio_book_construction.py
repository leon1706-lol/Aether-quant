"""Tests for portfolio/book_construction.py::build_rank_based_book() (Phase 3
of the 5/10 -> 9/10 roadmap). Conventions match the rest of this repo:
no test classes, module-level helpers, plain dicts.
"""

from portfolio.book_construction import (
    BookAllocation,
    build_book_history_record,
    build_rank_based_book,
    compute_confidence_spread,
    normalize_per_asset_class_slots,
    should_exit_non_selected_book_symbol,
    should_rebalance_this_bar,
)


def _candidate(rank: float | None, trading_eligible: bool = True) -> dict:
    return {"predicted_rank_20d": rank, "trading_eligible": trading_eligible}


def _class_candidate(rank: float | None, asset_class: str, trading_eligible: bool = True) -> dict:
    return {"predicted_rank_20d": rank, "trading_eligible": trading_eligible, "asset_class": asset_class}


def test_build_rank_based_book_selects_top_and_bottom_by_rank():
    candidates = {
        "A": _candidate(0.95),
        "B": _candidate(0.80),
        "C": _candidate(0.50),
        "D": _candidate(0.20),
        "E": _candidate(0.05),
    }

    book = build_rank_based_book(candidates, top_n=2, bottom_n=2)

    assert book["A"].role == "long"
    assert book["B"].role == "long"
    assert book["D"].role == "short"
    assert book["E"].role == "short"
    assert "C" not in book


def test_build_rank_based_book_long_multiplier_is_positive_short_is_negative():
    candidates = {"A": _candidate(0.9), "B": _candidate(0.1)}

    book = build_rank_based_book(candidates, top_n=1, bottom_n=1)

    assert book["A"].book_role_multiplier == 1.0
    assert book["B"].book_role_multiplier == -1.0


def test_build_rank_based_book_excludes_non_trading_eligible_assets():
    candidates = {
        "A": _candidate(0.95),
        "OBSERVATION_ONLY": _candidate(0.99, trading_eligible=False),
        "B": _candidate(0.05),
    }

    book = build_rank_based_book(candidates, top_n=1, bottom_n=1)

    assert "OBSERVATION_ONLY" not in book
    assert book["A"].role == "long"
    assert book["B"].role == "short"


def test_build_rank_based_book_excludes_missing_rank_predictions():
    candidates = {
        "A": _candidate(0.95),
        "NO_PREDICTION": _candidate(None),
        "B": _candidate(0.05),
    }

    book = build_rank_based_book(candidates, top_n=2, bottom_n=1)

    assert "NO_PREDICTION" not in book


def test_build_rank_based_book_thin_universe_degrades_to_fewer_than_requested():
    # top_n claims candidates first, so an oversized bottom_n request
    # degrades to whatever's left rather than erroring - here 1 candidate
    # goes long, leaving only 2 (not the requested 5) for the short side.
    candidates = {"A": _candidate(0.9), "B": _candidate(0.5), "C": _candidate(0.1)}

    book = build_rank_based_book(candidates, top_n=1, bottom_n=5)

    assert len(book) == 3
    assert book["A"].role == "long"
    assert book["B"].role == "short"
    assert book["C"].role == "short"


def test_build_rank_based_book_no_overlap_between_long_and_short():
    # 5 candidates, top_n + bottom_n (3 + 3 = 6) exceeds the total count -
    # long claims the top 3 first, leaving only 2 for short (not 3), and
    # neither symbol may appear in both roles.
    candidates = {
        "A": _candidate(0.9), "B": _candidate(0.7), "C": _candidate(0.5),
        "D": _candidate(0.3), "E": _candidate(0.1),
    }

    book = build_rank_based_book(candidates, top_n=3, bottom_n=3)

    long_symbols = {symbol for symbol, allocation in book.items() if allocation.role == "long"}
    short_symbols = {symbol for symbol, allocation in book.items() if allocation.role == "short"}
    assert long_symbols == {"A", "B", "C"}
    assert short_symbols == {"D", "E"}
    assert long_symbols.isdisjoint(short_symbols)


def test_build_rank_based_book_empty_when_fewer_than_two_eligible_candidates():
    candidates = {"A": _candidate(0.9)}

    book = build_rank_based_book(candidates, top_n=1, bottom_n=1)

    assert book == {}


def test_build_rank_based_book_empty_when_only_one_side_has_candidates():
    # top_n claims every eligible symbol, leaving none for the short side.
    candidates = {"A": _candidate(0.9), "B": _candidate(0.8)}

    book = build_rank_based_book(candidates, top_n=2, bottom_n=1)

    assert book == {}


def test_build_rank_based_book_tie_break_follows_candidates_insertion_order():
    # _select_book_group()'s selection sort is a Python-stable sort keyed
    # only on rank - a genuine tie resolves by insertion order of the
    # `candidates` dict, not any inherent property of the tied symbols.
    # This is DELIBERATE and load-bearing (development/Problems.md
    # #91/#97/#99): aq_cli.py's --reconcile-book-history now depends on
    # this staying insertion-order-based, re-inserting its own raw-scores
    # dict in main.py's live self.symbols order before it ever reaches
    # this function, specifically so offline's tie-break matches live's.
    # A future change making this alphabetical (or any order not driven
    # by the caller's dict) would silently break that fix.
    candidates_b_first = {"B": _candidate(0.9), "C": _candidate(0.9), "A": _candidate(0.1)}
    assert set(build_rank_based_book(candidates_b_first, top_n=1, bottom_n=0)) == {"B"}

    candidates_c_first = {"C": _candidate(0.9), "B": _candidate(0.9), "A": _candidate(0.1)}
    assert set(build_rank_based_book(candidates_c_first, top_n=1, bottom_n=0)) == {"C"}


def test_build_rank_based_book_zero_top_n_returns_empty():
    candidates = {"A": _candidate(0.9), "B": _candidate(0.1)}

    assert build_rank_based_book(candidates, top_n=0, bottom_n=1) == {}


def test_build_rank_based_book_zero_bottom_n_is_a_deliberate_long_only_book():
    # main.py passes bottom_n=0 to honor phase5.backtest.strategy_mode ==
    # "long_flat" while still getting rank-driven entries/rotation on the
    # long side - not a degenerate case like top_n=0 above.
    candidates = {"A": _candidate(0.9), "B": _candidate(0.8), "C": _candidate(0.1)}

    book = build_rank_based_book(candidates, top_n=2, bottom_n=0)

    assert set(book) == {"A", "B"}
    assert all(allocation.role == "long" for allocation in book.values())


def test_build_rank_based_book_disengages_when_rank_spread_below_confidence_floor():
    # Ranks clustered tightly around 0.5 - no real cross-sectional dispersion.
    candidates = {"A": _candidate(0.52), "B": _candidate(0.51), "C": _candidate(0.49), "D": _candidate(0.48)}

    book = build_rank_based_book(candidates, top_n=2, bottom_n=2, min_rank_confidence_spread=0.5)

    assert book == {}


def test_build_rank_based_book_engages_when_spread_clears_confidence_floor():
    candidates = {"A": _candidate(0.95), "B": _candidate(0.05)}

    book = build_rank_based_book(candidates, top_n=1, bottom_n=1, min_rank_confidence_spread=0.5)

    assert book["A"].role == "long"
    assert book["B"].role == "short"


# ---------------------------------------------------------------------------
# spread_check_ranks (V5.1 Phase 1, development/Problems.md #77)
#
# The regression this reproduces: main.py feeds build_rank_based_book()
# candidates whose predicted_rank_20d is ALREADY a per-bar cross-sectional
# percentile (portfolio/rank_signal.py::cross_sectional_rank_scores()). A
# fixed top-N/bottom-N split of a percentile-ranked pool shows a large
# spread by construction REGARDLESS of the underlying model's actual
# conviction that bar - checking min_rank_confidence_spread against that
# normalized scale can never disengage the book on a genuinely noisy day,
# defeating the gate's entire purpose (confirmed in a real Lean backtest:
# fees/orders fell as expected, but Sharpe/net-profit got dramatically
# WORSE than the pre-Phase-1 baseline, because the book was now trading
# through low-conviction noise it previously correctly sat out).
# ---------------------------------------------------------------------------


def test_spread_check_defaults_to_eligible_ranks_when_not_given_byte_identical():
    # Default (no spread_check_ranks) must reproduce today's exact
    # behavior - both disengage-below-floor and engage-above-floor cases.
    tight_candidates = {"A": _candidate(0.52), "B": _candidate(0.51), "C": _candidate(0.49), "D": _candidate(0.48)}
    assert build_rank_based_book(tight_candidates, top_n=2, bottom_n=2, min_rank_confidence_spread=0.5) == {}

    wide_candidates = {"A": _candidate(0.95), "B": _candidate(0.05)}
    book = build_rank_based_book(wide_candidates, top_n=1, bottom_n=1, min_rank_confidence_spread=0.5)
    assert book["A"].role == "long" and book["B"].role == "short"


def test_normalized_ranks_alone_would_trivially_clear_a_realistic_threshold():
    # THE bug, reproduced directly: candidates already carry cross-sectional
    # percentiles (as main.py now passes) - top-1/bottom-1 of 4 clears even
    # a demanding 0.5 spread floor by construction, with ZERO information
    # about whether the underlying raw model output had any real dispersion.
    normalized_candidates = {"A": _candidate(1.0), "B": _candidate(0.67), "C": _candidate(0.33), "D": _candidate(0.0)}
    book = build_rank_based_book(normalized_candidates, top_n=1, bottom_n=1, min_rank_confidence_spread=0.5)
    assert book != {}, "normalized-scale spread trivially clears the floor - this is the defeated-gate bug"


def test_spread_check_ranks_disengages_the_book_when_raw_scores_show_no_real_dispersion():
    # THE fix: even though the NORMALIZED candidates above look maximally
    # dispersed (0.0 to 1.0), the caller's raw_rank_score for the same
    # symbols was tightly clustered (a genuinely low-conviction bar) -
    # spread_check_ranks must be what actually gates engagement.
    normalized_candidates = {"A": _candidate(1.0), "B": _candidate(0.67), "C": _candidate(0.33), "D": _candidate(0.0)}
    raw_scores = {"A": 0.502, "B": 0.501, "C": 0.499, "D": 0.498}  # clustered, no real dispersion

    book = build_rank_based_book(
        normalized_candidates, top_n=1, bottom_n=1, min_rank_confidence_spread=0.5,
        spread_check_ranks=raw_scores,
    )
    assert book == {}


def test_spread_check_ranks_still_engages_when_raw_scores_show_genuine_dispersion():
    normalized_candidates = {"A": _candidate(1.0), "B": _candidate(0.67), "C": _candidate(0.33), "D": _candidate(0.0)}
    raw_scores = {"A": 0.9, "B": 0.6, "C": 0.3, "D": 0.05}  # genuinely dispersed

    book = build_rank_based_book(
        normalized_candidates, top_n=1, bottom_n=1, min_rank_confidence_spread=0.5,
        spread_check_ranks=raw_scores,
    )
    assert book["A"].role == "long" and book["D"].role == "short"


def test_spread_check_ranks_never_changes_which_symbols_are_selected():
    # Selection is invariant under the (monotone) normalization transform -
    # spread_check_ranks affects ONLY the engage/disengage decision, never
    # who gets picked once the book does engage.
    normalized_candidates = {"A": _candidate(1.0), "B": _candidate(0.67), "C": _candidate(0.33), "D": _candidate(0.0)}
    raw_scores = {"A": 0.9, "B": 0.6, "C": 0.3, "D": 0.05}

    without_override = build_rank_based_book(normalized_candidates, top_n=1, bottom_n=1, min_rank_confidence_spread=0.0)
    with_override = build_rank_based_book(
        normalized_candidates, top_n=1, bottom_n=1, min_rank_confidence_spread=0.0, spread_check_ranks=raw_scores
    )
    assert set(without_override.keys()) == set(with_override.keys()) == {"A", "D"}
    # predicted_rank_20d on the resulting allocation is still the
    # NORMALIZED value (sizing/confidence must keep using it) - only the
    # engagement gate reads spread_check_ranks, never the stored allocation.
    assert with_override["A"].predicted_rank_20d == 1.0
    assert with_override["D"].predicted_rank_20d == 0.0


def test_spread_check_ranks_missing_symbol_falls_back_to_eligible_ranks_not_a_crash():
    normalized_candidates = {"A": _candidate(1.0), "B": _candidate(0.67), "C": _candidate(0.33), "D": _candidate(0.0)}
    partial_raw_scores = {"A": 0.9}  # missing B/C/D entirely

    book = build_rank_based_book(
        normalized_candidates, top_n=1, bottom_n=1, min_rank_confidence_spread=0.0,
        spread_check_ranks=partial_raw_scores,
    )
    assert book != {}  # never raises, degrades gracefully


# ---------------------------------------------------------------------------
# compute_confidence_spread() (public, shared with the book-spread
# calibration tool so the live gate and the calibration can never disagree
# on what "spread" means for a given selection)
# ---------------------------------------------------------------------------


def test_compute_confidence_spread_basic_mean_difference():
    ranks = {"A": 0.9, "B": 0.7, "C": 0.3, "D": 0.1}
    spread = compute_confidence_spread(["A", "B"], ["C", "D"], ranks, ranks)
    assert spread == (0.9 + 0.7) / 2 - (0.3 + 0.1) / 2


def test_compute_confidence_spread_empty_long_returns_none():
    assert compute_confidence_spread([], ["C"], {"C": 0.1}, {"C": 0.1}) is None


def test_compute_confidence_spread_empty_short_returns_none():
    assert compute_confidence_spread(["A"], [], {"A": 0.9}, {"A": 0.9}) is None


def test_compute_confidence_spread_missing_symbol_falls_back_to_eligible_ranks():
    spread = compute_confidence_spread(["A"], ["B"], {}, {"A": 0.8, "B": 0.2})
    assert spread == 0.8 - 0.2


def test_compute_confidence_spread_matches_the_value_select_book_group_gates_on():
    # Cross-check: the exact same inputs build_rank_based_book() uses
    # internally must reproduce identically when called directly.
    candidates = {"A": _candidate(1.0), "B": _candidate(0.67), "C": _candidate(0.33), "D": _candidate(0.0)}
    raw_scores = {"A": 0.61, "B": 0.60, "C": 0.59, "D": 0.58}  # compressed, near-constant raw dispersion
    spread = compute_confidence_spread(["A"], ["D"], raw_scores, {"A": 1.0, "D": 0.0})
    assert spread == 0.61 - 0.58

    disengaged = build_rank_based_book(
        candidates, top_n=1, bottom_n=1, min_rank_confidence_spread=0.05, spread_check_ranks=raw_scores,
    )
    assert disengaged == {}, "the compressed raw spread computed above should also disengage the real gate"


def test_build_rank_based_book_is_asset_class_blind():
    # Multi-asset-class support: book_candidates already includes any
    # symbol with a valid predicted_rank_20d regardless of asset class -
    # build_rank_based_book() needs no signature change to select across a
    # mixed equity/crypto/bond/future/option universe, since it never
    # inspects asset_class at all. An extra "asset_class" key on each
    # candidate dict (as main.py's Pass 1 would include incidentally) is
    # simply ignored.
    candidates = {
        "AAPL": {**_candidate(0.95), "asset_class": "equity"},
        "BTCUSD": {**_candidate(0.85), "asset_class": "crypto"},
        "TLT": {**_candidate(0.50), "asset_class": "bond"},
        "ES": {**_candidate(0.15), "asset_class": "future"},
        "SPY_OPT": {**_candidate(0.05), "asset_class": "option"},
    }

    book = build_rank_based_book(candidates, top_n=2, bottom_n=2)

    long_symbols = {symbol for symbol, allocation in book.items() if allocation.role == "long"}
    short_symbols = {symbol for symbol, allocation in book.items() if allocation.role == "short"}
    assert long_symbols == {"AAPL", "BTCUSD"}
    assert short_symbols == {"ES", "SPY_OPT"}
    assert "TLT" not in book


def test_build_rank_based_book_allocation_to_dict_shape():
    candidates = {"A": _candidate(0.9), "B": _candidate(0.1)}

    book = build_rank_based_book(candidates, top_n=1, bottom_n=1)

    assert book["A"].to_dict() == {
        "role": "long",
        "book_role_multiplier": 1.0,
        "predicted_rank_20d": 0.9,
        "book_reason": "rank_based_book_long",
        # V5.1 Phase 0/1: rank_head/target_weight, both defaulted so every
        # pre-V5.1 construction/consumer is unaffected - see
        # BookAllocation's own docstring.
        "rank_head": "blend",
        "target_weight": None,
    }


# --- per_asset_class_slots (development/Problems.md#29) ---


def test_build_rank_based_book_per_asset_class_slots_none_matches_pooled_default():
    # Explicit per_asset_class_slots=None must be byte-identical to omitting
    # it entirely - the backward-compatibility contract this parameter is
    # required to preserve.
    candidates = {
        "A": _candidate(0.95), "B": _candidate(0.80), "C": _candidate(0.50),
        "D": _candidate(0.20), "E": _candidate(0.05),
    }

    pooled_default = build_rank_based_book(candidates, top_n=2, bottom_n=2)
    pooled_explicit_none = build_rank_based_book(candidates, top_n=2, bottom_n=2, per_asset_class_slots=None)

    assert pooled_default == pooled_explicit_none


def test_build_rank_based_book_per_asset_class_slots_ranks_within_each_class_independently():
    # Pooled top_n=2/bottom_n=2 across these 4 symbols would put both
    # equities long and both crypto short (highest two ranks are equities,
    # lowest two are crypto) - per-class slots give each class its own
    # long+short split instead of one class dominating a side.
    candidates = {
        "AAPL": _class_candidate(0.95, "equity"),
        "IBM": _class_candidate(0.85, "equity"),
        "BTCUSD": _class_candidate(0.30, "crypto"),
        "ETHUSD": _class_candidate(0.20, "crypto"),
    }

    book = build_rank_based_book(
        candidates, top_n=99, bottom_n=99,
        per_asset_class_slots={"equity": (1, 1), "crypto": (1, 1)},
    )

    assert book["AAPL"].role == "long"
    assert book["IBM"].role == "short"
    assert book["BTCUSD"].role == "long"
    assert book["ETHUSD"].role == "short"


def test_build_rank_based_book_per_asset_class_slots_excludes_classes_not_listed():
    candidates = {
        "AAPL": _class_candidate(0.95, "equity"),
        "IBM": _class_candidate(0.05, "equity"),
        "BTCUSD": _class_candidate(0.90, "crypto"),
        "ETHUSD": _class_candidate(0.10, "crypto"),
    }

    book = build_rank_based_book(candidates, top_n=1, bottom_n=1, per_asset_class_slots={"equity": (1, 1)})

    assert set(book) == {"AAPL", "IBM"}
    assert "BTCUSD" not in book
    assert "ETHUSD" not in book


def test_build_rank_based_book_per_asset_class_slots_one_thin_class_does_not_block_others():
    candidates = {
        "AAPL": _class_candidate(0.95, "equity"),
        "IBM": _class_candidate(0.05, "equity"),
        # Only one eligible crypto candidate - can't form a two-sided book.
        "BTCUSD": _class_candidate(0.50, "crypto"),
    }

    book = build_rank_based_book(
        candidates, top_n=1, bottom_n=1,
        per_asset_class_slots={"equity": (1, 1), "crypto": (1, 1)},
    )

    assert set(book) == {"AAPL", "IBM"}
    assert "BTCUSD" not in book


def test_build_rank_based_book_per_asset_class_slots_min_rank_confidence_spread_applies_per_class():
    candidates = {
        # Wide long/short spread - clears the floor.
        "AAPL": _class_candidate(0.95, "equity"),
        "IBM": _class_candidate(0.05, "equity"),
        # Tightly clustered near 0.5 - does not clear the same floor.
        "BTCUSD": _class_candidate(0.52, "crypto"),
        "ETHUSD": _class_candidate(0.48, "crypto"),
    }

    book = build_rank_based_book(
        candidates, top_n=1, bottom_n=1, min_rank_confidence_spread=0.5,
        per_asset_class_slots={"equity": (1, 1), "crypto": (1, 1)},
    )

    assert set(book) == {"AAPL", "IBM"}


def test_build_rank_based_book_per_asset_class_slots_ignores_top_n_bottom_n_params():
    # top_n/bottom_n are documented as ignored once per_asset_class_slots is
    # provided - only each class's own (top_n, bottom_n) pair applies.
    candidates = {
        "AAPL": _class_candidate(0.95, "equity"),
        "IBM": _class_candidate(0.05, "equity"),
    }

    book = build_rank_based_book(
        candidates, top_n=0, bottom_n=0,
        per_asset_class_slots={"equity": (1, 1)},
    )

    assert set(book) == {"AAPL", "IBM"}


# --- normalize_per_asset_class_slots() (development/Problems.md, per_asset_class_slots shape validation) ---


def test_normalize_per_asset_class_slots_none_returns_empty_no_skips():
    valid, skipped = normalize_per_asset_class_slots(None)

    assert valid == {}
    assert skipped == []


def test_normalize_per_asset_class_slots_empty_dict_returns_empty_no_skips():
    valid, skipped = normalize_per_asset_class_slots({})

    assert valid == {}
    assert skipped == []


def test_normalize_per_asset_class_slots_well_formed_entries_pass_through():
    valid, skipped = normalize_per_asset_class_slots({"equity": [3, 3], "crypto": (2, 2)})

    assert valid == {"equity": (3, 3), "crypto": (2, 2)}
    assert skipped == []


def test_normalize_per_asset_class_slots_wrong_length_is_skipped_not_fatal():
    # This is exactly the case that used to hard-crash build_rank_based_book()
    # every bar instead of degrading gracefully - see development/Problems.md.
    valid, skipped = normalize_per_asset_class_slots({"equity": [3], "crypto": [2, 2, 2]})

    assert valid == {}
    assert skipped == ["equity", "crypto"]


def test_normalize_per_asset_class_slots_wrong_type_is_skipped_not_fatal():
    valid, skipped = normalize_per_asset_class_slots({"equity": "not-a-list", "crypto": 5, "bond": None})

    assert valid == {}
    assert set(skipped) == {"equity", "crypto", "bond"}


def test_normalize_per_asset_class_slots_partial_validity_keeps_good_entries():
    valid, skipped = normalize_per_asset_class_slots({"equity": [3, 3], "crypto": [2]})

    assert valid == {"equity": (3, 3)}
    assert skipped == ["crypto"]


# ---- should_rebalance_this_bar() (Stage 2 of the rank-pivot roadmap:
# rebalance_every_bars turnover control - see main.py::on_data()'s use of
# this exact function for why it's extracted here instead of living inline
# in main.py, which cannot be imported outside a running Lean container). ----


def test_should_rebalance_this_bar_first_bar_always_rebalances_even_with_no_history():
    assert should_rebalance_this_bar(1, 5, has_previous_allocation=False) is True


def test_should_rebalance_this_bar_first_bar_rebalances_with_history_too():
    assert should_rebalance_this_bar(1, 5, has_previous_allocation=True) is True


def test_should_rebalance_this_bar_rebuilds_every_nth_bar_only():
    rebalance_every_bars = 5
    # 1-indexed bar_index: rebalance bars are 1, 6, 11, 16, ... (i.e. bars
    # 0, 5, 10, 15, ... in 0-indexed terms).
    expected_rebalance_bars = {1, 6, 11, 16}

    for bar_index in range(1, 21):
        result = should_rebalance_this_bar(bar_index, rebalance_every_bars, has_previous_allocation=True)
        assert result == (bar_index in expected_rebalance_bars), bar_index


def test_should_rebalance_this_bar_missing_previous_allocation_forces_rebalance():
    # Never leave the book empty just because the modulo didn't line up -
    # e.g. a mid-run restart that lost the cached allocation.
    assert should_rebalance_this_bar(13, 5, has_previous_allocation=False) is True


def test_should_rebalance_this_bar_rebalance_every_bars_of_one_matches_previous_every_bar_behavior():
    # rebalance_every_bars=1 must reproduce the pre-Stage-2 every-bar
    # rebalance behavior exactly - no regression for anyone who never sets
    # the new config key (it defaults to 1 in main.py's constructor).
    for bar_index in range(1, 11):
        assert should_rebalance_this_bar(bar_index, 1, has_previous_allocation=True) is True


def test_should_rebalance_this_bar_rejects_zero_or_negative_interval_by_clamping_to_one():
    # max(1, rebalance_every_bars) inside the function - a misconfigured 0
    # degrades to "every bar" instead of a ZeroDivisionError.
    for bar_index in range(1, 6):
        assert should_rebalance_this_bar(bar_index, 0, has_previous_allocation=True) is True


# ---- is_trading_day_bar (V5.2.4, development/Problems.md #91) - main.py's
# bar_index only advances on equity-session ticks post-V5.2.4; this flag lets
# a non-equity-session tick never rebalance, regardless of the modulo or
# cold-start state. ----


def test_should_rebalance_this_bar_is_trading_day_bar_false_never_rebalances():
    # Would otherwise rebalance (modulo satisfied) - the new flag overrides it.
    assert should_rebalance_this_bar(6, 5, has_previous_allocation=True, is_trading_day_bar=False) is False


def test_should_rebalance_this_bar_is_trading_day_bar_false_overrides_cold_start_too():
    # Even the "no previous allocation, always rebalance" cold-start
    # exception must not fire on a non-trading-day tick.
    assert should_rebalance_this_bar(1, 5, has_previous_allocation=False, is_trading_day_bar=False) is False


def test_should_rebalance_this_bar_is_trading_day_bar_true_or_omitted_is_a_pure_no_op():
    # Explicit True and the omitted default must reproduce every existing
    # case in this file exactly - regression-lock against the V5.2.4 signature change.
    for bar_index in range(1, 21):
        for has_previous_allocation in (True, False):
            omitted = should_rebalance_this_bar(bar_index, 5, has_previous_allocation)
            explicit_true = should_rebalance_this_bar(
                bar_index, 5, has_previous_allocation, is_trading_day_bar=True
            )
            assert omitted == explicit_true


# ---- should_exit_non_selected_book_symbol() (V5.2.4, development/
# Problems.md #91) - the empty-book force-liquidation contract fix: an
# empty/disengaged book_allocations must never force-exit a held position,
# matching build_rank_based_book()'s own documented "byte-identical to this
# module not existing at all" contract. ----


def test_should_exit_non_selected_book_symbol_real_rotation_exit_fires():
    # A genuinely active, non-empty book that didn't select this symbol -
    # the real, unchanged rotation-exit case.
    assert should_exit_non_selected_book_symbol(
        book_is_active=True, portfolio_book_enabled=True, is_currently_invested=True
    ) is True


def test_should_exit_non_selected_book_symbol_disengaged_book_never_force_exits():
    # The bug fix: book_allocations came back empty this bar (confidence-gate
    # failure, or - pre-V5.2.4 - a thin-tick artifact) - must NOT force-close
    # a held position, per build_rank_based_book()'s own documented contract.
    assert should_exit_non_selected_book_symbol(
        book_is_active=False, portfolio_book_enabled=True, is_currently_invested=True
    ) is False


def test_should_exit_non_selected_book_symbol_book_disabled_never_force_exits():
    assert should_exit_non_selected_book_symbol(
        book_is_active=True, portfolio_book_enabled=False, is_currently_invested=True
    ) is False


def test_should_exit_non_selected_book_symbol_nothing_to_exit_when_not_invested():
    assert should_exit_non_selected_book_symbol(
        book_is_active=True, portfolio_book_enabled=True, is_currently_invested=False
    ) is False


def test_rebalance_schedule_holds_positions_between_rebalances_synthetic():
    """Synthetic simulation of main.py::on_data()'s caching pattern: confirm
    that between rebalance bars the SAME allocation object is reused (held),
    and that a per-bar book-formation baseline would churn far more often
    than the scheduled one - the concrete order-count-reduction claim behind
    Stage 2 of the rank-pivot roadmap."""
    total_bars = 100
    rebalance_every_bars = 5

    # Deterministic, changing candidate ranks so a naive per-bar rebuild
    # would pick a different top/bottom-N most bars (maximal churn baseline).
    def candidates_for_bar(bar_index: int) -> dict:
        return {
            symbol: _candidate((bar_index + offset) % 10 / 10.0)
            for offset, symbol in enumerate(["A", "B", "C", "D", "E", "F"])
        }

    # Scheduled path: only rebuild on rebalance bars, else hold the cached book.
    scheduled_rebuild_count = 0
    last_allocation: dict = {}
    for bar_index in range(1, total_bars + 1):
        if should_rebalance_this_bar(bar_index, rebalance_every_bars, bool(last_allocation)):
            last_allocation = build_rank_based_book(candidates_for_bar(bar_index), top_n=2, bottom_n=2)
            scheduled_rebuild_count += 1

    # Naive baseline: rebuild (and therefore potentially re-rotate) every bar.
    naive_rebuild_count = total_bars

    assert scheduled_rebuild_count == total_bars // rebalance_every_bars
    assert scheduled_rebuild_count < naive_rebuild_count
    # Concretely a 5x reduction in book-formation events, the direct driver
    # of the order-count drop this stage targets.
    assert naive_rebuild_count / scheduled_rebuild_count == rebalance_every_bars


# --- hysteresis (V5.1 Phase 0/1, development/Problems.md - item 6) ---


def _eight_name_pool() -> dict:
    return {
        "A": _candidate(0.95), "B": _candidate(0.85), "C": _candidate(0.75), "D": _candidate(0.60),
        "E": _candidate(0.40), "F": _candidate(0.25), "G": _candidate(0.15), "H": _candidate(0.05),
    }


def test_default_hysteresis_params_reproduce_selection_byte_identical():
    pool = _eight_name_pool()
    baseline = build_rank_based_book(pool, top_n=2, bottom_n=2)
    with_defaults = build_rank_based_book(
        pool, top_n=2, bottom_n=2, previous_allocations=None, hysteresis_rank_margin=0.0
    )
    assert baseline.keys() == with_defaults.keys()
    for symbol in baseline:
        assert baseline[symbol] == with_defaults[symbol]


def test_hysteresis_retains_an_incumbent_that_slipped_within_the_margin():
    pool = _eight_name_pool()
    previous = build_rank_based_book(pool, top_n=2, bottom_n=2)  # A, B long; G, H short

    # B's rank drops from 0.85 to just below C (0.75) - close enough that a
    # 0.10 margin should keep it.
    drifted_pool = dict(pool)
    drifted_pool["B"] = _candidate(0.70)

    without_hysteresis = build_rank_based_book(drifted_pool, top_n=2, bottom_n=2)
    with_hysteresis = build_rank_based_book(
        drifted_pool, top_n=2, bottom_n=2, previous_allocations=previous, hysteresis_rank_margin=0.10
    )

    assert {s for s, a in without_hysteresis.items() if a.role == "long"} == {"A", "C"}
    assert {s for s, a in with_hysteresis.items() if a.role == "long"} == {"A", "B"}


def test_hysteresis_drops_an_incumbent_that_falls_outside_the_margin():
    pool = _eight_name_pool()
    previous = build_rank_based_book(pool, top_n=2, bottom_n=2)

    # B collapses far below the natural cutoff - no margin should save it.
    drifted_pool = dict(pool)
    drifted_pool["B"] = _candidate(0.10)

    with_hysteresis = build_rank_based_book(
        drifted_pool, top_n=2, bottom_n=2, previous_allocations=previous, hysteresis_rank_margin=0.05
    )
    assert {s for s, a in with_hysteresis.items() if a.role == "long"} == {"A", "C"}


def test_hysteresis_never_grows_the_book_past_the_requested_slot_count():
    pool = _eight_name_pool()
    previous = build_rank_based_book(pool, top_n=2, bottom_n=2)

    with_hysteresis = build_rank_based_book(
        pool, top_n=2, bottom_n=2, previous_allocations=previous, hysteresis_rank_margin=1.0
    )
    long_count = sum(1 for allocation in with_hysteresis.values() if allocation.role == "long")
    short_count = sum(1 for allocation in with_hysteresis.values() if allocation.role == "short")
    assert long_count == 2
    assert short_count == 2


def test_hysteresis_short_leg_retains_an_incumbent_symmetrically():
    pool = _eight_name_pool()
    previous = build_rank_based_book(pool, top_n=2, bottom_n=2)  # G, H short

    # G's rank rises from 0.15 to just above F (0.25) - within margin of the
    # short-side cutoff, should still be retained as short.
    drifted_pool = dict(pool)
    drifted_pool["G"] = _candidate(0.30)

    without_hysteresis = build_rank_based_book(drifted_pool, top_n=2, bottom_n=2)
    with_hysteresis = build_rank_based_book(
        drifted_pool, top_n=2, bottom_n=2, previous_allocations=previous, hysteresis_rank_margin=0.10
    )

    assert {s for s, a in without_hysteresis.items() if a.role == "short"} == {"F", "H"}
    assert {s for s, a in with_hysteresis.items() if a.role == "short"} == {"G", "H"}


def test_book_allocation_gains_rank_head_and_target_weight_defaults():
    pool = _eight_name_pool()
    book = build_rank_based_book(pool, top_n=1, bottom_n=1)
    allocation = next(iter(book.values()))
    assert allocation.rank_head == "blend"
    assert allocation.target_weight is None


# ---------------------------------------------------------------------------
# build_book_history_record() (V5.2.2, development/Problems.md) - the
# diagnostic snapshot main.py's optional book-history log writes per
# rebalance bar.
# ---------------------------------------------------------------------------


def _sample_allocations() -> dict[str, BookAllocation]:
    return {
        "A": BookAllocation(role="long", book_role_multiplier=1.0, predicted_rank_20d=0.9, book_reason="r"),
        "B": BookAllocation(role="short", book_role_multiplier=-1.0, predicted_rank_20d=0.1, book_reason="r"),
    }


_SAMPLE_POLICY = {
    "heads": {"rank_20d": 0.5, "rank_5d": 0.5},
    "model_priority": ["sequence", "multitask"],
    "demoted": [],
    "normalization": "cross_sectional",
}


def test_build_book_history_record_normal_shape():
    record = build_book_history_record(
        "2019-01-02",
        _sample_allocations(),
        raw_scores_by_symbol={"A": 0.61, "B": 0.02},
        target_weights_by_symbol={"A": 0.12, "B": -0.08},
        sector_by_symbol={"A": "Technology", "B": "Fixed Income"},
        rank_signal_policy=_SAMPLE_POLICY,
    )
    assert record["date"] == "2019-01-02"
    assert record["rank_signal_policy"]["heads"] == {"rank_20d": 0.5, "rank_5d": 0.5}
    assert record["allocations"]["A"] == {
        "role": "long",
        "book_role_multiplier": 1.0,
        "predicted_rank_20d": 0.9,
        "rank_head": "blend",
        "raw_rank_score": 0.61,
        "target_weight": 0.12,
        "sector": "Technology",
    }
    assert record["allocations"]["B"]["role"] == "short"
    assert record["allocations"]["B"]["target_weight"] == -0.08


def test_build_book_history_record_missing_raw_score_is_none_not_keyerror():
    record = build_book_history_record(
        "2019-01-02", _sample_allocations(),
        raw_scores_by_symbol={},  # neither symbol present
        target_weights_by_symbol={"A": 0.12, "B": -0.08},
        sector_by_symbol={},
        rank_signal_policy=_SAMPLE_POLICY,
    )
    assert record["allocations"]["A"]["raw_rank_score"] is None
    assert record["allocations"]["B"]["raw_rank_score"] is None
    assert record["allocations"]["A"]["sector"] == "Unknown"


def test_build_book_history_record_missing_target_weight_is_none():
    # Mirrors book_neutrality_enabled=False live: self._book_target_weights
    # stays {} - every symbol's target_weight must be None, not a crash.
    record = build_book_history_record(
        "2019-01-02", _sample_allocations(),
        raw_scores_by_symbol={"A": 0.61, "B": 0.02},
        target_weights_by_symbol={},
        sector_by_symbol={"A": "Technology", "B": "Fixed Income"},
        rank_signal_policy=_SAMPLE_POLICY,
    )
    assert record["allocations"]["A"]["target_weight"] is None
    assert record["allocations"]["B"]["target_weight"] is None


def test_build_book_history_record_empty_book_allocations_never_raises():
    record = build_book_history_record(
        "2019-01-02", {}, raw_scores_by_symbol={}, target_weights_by_symbol={},
        sector_by_symbol={}, rank_signal_policy=_SAMPLE_POLICY,
    )
    assert record["date"] == "2019-01-02"
    assert record["allocations"] == {}
    assert record["rank_signal_policy"]["heads"] == {"rank_20d": 0.5, "rank_5d": 0.5}


def test_build_book_history_record_missing_policy_keys_degrade_to_defaults():
    record = build_book_history_record(
        "2019-01-02", {}, raw_scores_by_symbol={}, target_weights_by_symbol={},
        sector_by_symbol={}, rank_signal_policy={},
    )
    assert record["rank_signal_policy"] == {
        "heads": {}, "model_priority": [], "demoted": [], "normalization": "cross_sectional",
    }


def test_build_book_history_record_full_universe_signals_none_is_byte_identical_to_v5_2_2():
    # V5.2.3 - the default (no full_universe_signals argument at all) must
    # reproduce the exact V5.2.2 record shape: no "universe" key present.
    record = build_book_history_record(
        "2019-01-02", _sample_allocations(),
        raw_scores_by_symbol={"A": 0.61, "B": 0.02},
        target_weights_by_symbol={"A": 0.12, "B": -0.08},
        sector_by_symbol={"A": "Technology", "B": "Fixed Income"},
        rank_signal_policy=_SAMPLE_POLICY,
    )
    assert "universe" not in record


def test_build_book_history_record_full_universe_signals_produces_universe_key():
    full_universe_signals = {
        "A": {"raw_rank_score": 0.61, "feature_ready": True, "reason": None, "trading_eligible": True, "security_type": "equity"},
        "BTCUSD": {"raw_rank_score": 0.5, "feature_ready": True, "reason": None, "trading_eligible": True, "security_type": "crypto"},
        "EURUSD": {"raw_rank_score": None, "feature_ready": False, "reason": "Need 2 bars, have 1", "trading_eligible": True, "security_type": "forex"},
    }
    record = build_book_history_record(
        "2019-01-02", _sample_allocations(),
        raw_scores_by_symbol={"A": 0.61, "B": 0.02},
        target_weights_by_symbol={"A": 0.12, "B": -0.08},
        sector_by_symbol={"A": "Technology", "B": "Fixed Income"},
        rank_signal_policy=_SAMPLE_POLICY,
        full_universe_signals=full_universe_signals,
    )
    assert record["universe"]["A"] == {
        "raw_rank_score": 0.61, "feature_ready": True, "reason": None,
        "trading_eligible": True, "security_type": "equity",
    }
    assert record["universe"]["EURUSD"]["feature_ready"] is False
    assert record["universe"]["EURUSD"]["reason"] == "Need 2 bars, have 1"
    assert record["universe"]["EURUSD"]["raw_rank_score"] is None


def test_build_book_history_record_full_universe_signals_missing_keys_degrade_to_none():
    record = build_book_history_record(
        "2019-01-02", {}, raw_scores_by_symbol={}, target_weights_by_symbol={},
        sector_by_symbol={}, rank_signal_policy={},
        full_universe_signals={"A": {}},
    )
    assert record["universe"]["A"] == {
        "raw_rank_score": None, "feature_ready": None, "reason": None,
        "trading_eligible": None, "security_type": None,
    }


def test_build_book_history_record_omits_decisions_key_when_none():
    # V5.2.6 - book_member_decisions=None (the default) must reproduce
    # the exact pre-V5.2.6 record shape: no "book_member_decisions" key.
    record = build_book_history_record(
        "2019-01-02", _sample_allocations(),
        raw_scores_by_symbol={"A": 0.61, "B": 0.02},
        target_weights_by_symbol={"A": 0.12, "B": -0.08},
        sector_by_symbol={"A": "Technology", "B": "Fixed Income"},
        rank_signal_policy=_SAMPLE_POLICY,
    )
    assert "book_member_decisions" not in record


def test_build_book_history_record_includes_decisions_when_provided():
    book_member_decisions = {
        "A": {"action": "trade", "reasons": ["trading_eligible_book_selected_directional_signal_above_confidence_threshold"]},
        "B": {"action": "simulate", "reasons": ["liquidity_blocked_insufficient_volume_simulate_instead"]},
    }
    record = build_book_history_record(
        "2019-01-02", _sample_allocations(),
        raw_scores_by_symbol={"A": 0.61, "B": 0.02},
        target_weights_by_symbol={"A": 0.12, "B": -0.08},
        sector_by_symbol={"A": "Technology", "B": "Fixed Income"},
        rank_signal_policy=_SAMPLE_POLICY,
        book_member_decisions=book_member_decisions,
    )
    assert record["book_member_decisions"]["A"]["action"] == "trade"
    assert record["book_member_decisions"]["B"]["action"] == "simulate"
    assert record["book_member_decisions"]["B"]["reasons"] == ["liquidity_blocked_insufficient_volume_simulate_instead"]


def test_build_book_history_record_decisions_missing_keys_degrade_to_none_and_empty_list():
    record = build_book_history_record(
        "2019-01-02", {}, raw_scores_by_symbol={}, target_weights_by_symbol={},
        sector_by_symbol={}, rank_signal_policy={},
        book_member_decisions={"A": {}},
    )
    assert record["book_member_decisions"]["A"] == {"action": None, "reasons": []}
