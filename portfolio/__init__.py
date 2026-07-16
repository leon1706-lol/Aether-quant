"""Cross-sectional portfolio (long/short book) construction for Aether Quant V2."""

from .book_construction import BookAllocation, build_rank_based_book, normalize_per_asset_class_slots
from .options_strategy import (
    OptionsPositionDecision,
    build_options_position_sizing,
    select_single_leg_contract,
)

__all__ = [
    "BookAllocation",
    "OptionsPositionDecision",
    "build_options_position_sizing",
    "build_rank_based_book",
    "normalize_per_asset_class_slots",
    "select_single_leg_contract",
]
