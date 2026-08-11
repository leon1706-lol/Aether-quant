"""V5.2.8 (development/Problems.md #94) - a day-by-day OFFLINE replay of
main.py's kill-switch + sticky-trade-lock state machine, against a
purely offline return series (e.g. evaluation/rank_book_simulator.py::
simulate_rank_book()'s own per_date_net_return output) - the first
offline counterpart to any of live's ~10 risk/execution gates
(development/Problems.md #92's own finding was that NONE of them had one
before this). Follows the exact three-tier pattern already established by
evaluation/rank_signal_calibration.py's reconcile_book_history_date()/
replay_book_history_reconciliation()/summarize_book_history_reconciliation()
- a new, additive sibling module, never touching rank_book_simulator.py's
own simulate_rank_book() (that function's own docstring explicitly warns
against conflating raw ranking quality with live gate engagement - this
module answers a different question and lives separately on purpose).

APPROXIMATION, NOT GROUND TRUTH (read before trusting this module's
numbers - see development/Problems.md #94 for the full caveat and the
named follow-up this does NOT attempt): real live state at any given date
depends on the ACTUAL trade-lock/liquidation path taken on every PRIOR
date (main.py's own session-rollover block, main.py:6140-6345) - this
replay mechanically reproduces that same state machine, but only ever
sees the offline return series, never the live book's own realized
(gate-diverged) history. It models exactly two of evaluate_kill_switch()'s
7 runtime_metrics inputs (recent_bar_returns via a rolling deque,
drawdown_velocity_pct_per_bar via a running peak) plus
risk_controls.py::assess_drawdown_lock()'s daily/total drawdown breach -
both feed the SAME sticky trade-lock reason space main.py's own
session-rollover clearing logic uses. It does NOT model live_rank_ic,
consecutive_losses, slippage_divergence_bps, model_age_days, or
reconciliation_breach (no offline equivalent exists for any of these) -
they stay None throughout, which evaluate_kill_switch()'s own documented
None-skip contract degrades cleanly rather than fabricating a value for.
No bypass flags (bypass_sticky_trade_lock etc.) are modeled either - this
replay always represents the honest, non-bypassed sticky behavior."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field

from risk.kill_switch import evaluate_kill_switch
from risk_controls import assess_drawdown_lock

_RETURN_HISTORY_MAXLEN = 252


@dataclass(frozen=True)
class KillSwitchReplayRecord:
    date: str
    tripped: bool
    severity: str
    triggers: list = field(default_factory=list)
    sticky_reason_active: bool = False
    trade_lock_reason: str | None = None
    would_be_locked: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _is_sticky_reason(reason: str | None) -> bool:
    """Byte-identical predicate to main.py:6178-6180's
    trade_lock_reason_is_sticky check - kept as its own function so it
    can never silently drift from the live condition it mirrors."""
    return reason == "total_drawdown_limit_breached" or str(reason or "").startswith("kill_switch_")


def replay_kill_switch_over_dataset(
    dates: list,
    daily_portfolio_returns: dict,
    kill_switch_config: dict,
    *,
    max_daily_drawdown_pct: float,
    max_total_drawdown_pct: float,
    starting_portfolio_value: float = 1.0,
) -> list:
    """Day-by-day, in `dates` order (must already be sorted - callers own
    that, same convention as rank_book_simulator.py's unique_dates loop).

    daily_portfolio_returns: {date: net_return} - reuse simulate_rank_book()'s
    own per_date_net_return/per_date pair directly (dict(zip(per_date,
    per_date_net_return))) rather than inventing a second return series.
    A date missing from this dict defaults to 0.0 return (a flat/no-trade
    day), never KeyError.

    Mirrors main.py:6140-6345's exact per-date sequence: (1) sticky-lock
    clear/keep using the reason carried over from the PRIOR date, (2)
    portfolio_value/peak_equity/drawdown update from this date's return,
    (3) return-history + drawdown-velocity update, (4)
    assess_drawdown_lock() check, (5) evaluate_kill_switch() check - in
    that exact order, since main.py's own ordering determines which
    reason wins when more than one would fire the same date. Returns one
    dict (KillSwitchReplayRecord.to_dict()) per date."""
    return_history: deque = deque(maxlen=_RETURN_HISTORY_MAXLEN)
    previous_portfolio_value = None
    previous_total_drawdown = None
    portfolio_value = float(starting_portfolio_value)
    peak_equity = portfolio_value
    trade_lock_active = False
    trade_lock_reason = None

    records = []

    for date in dates:
        # (1) sticky-lock clear/keep, using the reason carried over from
        # the PRIOR date - byte-identical predicate to main.py's own.
        if trade_lock_active and not _is_sticky_reason(trade_lock_reason):
            trade_lock_active = False
            trade_lock_reason = None

        # (2) portfolio value / peak / drawdown, from the offline return
        # series. No separate session/day-open concept exists offline -
        # daily_drawdown collapses to this date's own one-bar return
        # (main.py's own daily_drawdown is itself session-open-to-now,
        # effectively the same figure at Daily resolution where a new
        # session starts every bar in backtest mode).
        net_return = float(daily_portfolio_returns.get(date, 0.0))
        portfolio_value *= 1.0 + net_return
        peak_equity = max(peak_equity, portfolio_value)
        total_drawdown = portfolio_value / max(peak_equity, 1e-9) - 1.0
        daily_drawdown = net_return

        # (3) return history + drawdown velocity, same deque convention
        # as main.py's self._kill_switch_return_history.
        if previous_portfolio_value is not None and previous_portfolio_value > 0:
            return_history.append(portfolio_value / previous_portfolio_value - 1.0)
        drawdown_velocity = (
            abs(total_drawdown) - abs(previous_total_drawdown) if previous_total_drawdown is not None else None
        )
        previous_portfolio_value = portfolio_value
        previous_total_drawdown = total_drawdown

        # (4) drawdown-lock breach (risk_controls.py, byte-identical call
        # to main.py's own).
        breach_active, breach_reason = assess_drawdown_lock(
            daily_drawdown, total_drawdown, max_daily_drawdown_pct, max_total_drawdown_pct
        )
        if breach_active:
            trade_lock_active = True
            trade_lock_reason = breach_reason

        # (5) the kill switch itself - only the two dataset-derivable
        # runtime_metrics inputs are populated; every other input stays
        # None (evaluate_kill_switch()'s own documented None-skip
        # contract handles this cleanly, never fabricates a value).
        runtime_metrics = {
            "recent_bar_returns": list(return_history),
            "drawdown_velocity_pct_per_bar": drawdown_velocity,
            "live_rank_ic": None,
            "consecutive_losses": None,
            "slippage_divergence_bps": None,
            "model_age_days": None,
            "reconciliation_breach": False,
        }
        decision = evaluate_kill_switch(runtime_metrics, kill_switch_config)
        if decision.tripped:
            trade_lock_active = True
            trade_lock_reason = decision.reason

        records.append(
            KillSwitchReplayRecord(
                date=str(date),
                tripped=decision.tripped,
                severity=decision.severity,
                triggers=list(decision.triggers),
                sticky_reason_active=_is_sticky_reason(trade_lock_reason),
                trade_lock_reason=trade_lock_reason,
                would_be_locked=trade_lock_active,
            ).to_dict()
        )

    return records


def summarize_kill_switch_replay(records: list) -> dict:
    """Aggregate trip-count / total-locked-days / locked-day fraction,
    mirroring evaluation/rank_signal_calibration.py::
    summarize_book_history_reconciliation()'s aggregation shape."""
    total_dates = len(records)
    trip_count = sum(1 for record in records if record["tripped"])
    locked_days = sum(1 for record in records if record["would_be_locked"])
    return {
        "total_dates": total_dates,
        "trip_count": trip_count,
        "locked_days": locked_days,
        "locked_day_fraction": (locked_days / total_dates) if total_dates else 0.0,
    }
