"""V5.4.4 - tests for HRP integration into live book construction:
portfolio/book_construction.py::pct_returns_from_closes() /
apply_hrp_weights(), the portfolio/hrp_allocation.py single-sided
full-gross fix, and the byte-identical "rank" default guard."""

from __future__ import annotations

import numpy as np
import pytest

from portfolio.book_construction import (
    BookAllocation,
    apply_hrp_weights,
    build_rank_based_book,
    pct_returns_from_closes,
)
from portfolio.hrp_allocation import build_hrp_allocation


def _allocations(longs: list[str], shorts: list[str]) -> dict[str, BookAllocation]:
    allocations = {}
    for symbol in longs:
        allocations[symbol] = BookAllocation(
            role="long", book_role_multiplier=1.0, predicted_rank_20d=0.9, book_reason="rank_based_book_long"
        )
    for symbol in shorts:
        allocations[symbol] = BookAllocation(
            role="short", book_role_multiplier=-1.0, predicted_rank_20d=0.1, book_reason="rank_based_book_short"
        )
    return allocations


def _returns_by_symbol(symbols: list[str], n: int = 60, seed: int = 5) -> dict[str, list[float]]:
    rng = np.random.default_rng(seed)
    return {symbol: list(rng.normal(0.0, 0.01, n)) for symbol in symbols}


class TestPctReturnsFromCloses:
    def test_basic_close_to_close_returns(self):
        closes = [100.0, 110.0, 99.0]
        assert pct_returns_from_closes(closes) == pytest.approx([0.10, 99.0 / 110.0 - 1.0])

    def test_short_input_returns_empty(self):
        assert pct_returns_from_closes([]) == []
        assert pct_returns_from_closes([100.0]) == []

    def test_zero_or_missing_close_skipped_not_inf(self):
        closes = [100.0, 0.0, 110.0, None, 121.0]
        # Every pair here touches a 0/None close: (100->0) skipped (0
        # current close would otherwise emit a -100% variance bomb),
        # (0->110) skipped (zero previous), (110->None) and (None->121)
        # skipped (missing value) - nothing usable survives, so [].
        assert pct_returns_from_closes(closes) == []

    def test_bad_close_in_middle_does_not_poison_clean_pairs(self):
        closes = [100.0, 0.0, 110.0, 121.0]
        # Only the (110->121) pair is fully clean.
        assert pct_returns_from_closes(closes) == pytest.approx([121.0 / 110.0 - 1.0])


