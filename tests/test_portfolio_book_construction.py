"""Tests for portfolio/book_construction.py::build_rank_based_book() (Phase 3
of the 5/10 -> 9/10 roadmap). Conventions match the rest of this repo:
no test classes, module-level helpers, plain dicts.
"""

from portfolio.book_construction import build_rank_based_book


def _candidate(rank: float | None, trading_eligible: bool = True) -> dict:
    return {"predicted_rank_20d": rank, "trading_eligible": trading_eligible}


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


def test_build_rank_based_book_zero_top_n_or_bottom_n_returns_empty():
    candidates = {"A": _candidate(0.9), "B": _candidate(0.1)}

    assert build_rank_based_book(candidates, top_n=0, bottom_n=1) == {}
    assert build_rank_based_book(candidates, top_n=1, bottom_n=0) == {}


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
    }
