"""V5.3.5 (development/Problems.md #102): a rolling TRAILING realized-IC
gate for book engagement - the direct sibling of
portfolio/book_construction.py::compute_confidence_spread()'s consumer in
_select_book_group(), added because dispersion and skill turned out to be
different things a real backtest could tell apart even when the existing
min_rank_confidence_spread gate couldn't.

Background: #102 found that lowering min_rank_confidence_spread (which
only measures whether the model's raw scores are DISPERSED today) let the
live book trade through real, historically bad stretches where the
model's own per-era IC diagnostic (#71) is near-zero or negative - a
day's scores can look perfectly "spread out" while carrying zero genuine
predictive validity. This module adds an independent, second veto based
on TRAILING REALIZED IC (was the model actually right, recently) rather
than same-day dispersion.

Deliberately its own module, not folded into book_construction.py or
risk/kill_switch.py:
  - book_construction.py is same-bar cross-sectional selection math with
    no temporal/resolution state today (compute_confidence_spread() reads
    only this bar's own scores). This gate needs a multi-bar buffer and a
    "wait for the future, then resolve" shape - closer in spirit to
    evaluation/kill_switch_replay.py's day-by-day state-carry pattern -
    and deserves its own independently-testable home, the same
    relationship portfolio/book_neutrality.py already has to
    book_construction.py (a sibling module, imported by main.py's call
    site, not inlined).
  - risk/kill_switch.py already has a dormant `min_live_rank_ic`
    condition, but it reads `live_rank_ic` from a locally-cached file
    only a separate Postgres-connected worker ever writes
    (visualization/grafana/retraining_status.json) - which doesn't exist
    in a standalone `aq backtest` run, so that condition is a live no-op
    during backtests today. It is also a portfolio-wide sticky trade-lock
    trip (blast radius: everything), a different kind of decision from
    this module's book-construction-level, per-rebalance engagement veto
    (blast radius: this one rebalance). Wiring this module's rolling
    buffer into that kill-switch condition too would be a real, small,
    separately-verifiable follow-up - explicitly not done here, to keep
    this round's verification story to one mechanism.

Pure, deterministic, cheap - both functions below do only pandas/numpy
work over an already-assembled event list (no I/O), respecting main.py's
per-bar latency budget the same way every other pure risk/analyzer module
in this codebase does (risk/kill_switch.py, analyzer/market_analyzer.py).

Design choice: a hard, boolean gate - not a continuous position-sizing
multiplier. Every existing book-level check (min_rank_confidence_spread)
is a hard veto with a single, audit-log-able reason, and
book_construction.py's own docstring already defers continuous
rank-weighted sizing as a documented future extension rather than
building it alongside a same-round change to the selection logic itself.
A scaling multiplier for this signal specifically is the same kind of
future extension, deferred for the same reason: shipping a new signal and
a new sizing curve in the same round makes it impossible to attribute a
verification result to either one cleanly.
"""

from __future__ import annotations

from evaluation.rank_ic_core import aggregate_rank_ic_observations, resolve_realized_rank_ic_observations

# Same "this condition can never fire" sentinel convention as
# risk/kill_switch.py::_NEVER_BELOW - enabling this gate must never, by
# itself, activate an uncalibrated threshold. The real floor comes from
# evaluation/rolling_ic_gate_calibration.py, never guessed.
_NEVER_BELOW = -1e12


