"""Overfitting tests, grouped by the job (V6.6.5): PBO by CSCV, the probabilistic and deflated Sharpe, the minimum track
record, the haircut Sharpe, placebo tests, the leakage audit and the selection gate the research rounds apply."""

from aether_quant.evaluation import deflated_sharpe_ratio, expected_max_sharpe, probabilistic_sharpe_ratio
from aether_quant.research import audit_leakage, deflated_sharpe_from_inputs, placebo_p_value, probability_of_backtest_overfitting, selection_gate
from evaluation.overfitting import haircut_sharpe, minimum_track_record_length, pbo

__all__ = [
    "audit_leakage", "deflated_sharpe_from_inputs", "deflated_sharpe_ratio", "expected_max_sharpe", "haircut_sharpe", "minimum_track_record_length", "pbo",
    "placebo_p_value", "probabilistic_sharpe_ratio", "probability_of_backtest_overfitting", "selection_gate",
]
