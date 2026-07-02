"""Pure aggregation functions over experience-event dicts (Phase V2-15).

Every function here operates on a plain list[dict], where each dict has the
same shape as experience.redis_queue.build_experience_event()'s return value
(or the JSONB-decoded `payload` column read back from Postgres via
`cursor.fetchall()`). There is exactly one implementation shape - callers
choose where the list comes from (Redis/in-memory log or a Postgres query),
not which function to call.
"""

from __future__ import annotations

import numpy as np

SIGNALS = ("buy", "sell", "hold")
ACTIONS = ("observe", "simulate", "trade", "reduce_risk", "retrain_candidate")


def count_observations(events: list[dict]) -> int:
    return len(events)


def signal_distribution(events: list[dict]) -> dict[str, int]:
    counts = {signal: 0 for signal in SIGNALS}
    for event in events:
        signal = event.get("signal")
        if signal in counts:
            counts[signal] += 1
    return counts


def action_distribution(events: list[dict]) -> dict[str, int]:
    counts = {action: 0 for action in ACTIONS}
    for event in events:
        action = event.get("action")
        if action in counts:
            counts[action] += 1
    return counts


def rejected_by_reason(events: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        if event.get("action") == "trade":
            continue
        reasons = (event.get("market_analysis") or {}).get("reasons") or []
        for reason in reasons:
            counts[reason] = counts.get(reason, 0) + 1
    return counts


def _realized_pnls(events: list[dict]) -> list[float]:
    pnls = []
    for event in events:
        pnl = (event.get("portfolio") or {}).get("last_realized_pnl")
        if pnl is not None:
            pnls.append(float(pnl))
    return pnls


def simulated_win_loss(events: list[dict]) -> dict:
    pnls = _realized_pnls(events)
    wins = sum(1 for pnl in pnls if pnl > 0)
    losses = sum(1 for pnl in pnls if pnl < 0)
    total = wins + losses
    return {
        "wins": wins,
        "losses": losses,
        "win_rate": (wins / total) if total > 0 else 0.0,
    }


def _simulated_equity_series(events: list[dict]) -> list[float]:
    return [
        float(event["portfolio"]["total_value"])
        for event in events
        if (event.get("portfolio") or {}).get("simulated") and event["portfolio"].get("total_value") is not None
    ]


def simulated_sharpe(events: list[dict], periods_per_year: int = 252) -> float:
    equity_series = _simulated_equity_series(events)
    if len(equity_series) < 2:
        return 0.0

    equity_array = np.asarray(equity_series, dtype=float)
    previous = equity_array[:-1]
    current = equity_array[1:]
    with np.errstate(divide="ignore", invalid="ignore"):
        returns = np.where(previous != 0, (current - previous) / previous, 0.0)

    std = float(np.std(returns))
    if std == 0.0:
        return 0.0

    mean = float(np.mean(returns))
    return (mean / std) * (periods_per_year**0.5)


def simulated_max_drawdown(events: list[dict]) -> float:
    equity_series = _simulated_equity_series(events)
    if not equity_series:
        return 0.0

    peak = equity_series[0]
    max_drawdown = 0.0
    for equity in equity_series:
        peak = max(peak, equity)
        if peak > 0:
            drawdown = equity / peak - 1.0
            max_drawdown = min(max_drawdown, drawdown)
    return max_drawdown


def compute_observation_summary(events: list[dict]) -> dict:
    return {
        "count_observations": count_observations(events),
        "signal_distribution": signal_distribution(events),
        "action_distribution": action_distribution(events),
        "rejected_by_reason": rejected_by_reason(events),
        "simulated_win_loss": simulated_win_loss(events),
        "simulated_sharpe": simulated_sharpe(events),
        "simulated_max_drawdown": simulated_max_drawdown(events),
    }
