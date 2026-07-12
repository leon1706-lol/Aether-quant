"""Cross-sectional portfolio (long/short book) construction for Aether Quant V2."""

from .book_construction import BookAllocation, build_rank_based_book

__all__ = [
    "BookAllocation",
    "build_rank_based_book",
]
