"""Offline, cost-aware evaluation of the cross-sectional rank book (V5.1
Phase 0) - turns "how good is this rank prediction" into "what would this
have actually earned net of fees", the question nothing else in this
codebase answers (train.py::compute_strategy_metrics() simulates a
long-only 1-day-direction strategy gross of costs, not the rank book, and
not net-of-cost). Deliberately its own package, not folded into
retraining/ or performance/: pure numpy/pandas, NO torch import, so both of
those (and any future Postgres-fed monitoring job) can import it without
pulling in the training stack - the same torch-free-core convention
train.py::_rank_ic_from_arrays() already established for its own metric.
"""

from .ablation import (
    ABLATION_VARIANTS,
    NOT_OFFLINE_MEASURABLE_VARIANTS,
    compare_static_vs_retrained,
    run_ablation,
    simulate_static_baseline,
)
from .model_predictions import (
    build_sequence_windows,
    predict_head,
    predict_multitask_head,
    predict_sequence_head,
)
from .rank_book_simulator import (
    RankBookSimulationResult,
    capacity_curve,
    simulate_rank_book,
    stress_test_costs,
    summarize_metric_stability,
)

__all__ = [
    "ABLATION_VARIANTS",
    "NOT_OFFLINE_MEASURABLE_VARIANTS",
    "RankBookSimulationResult",
    "build_sequence_windows",
    "capacity_curve",
    "compare_static_vs_retrained",
    "predict_head",
    "predict_multitask_head",
    "predict_sequence_head",
    "run_ablation",
    "simulate_rank_book",
    "simulate_static_baseline",
    "stress_test_costs",
    "summarize_metric_stability",
]
