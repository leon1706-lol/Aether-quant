"""V5.1 Phase 6 (production safety): the automatic, per-bar circuit
breaker. Deliberately trips the EXISTING trade-lock machinery (main.py's
self.trade_lock_active/self.trade_lock_reason, already consumed by
execution/order_gate.py::resolve_order_permission()'s risk_locks_healthy
input, analyzer/market_analyzer.py's Priority 1 reduce_risk check, state.json,
and the audit log) rather than adding a second, parallel lock - a second
lock would create two sources of truth that can disagree, and `aq
trade-lock --off`/`--auto` would no longer be a complete story.

Pure, deterministic, cheap: evaluate_kill_switch() does only dict/threshold
comparisons over ALREADY-COMPUTED inputs (a rolling per-bar return history,
a drawdown-velocity figure, etc. - all assembled by main.py once per bar
from state it already tracks) - no I/O, no per-bar work heavier than a
handful of float comparisons, respecting main.py's per-bar latency budget
the same way every other pure risk/analyzer module in this codebase does.

GUARDRAIL - fail-open at two levels, matching execution/cost_model.py::
build_net_edge_decision()'s own contract:
  1. config["enabled"] is False (the function-level default) -> never trips,
     full no-op, regardless of any other input.
  2. Even when enabled, each INDIVIDUAL condition's own threshold defaults
     to a value that condition can never cross - so enabling the kill
     switch with only some thresholds configured only activates those
     specific checks, never accidentally activates an unconfigured one.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

# Deliberately extreme "this condition can never fire" sentinels - not 0.0
# or None, which would either behave surprisingly (0.0 is a real threshold
# some configs might genuinely want) or require every comparison below to
# be null-guarded twice. A value this far outside any plausible input
# reliably degrades a single unconfigured condition to a no-op without
# touching the others.
_NEVER_BELOW = -1e12
_NEVER_ABOVE = 1e12


@dataclass(frozen=True)
class KillSwitchDecision:
    tripped: bool
    severity: str
    triggers: list[str] = field(default_factory=list)
    reason: str = ""
    recommended_action: str = "none"
    observed: dict = field(default_factory=dict)
    thresholds: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _rolling_sharpe(
    returns: list[float], trading_days_per_year: int = 252, min_return_std_floor: float = 0.0
) -> float | None:
    """None (never 0.0) when there are fewer than 2 observations - the
    caller must be able to tell "not enough data yet" apart from
    "genuinely zero Sharpe" (a std of exactly 0.0 with >=2 observations IS
    reported as 0.0, same convention evaluation/rank_book_simulator.py::
    _annualized_sharpe() already uses).

    GUARDRAIL (Problems.md - a sticky kill-switch trip from a numerically
    meaningless reading): std <= max(0.0, min_return_std_floor) also
    returns a clean 0.0 - widening the exact-zero guard above into a
    near-zero guard. mean/std*sqrt(trading_days_per_year) is numerically
    explosive whenever std is small but nonzero: a return window that's
    mostly flat/cash (e.g. a mostly-uninvested portfolio) with just a
    couple of small real values mixed in can swing to wildly extreme
    Sharpe readings - both directions - purely from which few nonzero
    values happen to still be inside the window, not from genuine risk-
    adjusted performance. Reproduced directly against a real backtest's
    equity curve: a near-flat window produced Sharpe swings of +2.25 and
    -2.28 bar-to-bar from noise alone. min_return_std_floor=0.0 (default)
    reproduces today's exact behavior for any caller that doesn't pass it."""
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    std = math.sqrt(variance)
    if std <= max(0.0, min_return_std_floor):
        return 0.0
    return (mean / std) * math.sqrt(trading_days_per_year)


def evaluate_kill_switch(runtime_metrics: dict, config: dict) -> KillSwitchDecision:
    """Evaluated once per bar by main.py, fed a `runtime_metrics` dict it
    assembles from state it already tracks:
      - "recent_bar_returns": list[float] - a rolling per-bar portfolio
        return history (main.py's own bounded deque), used to compute a
        rolling Sharpe over the trailing `evaluation_bars` window.
      - "drawdown_velocity_pct_per_bar": float | None - this bar's total
        drawdown minus the previous bar's (a one-bar rate of change, not
        an average - a single sharp bar is exactly what this exists to
        catch quickly).
      - "live_rank_ic": float | None - the most recent rank-IC-decay
        trigger's metric_value, if the LATEST entry in
        visualization/grafana/retraining_status.json's last_trigger
        happens to be a rank_ic_decay_trigger (main.py never opens its own
        Postgres connection - this is the same "read a locally-cached file
        a separate Postgres-connected worker refreshes" pattern
        read_manual_trade_lock_override()/load_cached_fred_series() already
        use). None whenever the latest trigger isn't rank-IC-shaped, not
        just when the file is missing - a stale/wrong-shaped signal must
        never be treated as a real reading.
      - "consecutive_losses": int | None - main.py's own realized-trade
        streak counter.
      - "slippage_divergence_bps": float | None - realized-vs-expected
        round-trip cost divergence from the most recent fill(s)
        (execution/cost_model.py's expected estimate vs. the actual fill
        price main.py's OnOrderEvent observes). None until at least one
        fill has been observed this session.
      - "model_age_days": float | None - age of the active model artifact
        on disk.
      - "reconciliation_breach": bool - True when execution/reconciliation.py::
        reconcile_positions()'s max_abs_weight_drift exceeded
        phase_v2.reconciliation.max_tolerated_drift this bar (Step 6.2)
        and phase_v2.reconciliation.trips_kill_switch is true - reconciliation
        failures trip the switch rather than being logged and ignored.

    Any key's value being None simply skips that one condition (never
    raises, never counts as a trip) - a bar where a given signal isn't
    available yet degrades that ONE condition, not the whole switch."""
    if not bool(config.get("enabled", False)):
        return KillSwitchDecision(tripped=False, severity="none", reason="kill_switch_disabled")

    evaluation_bars = int(config.get("evaluation_bars", 60))
    # GUARDRAIL (Problems.md - kill switch tripped on bar 2-3 of every
    # run): evaluation_bars was previously used ONLY as a slice bound
    # ([-evaluation_bars:]), never as a minimum-sample requirement, so
    # _rolling_sharpe() happily annualized a 2-observation mean/std by
    # sqrt(252) into an absurd magnitude and tripped the switch almost
    # immediately. min_bars_for_sharpe defaults to evaluation_bars itself
    # (the value's own documented intent - "the trailing window size") and
    # gates whether the rolling-Sharpe trigger is evaluated AT ALL this
    # bar, not just how much history it's computed over.
    min_bars_for_sharpe = int(config.get("min_bars_for_sharpe", evaluation_bars))
    # GUARDRAIL (Problems.md - a real backtest's kill switch stuck sticky
    # on a spurious trip) - independent of min_bars_for_sharpe above:
    # count and variance are orthogonal failure modes. A window with
    # plenty of samples that are almost all exactly zero (e.g. a mostly-
    # cash portfolio) clears the count floor fine but is still numerically
    # degenerate for mean/std - see _rolling_sharpe()'s own docstring.
    # Default 0.0005 (std*sqrt(252) ~= 1% annualized) - below this, daily
    # returns are behaviorally indistinguishable from sitting in cash, far
    # more likely a near-zero-return artifact than a real low-vol edge.
    min_return_std_for_sharpe = float(config.get("min_return_std_for_sharpe", 0.0005))
    min_rolling_sharpe = float(config.get("min_rolling_sharpe", _NEVER_BELOW))
    max_drawdown_velocity_pct_per_bar = float(config.get("max_drawdown_velocity_pct_per_bar", _NEVER_ABOVE))
    min_live_rank_ic = float(config.get("min_live_rank_ic", _NEVER_BELOW))
    max_consecutive_losses = float(config.get("max_consecutive_losses", _NEVER_ABOVE))
    max_slippage_divergence_bps = float(config.get("max_slippage_divergence_bps", _NEVER_ABOVE))
    max_model_age_days = float(config.get("max_model_age_days", _NEVER_ABOVE))

    triggers: list[str] = []
    observed: dict = {}

    # evaluation_bars <= 0 previously meant "use the entire history" via
    # Python's own `[-0:]` == `[0:]` slice semantics - not a real window,
    # and not what a misconfigured 0/negative value should do. Treat it as
    # no window at all (insufficient data, trigger never evaluated) rather
    # than silently falling back to unbounded history.
    all_returns = list(runtime_metrics.get("recent_bar_returns") or [])
    recent_returns = all_returns[-evaluation_bars:] if evaluation_bars > 0 else []
    observed["rolling_sharpe_num_bars"] = len(recent_returns)
    rolling_sharpe = (
        _rolling_sharpe(recent_returns, min_return_std_floor=min_return_std_for_sharpe)
        if len(recent_returns) >= min_bars_for_sharpe
        else None
    )
    observed["rolling_sharpe"] = rolling_sharpe
    if rolling_sharpe is not None and rolling_sharpe < min_rolling_sharpe:
        triggers.append("rolling_sharpe_below_floor")

    drawdown_velocity = runtime_metrics.get("drawdown_velocity_pct_per_bar")
    observed["drawdown_velocity_pct_per_bar"] = drawdown_velocity
    if drawdown_velocity is not None and float(drawdown_velocity) > max_drawdown_velocity_pct_per_bar:
        triggers.append("drawdown_velocity_above_cap")

    live_rank_ic = runtime_metrics.get("live_rank_ic")
    observed["live_rank_ic"] = live_rank_ic
    if live_rank_ic is not None and float(live_rank_ic) < min_live_rank_ic:
        triggers.append("live_rank_ic_below_floor")

    consecutive_losses = runtime_metrics.get("consecutive_losses")
    observed["consecutive_losses"] = consecutive_losses
    if consecutive_losses is not None and float(consecutive_losses) > max_consecutive_losses:
        triggers.append("consecutive_losses_above_cap")

    slippage_divergence_bps = runtime_metrics.get("slippage_divergence_bps")
    observed["slippage_divergence_bps"] = slippage_divergence_bps
    if slippage_divergence_bps is not None and float(slippage_divergence_bps) > max_slippage_divergence_bps:
        triggers.append("slippage_divergence_above_cap")

    model_age_days = runtime_metrics.get("model_age_days")
    observed["model_age_days"] = model_age_days
    if model_age_days is not None and float(model_age_days) > max_model_age_days:
        triggers.append("model_age_above_cap")

    if bool(runtime_metrics.get("reconciliation_breach", False)):
        triggers.append("reconciliation_breach")
        observed["reconciliation_breach"] = True

    thresholds = {
        "evaluation_bars": evaluation_bars,
        "min_bars_for_sharpe": min_bars_for_sharpe,
        "min_return_std_for_sharpe": min_return_std_for_sharpe,
        "min_rolling_sharpe": min_rolling_sharpe,
        "max_drawdown_velocity_pct_per_bar": max_drawdown_velocity_pct_per_bar,
        "min_live_rank_ic": min_live_rank_ic,
        "max_consecutive_losses": max_consecutive_losses,
        "max_slippage_divergence_bps": max_slippage_divergence_bps,
        "max_model_age_days": max_model_age_days,
    }

    if not triggers:
        return KillSwitchDecision(
            tripped=False,
            severity="none",
            triggers=[],
            reason="all_checks_within_thresholds",
            recommended_action="none",
            observed=observed,
            thresholds=thresholds,
        )

    severity = "critical" if len(triggers) > 1 else "warning"
    return KillSwitchDecision(
        tripped=True,
        severity=severity,
        triggers=triggers,
        reason=f"kill_switch_{'_and_'.join(triggers)}",
        recommended_action=str(config.get("action", "trade_lock")),
        observed=observed,
        thresholds=thresholds,
    )
