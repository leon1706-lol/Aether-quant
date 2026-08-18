"""Phase 6 of the 5/10 -> 9/10 roadmap: production rank-IC decay
monitoring - closes a real gap. `rank_20d` is the one signal in this
codebase with a statistically significant backtest result (see
risk/position_sizing.py::rank_sizing_multiplier()'s docstring: sequence
model mean IC 0.073, t-stat 4.40 on the full series), but rank-IC was
never monitored in production at all before this - only computed offline
into `*_training_metrics.json` by train.py::compute_rank_ic().

The outcome-resolution shape here is genuinely different from every
existing trigger in performance/triggers.py: those all operate on
already-resolved experience events (the outcome - drawdown, win/loss,
confidence - is known at the moment the event was recorded). Rank-IC
can't be scored until the prediction's realized 20-trading-day forward
return is known - a "wait for the future, then join back" shape. This
module is that outcome-resolution job: given a stream of experience
events (each optionally carrying `resolved_predicted_rank_20d`/
`close_price`, see experience/redis_queue.py::build_experience_event()),
it self-joins each prediction against the SAME ticker's close ~20 TRADING
days later (not 20 calendar days - positional, within that ticker's own
event sequence, matching train.py::engineer_features()'s target_return_20d
convention of a row-indexed shift, not a calendar-day one - this
correctly respects each ticker's own trading calendar, e.g. crypto
trading every day vs. equities/bonds only on business days), computes the
realized forward return, then cross-sectionally ranks all tickers'
realized returns per origin date - reusing evaluation/rank_ic_core.py's
exact tested ranking/correlation core (no torch dependency needed here,
this module never imports torch).

V5.3.5 (development/Problems.md #102): the actual resolution/aggregation
logic now lives in evaluation/rank_ic_core.py (moved, not duplicated) so
main.py's live decision path can reuse it directly without pulling in
this module (which `performance/__init__.py` imports transitively via
`.trigger_worker`, which in turn imports `train.py`'s full torch/sklearn
stack - a real Lean-isolator-timeout risk, see development/Problems.md
#16). The two functions below are thin re-exports, kept for every
existing caller (performance/trigger_worker.py, tests/test_rank_ic_monitor.py).
"""

from __future__ import annotations

from evaluation.rank_ic_core import (
    aggregate_rank_ic_observations,
    resolve_realized_rank_ic_observations,
)


def compute_realized_rank_ic_observations(events: list[dict], horizon_days: int = 20) -> list[dict]:
    """Thin re-export of evaluation.rank_ic_core.resolve_realized_rank_ic_observations()
    - see that function's docstring for the actual algorithm."""
    return resolve_realized_rank_ic_observations(events, horizon_days)


def compute_production_rank_ic(observations: list[dict], non_overlapping_stride: int = 1) -> dict:
    """Thin re-export of evaluation.rank_ic_core.aggregate_rank_ic_observations()
    - see that function's docstring for the actual algorithm."""
    return aggregate_rank_ic_observations(observations, non_overlapping_stride=non_overlapping_stride)
