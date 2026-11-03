"""Book construction: rank-based long/short selection, neutrality, tranches, class caps and the sleeve loss guard
(formally verified in formal/AetherFormal/{BookNeutrality,BookConstruction,SleeveGuard}.lean)."""

from portfolio.book_construction import (
    BookAllocation,
    apply_class_weight_caps,
    build_rank_based_book,
    combine_tranche_weights,
    partial_adjust_weights,
    resolve_class_weight_caps,
    tranche_book_params,
    tranche_offsets,
)
from portfolio.book_neutrality import apply_book_neutrality
from portfolio.rank_signal import cross_sectional_rank_scores, grouped_cross_sectional_rank_scores
from portfolio.sleeve_guard import SleeveGuardConfig, evaluate_sleeve_guard, resolve_sleeve_guard_config, trailing_drawdown


def compute_hrp_weights(returns):
    """Hierarchical risk parity weights (portfolio/hrp_allocation.py; needs scipy, imported on call)."""
    from portfolio.hrp_allocation import compute_hrp_weights as _compute

    return _compute(returns)


__all__ = [
    "BookAllocation",
    "SleeveGuardConfig",
    "apply_book_neutrality",
    "apply_class_weight_caps",
    "build_rank_based_book",
    "combine_tranche_weights",
    "compute_hrp_weights",
    "cross_sectional_rank_scores",
    "evaluate_sleeve_guard",
    "grouped_cross_sectional_rank_scores",
    "partial_adjust_weights",
    "resolve_class_weight_caps",
    "resolve_sleeve_guard_config",
    "trailing_drawdown",
    "tranche_book_params",
    "tranche_offsets",
]