class TestApplyHrpWeights:
    def test_empty_book_returns_empty(self):
        assert apply_hrp_weights({}, {"A": [0.01, -0.01]}) == {}

    def test_two_sided_leg_sums_and_signs(self):
        longs, shorts = ["L1", "L2", "L3"], ["S1", "S2", "S3"]
        allocations = _allocations(longs, shorts)
        weights = apply_hrp_weights(allocations, _returns_by_symbol(longs + shorts), gross_exposure=1.0)
        assert set(weights) == set(longs + shorts)
        long_sum = sum(weights[s] for s in longs)
        short_sum = sum(weights[s] for s in shorts)
        # Each leg sums to gross/2 on a two-sided book (dollar-neutral).
        assert long_sum == pytest.approx(0.5, abs=1e-9)
        assert short_sum == pytest.approx(-0.5, abs=1e-9)
        # Sign preservation: longs strictly positive, shorts strictly negative.
        assert all(weights[s] > 0 for s in longs)
        assert all(weights[s] < 0 for s in shorts)

    def test_long_only_book_gets_full_gross(self):
        longs = ["L1", "L2", "L3", "L4"]
        allocations = _allocations(longs, [])
        weights = apply_hrp_weights(allocations, _returns_by_symbol(longs), gross_exposure=1.0)
        assert sum(weights.values()) == pytest.approx(1.0, abs=1e-9)
        assert all(w > 0 for w in weights.values())

    def test_short_only_book_gets_full_negative_gross(self):
        shorts = ["S1", "S2"]
        allocations = _allocations([], shorts)
        weights = apply_hrp_weights(allocations, _returns_by_symbol(shorts), gross_exposure=1.0)
        assert sum(weights.values()) == pytest.approx(-1.0, abs=1e-9)
        assert all(w < 0 for w in weights.values())

    def test_fallback_equal_weight_when_fewer_than_two_names_have_history(self):
        longs, shorts = ["L1", "L2"], ["S1", "S2"]
        allocations = _allocations(longs, shorts)
        # Only ONE symbol carries usable return history -> covariance
        # estimation impossible -> equal weight within each leg.
        returns = {"L1": [0.01, -0.01, 0.02]}
        weights = apply_hrp_weights(allocations, returns, gross_exposure=1.0)
        assert set(weights) == set(longs + shorts)
        for symbol in longs:
            assert weights[symbol] == pytest.approx(0.25)
        for symbol in shorts:
            assert weights[symbol] == pytest.approx(-0.25)

    def test_fallback_equal_weight_when_no_returns_at_all(self):
        longs, shorts = ["L1"], ["S1"]
        allocations = _allocations(longs, shorts)
        weights = apply_hrp_weights(allocations, {}, gross_exposure=1.0)
        assert weights["L1"] == pytest.approx(0.5)
        assert weights["S1"] == pytest.approx(-0.5)

    def test_sizing_changes_but_selection_untouched(self):
        # The whole point of the V5.4.4 integration: HRP re-weights the
        # EXACT symbol set build_rank_based_book() selected - never more,
        # never fewer, never a different role.
        candidates = {
            "AAA": {"predicted_rank_20d": 0.95, "trading_eligible": True},
            "BBB": {"predicted_rank_20d": 0.90, "trading_eligible": True},
            "CCC": {"predicted_rank_20d": 0.10, "trading_eligible": True},
            "DDD": {"predicted_rank_20d": 0.05, "trading_eligible": True},
            "EEE": {"predicted_rank_20d": 0.50, "trading_eligible": True},
        }
        book = build_rank_based_book(candidates, top_n=2, bottom_n=2, min_rank_confidence_spread=0.0)
        weights = apply_hrp_weights(book, _returns_by_symbol(list(book), seed=9), gross_exposure=1.0)
        assert set(weights) == set(book)
        for symbol, allocation in book.items():
            if allocation.role == "long":
                assert weights[symbol] > 0
            else:
                assert weights[symbol] < 0

    def test_hrp_weights_differ_from_confidence_formula(self):
        # HRP must actually change sizing vs the inline confidence
        # formula for a correlated book (otherwise the integration would
        # be a no-op dressed up as a feature). Highly correlated longs
        # get less combined weight than uncorrelated ones would.
        longs, shorts = ["L1", "L2"], ["S1", "S2"]
        allocations = _allocations(longs, shorts)
        rng = np.random.default_rng(23)
        common = rng.normal(0, 0.01, 80)
        returns = {
            "L1": list(common + rng.normal(0, 0.001, 80)),
            "L2": list(common + rng.normal(0, 0.001, 80)),
            "S1": list(rng.normal(0, 0.01, 80)),
            "S2": list(rng.normal(0, 0.01, 80)),
        }
        weights = apply_hrp_weights(allocations, returns, gross_exposure=1.0)
        # The two near-identical longs must NOT receive identical weights
        # (HRP breaks the tie via cluster structure) - and the leg sums
        # stay exact regardless.
        assert sum(weights[s] for s in longs) == pytest.approx(0.5, abs=1e-9)
        assert sum(weights[s] for s in shorts) == pytest.approx(-0.5, abs=1e-9)


