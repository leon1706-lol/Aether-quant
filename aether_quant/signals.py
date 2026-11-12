"""Signal evaluation, grouped by the job (V6.6.5): forward targets from prices, the IC report with HAC t-statistics and
bootstrap intervals, returns by quantile, IC decay, factor spanning and purged folds."""

from aether_quant.evaluation import newey_west_t_stat, rank_ic_from_arrays
from aether_quant.research import evaluate_signal, factor_spanning, ic_summary
from aether_quant.training import purged_embargoed_folds
from evaluation.signal_tools import forward_rank_targets, forward_returns, ic_decay, quantile_returns

__all__ = [
    "evaluate_signal", "factor_spanning", "forward_rank_targets", "forward_returns", "ic_decay", "ic_summary", "newey_west_t_stat", "purged_embargoed_folds",
    "quantile_returns", "rank_ic_from_arrays",
]