def compute_rolling_ic_state(
    event_buffer: list[dict],
    *,
    horizon_days: int,
    rolling_window_days: int,
    min_names_per_date: int = 2,
) -> dict:
    """Resolves `event_buffer` (main.py's own flat, in-memory
    {"ticker", "created_at", "resolved_predicted_rank_20d", "close_price"}
    deque, or the offline replay/calibration tools' equivalent) via
    evaluation.rank_ic_core.resolve_realized_rank_ic_observations(), then
    restricts to the trailing `rolling_window_days` UNIQUE resolved
    origin dates (not calendar days, and not raw observation count - a
    date with more symbols resolved must not count for more "days" of
    trailing history than a thin one) before aggregating.

    `min_names_per_date` (V5.3.5, development/Problems.md #102) - default
    2 preserves this function's original behavior exactly (see
    evaluation.rank_ic_core.rank_ic_from_arrays()'s own docstring for why
    this exists: a 2-name origin date is mathematically forced to a
    +-1 IC reading regardless of real skill, and real historical data
    confirmed this dominates the low tail of a walk-forward calibration's
    distribution). Callers evaluating a live or replayed rolling-IC
    reading - where thin-universe noise masquerading as "the model is
    badly wrong" would cause a spurious veto - should pass a value well
    above 2 (evaluation/rolling_ic_gate_calibration.py and evaluation/
    rolling_ic_gate_replay.py both default to 10, sourced from
    phase_v2.rolling_ic_gate.min_names_per_date).

    Returns {"rolling_mean_ic": float | None, "num_resolved_dates": int,
    "num_resolved_observations": int}. `rolling_mean_ic` is None (never
    0.0) when zero observations have resolved yet - "unknown" must never
    be silently treated as "IC is exactly zero" by evaluate_rolling_ic_gate()
    below, the same None-vs-neutral-default distinction every other pure
    signal function in this codebase already draws (e.g.
    risk/kill_switch.py::_rolling_sharpe())."""
    resolved = resolve_realized_rank_ic_observations(event_buffer, horizon_days=horizon_days)
    if not resolved:
        return {"rolling_mean_ic": None, "num_resolved_dates": 0, "num_resolved_observations": 0}

    unique_dates = sorted({observation["origin_date"] for observation in resolved})
    trailing_dates = set(unique_dates[-rolling_window_days:]) if rolling_window_days > 0 else set()
    trailing_observations = [observation for observation in resolved if observation["origin_date"] in trailing_dates]

    if not trailing_observations:
        return {"rolling_mean_ic": None, "num_resolved_dates": 0, "num_resolved_observations": 0}

    aggregate = aggregate_rank_ic_observations(trailing_observations, min_names_per_date=min_names_per_date)
    return {
        "rolling_mean_ic": aggregate["mean_ic"] if aggregate["num_dates"] > 0 else None,
        "num_resolved_dates": aggregate["num_dates"],
        "num_resolved_observations": len(trailing_observations),
    }


def evaluate_rolling_ic_gate(rolling_ic_state: dict, config: dict) -> dict:
    """Pure decision function - the direct sibling of
    portfolio.book_construction.compute_confidence_spread()'s consumer at
    _select_book_group(). `rolling_ic_state` is compute_rolling_ic_state()'s
    own output; `config` is phase_v2.rolling_ic_gate's dict.

    GUARDRAIL - fail-open at two levels, matching
    risk/kill_switch.py::evaluate_kill_switch()'s own documented contract:
      1. config["enabled"] is False -> always engaged, full no-op,
         regardless of any other input.
      2. num_resolved_dates < min_resolved_dates_required (default:
         config's own rolling_window_days, matching evaluate_kill_switch()'s
         min_bars_for_sharpe precedent - "the trailing window size" is the
         value's own documented intent) -> also engaged. A cold-start
         buffer (the first ~40-60 live bars of any run, before enough
         predictions have had time to resolve against a realized 20-day
         forward return) must never masquerade as "IC is bad" - it must
         masquerade as "gate not evaluated yet".

    Returns {"engaged": bool, "reason": str, "observed_rolling_mean_ic":
    float | None, "min_rolling_mean_ic": float, "num_resolved_dates": int}."""
    min_rolling_mean_ic = float(config.get("min_rolling_mean_ic", _NEVER_BELOW))
    num_resolved_dates = int(rolling_ic_state.get("num_resolved_dates", 0))
    observed_rolling_mean_ic = rolling_ic_state.get("rolling_mean_ic")

    if not bool(config.get("enabled", False)):
        return {
            "engaged": True,
            "reason": "rolling_ic_gate_disabled",
            "observed_rolling_mean_ic": observed_rolling_mean_ic,
            "min_rolling_mean_ic": min_rolling_mean_ic,
            "num_resolved_dates": num_resolved_dates,
        }

    min_resolved_dates_required = int(config.get("min_resolved_dates_required", config.get("rolling_window_days", 40)))
    if num_resolved_dates < min_resolved_dates_required or observed_rolling_mean_ic is None:
        return {
            "engaged": True,
            "reason": "rolling_ic_gate_insufficient_history",
            "observed_rolling_mean_ic": observed_rolling_mean_ic,
            "min_rolling_mean_ic": min_rolling_mean_ic,
            "num_resolved_dates": num_resolved_dates,
        }

    if observed_rolling_mean_ic < min_rolling_mean_ic:
        return {
            "engaged": False,
            "reason": "rolling_ic_below_floor",
            "observed_rolling_mean_ic": observed_rolling_mean_ic,
            "min_rolling_mean_ic": min_rolling_mean_ic,
            "num_resolved_dates": num_resolved_dates,
        }

    return {
        "engaged": True,
        "reason": "rolling_ic_above_floor",
        "observed_rolling_mean_ic": observed_rolling_mean_ic,
        "min_rolling_mean_ic": min_rolling_mean_ic,
        "num_resolved_dates": num_resolved_dates,
    }