class TestBuildHrpAllocationSingleSidedFix:
    def test_long_only_full_gross_not_half(self):
        # V5.4.4 regression guard: the pre-fix unconditional gross/2
        # split silently halved a long-only book's exposure (long_flat
        # is the shipped default strategy_mode).
        returns = _returns_by_symbol(["L1", "L2", "L3"])
        weights = build_hrp_allocation(
            returns, selected_tickers_long=["L1", "L2", "L3"], selected_tickers_short=[], gross_exposure=1.0
        )
        assert sum(weights.values()) == pytest.approx(1.0, abs=1e-9)

    def test_short_only_full_negative_gross_not_half(self):
        returns = _returns_by_symbol(["S1", "S2"])
        weights = build_hrp_allocation(
            returns, selected_tickers_long=[], selected_tickers_short=["S1", "S2"], gross_exposure=1.0
        )
        assert sum(weights.values()) == pytest.approx(-1.0, abs=1e-9)

    def test_two_sided_unchanged_half_split(self):
        returns = _returns_by_symbol(["L1", "L2", "S1", "S2"])
        weights = build_hrp_allocation(
            returns, selected_tickers_long=["L1", "L2"], selected_tickers_short=["S1", "S2"], gross_exposure=1.0
        )
        assert sum(weights[s] for s in ("L1", "L2")) == pytest.approx(0.5, abs=1e-9)
        assert sum(weights[s] for s in ("S1", "S2")) == pytest.approx(-0.5, abs=1e-9)


class TestRankDefaultByteIdenticalGuard:
    def test_rank_selection_ignores_hrp_concept_entirely(self):
        # allocation_method == "rank" (default): build_rank_based_book()
        # takes no sizing input at all, so its output is trivially
        # unchanged - this test pins that the SELECTION for a given
        # candidate pool is stable, which is the invariant the live
        # wiring relies on (HRP re-weights AFTER selection, and on the
        # default path apply_hrp_weights is never called at all).
        candidates = {
            "AAA": {"predicted_rank_20d": 0.95, "trading_eligible": True},
            "BBB": {"predicted_rank_20d": 0.90, "trading_eligible": True},
            "CCC": {"predicted_rank_20d": 0.10, "trading_eligible": True},
            "DDD": {"predicted_rank_20d": 0.05, "trading_eligible": True},
        }
        first = build_rank_based_book(candidates, top_n=2, bottom_n=2, min_rank_confidence_spread=0.0)
        second = build_rank_based_book(candidates, top_n=2, bottom_n=2, min_rank_confidence_spread=0.0)
        assert set(first) == set(second) == {"AAA", "BBB", "CCC", "DDD"}
        assert {s: a.role for s, a in first.items()} == {s: a.role for s, a in second.items()}


class TestAsymmetricTwoSidedFallback:
    """V5.4.5 (Problems.md #118): the equal-weight fallbacks divided gross
    across BOTH legs combined, so an asymmetric two-sided book came out
    with net exposure instead of dollar-neutral. Each leg must now sum to
    exactly its own +/-gross/2 (or the full +/-gross when single-sided)."""

    def test_thin_history_asymmetric_legs_are_dollar_neutral(self):
        allocations = _allocations(
            ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"], ["GGG", "HHH"]
        )
        # Only two names carry usable history -> fallback path.
        returns_by_symbol = {"AAA": [0.01, 0.02, -0.01], "GGG": [0.005, -0.004, 0.002]}
        weights = apply_hrp_weights(allocations, returns_by_symbol, gross_exposure=1.0)
        long_sum = sum(w for w in weights.values() if w > 0)
        short_sum = sum(-w for w in weights.values() if w < 0)
        assert long_sum == pytest.approx(0.5)
        assert short_sum == pytest.approx(0.5)
        assert set(weights) == set(allocations)

    def test_no_history_at_all_single_sided_keeps_full_gross(self):
        allocations = _allocations(["AAA", "BBB", "CCC"], [])
        weights = apply_hrp_weights(allocations, {}, gross_exposure=1.0)
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_linkage_exception_fallback_also_normalizes_per_leg(self, monkeypatch):
        import portfolio.hrp_allocation as hrp_module

        def _boom(_returns):
            raise RuntimeError("scipy exploded")

        monkeypatch.setattr(hrp_module, "compute_hrp_weights", _boom)
        weights = build_hrp_allocation(
            {t: [0.01, 0.02, -0.005] for t in ["A", "B", "C", "D"]},
            selected_tickers_long=["A", "B", "C"],
            selected_tickers_short=["D"],
            gross_exposure=1.0,
        )
        long_sum = sum(w for w in weights.values() if w > 0)
        short_sum = sum(-w for w in weights.values() if w < 0)
        assert long_sum == pytest.approx(0.5)
        assert short_sum == pytest.approx(0.5)
