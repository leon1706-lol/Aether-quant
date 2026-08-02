"""Cross-sectional portfolio (long/short book) construction for Aether Quant V2."""

from .book_construction import (
    BookAllocation,
    build_rank_based_book,
    normalize_per_asset_class_slots,
    should_rebalance_this_bar,
)
from .book_neutrality import apply_book_neutrality
from .options_strategy import (
    OptionsPositionDecision,
    build_options_position_sizing,
    select_single_leg_contract,
)
from .rank_signal import (
    cross_sectional_rank_scores,
    resolve_rank_signal_policy,
    select_raw_rank_score,
)

__all__ = [
    "BookAllocation",
    "OptionsPositionDecision",
    "apply_book_neutrality",
    "build_options_position_sizing",
    "build_rank_based_book",
    "cross_sectional_rank_scores",
    "normalize_per_asset_class_slots",
    "resolve_rank_signal_policy",
    "select_raw_rank_score",
    "select_single_leg_contract",
    "should_rebalance_this_bar",
]
