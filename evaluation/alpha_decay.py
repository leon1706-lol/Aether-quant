"""Is a generation's alpha decaying? A one-sided CUSUM of its net daily returns against what it was expected to earn (V6.6.1).

Decay is slow to see: at one false alarm in five years, a fall from Sharpe 1 to 0 takes on the order of 400 sessions to show. `average_run_lengths` reports what a threshold
buys, and the allocator (`portfolio/generation_blend.py`) therefore never lets this alone drive capital except at `dead`. Compare against the selection Sharpe halved, not the backtest's figure.

States: healthy -> watch -> decaying -> dead, with hysteresis: a state falls back only after `recover_sessions` below the lower threshold. Too few or non-finite returns keep the previous state.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from typing import Any

STATES = ("healthy", "watch", "decaying", "dead")
TRADING_DAYS = 252.0


@dataclass(frozen=True)
class DecayConfig:
    """Settings of the CUSUM decay monitor: the alarm threshold, the watch fraction and the minimum sessions before a verdict."""
    threshold: float = 26.0  # about one false alarm in five years at this slack; `average_run_lengths` reports the simulated figure
    watch_fraction: float = 0.5
    min_sessions: int = 60
    recover_sessions: int = 40
    dead_multiple: float = 2.0
    slack: float = 0.5  # half the annual Sharpe shift worth detecting, the CUSUM's reference value


@dataclass(frozen=True)
class DecayReport:
    """The decay monitor's state for one generation (healthy, watch, decaying), with its statistic and the sessions it saw."""
    state: str
    statistic: float
    sessions: int
    ew_sharpe: float | None
    reason: str


def _standardised(returns: np.ndarray, expected_sharpe: float, slack: float) -> np.ndarray:
    """Each session's distance below expectation, in daily standard deviations, less the slack that keeps ordinary noise from adding up."""
    deviation = returns.std(ddof=1)
    if not np.isfinite(deviation) or deviation <= 0.0:
        return np.zeros_like(returns)
    daily_expected = float(expected_sharpe) / math.sqrt(TRADING_DAYS)
    return daily_expected - returns / deviation - float(slack) / math.sqrt(TRADING_DAYS)


def cusum_path(returns: np.ndarray, *, expected_sharpe: float, slack: float = 0.5) -> np.ndarray:
    """The running statistic: it rises while returns fall short and rests at zero, so old good years can't hide today's loss."""
    steps = _standardised(np.asarray(returns, dtype=float), expected_sharpe, slack)
    path = np.zeros(len(steps))
    level = 0.0
    for position, step in enumerate(steps):
        level = max(0.0, level + float(step))
        path[position] = level
    return path


def cusum_lower(returns: np.ndarray, *, expected_sharpe: float, threshold: float, slack: float = 0.5) -> float:
    """Today's statistic as a share of the threshold: 1.0 is an alarm."""
    path = cusum_path(returns, expected_sharpe=expected_sharpe, slack=slack)
    return float(path[-1] / threshold) if len(path) and threshold > 0.0 else 0.0


def _ew_sharpe(returns: np.ndarray, half_life: float = 126.0) -> float | None:
    if len(returns) < 20:
        return None
    weights = 0.5 ** (np.arange(len(returns))[::-1] / half_life)
    mean = float(np.average(returns, weights=weights))
    variance = float(np.average((returns - mean) ** 2, weights=weights))
    return mean / math.sqrt(variance) * math.sqrt(TRADING_DAYS) if variance > 0.0 else None


def decay_state(returns: Sequence[float], *, expected_sharpe: float, previous: str = "healthy", config: DecayConfig | None = None) -> DecayReport:
    """A generation's state today. `previous` carries the hysteresis, so a state can't flicker on one good week."""
    config = config or DecayConfig()
    previous = previous if previous in STATES else "healthy"
    values = np.asarray(list(returns), dtype=float)
    if len(values) < config.min_sessions:
        return DecayReport(previous, 0.0, len(values), None, f"only {len(values)} sessions; minimum {config.min_sessions}")
    if not np.isfinite(values).all() or not math.isfinite(float(expected_sharpe)):
        return DecayReport(previous, 0.0, len(values), None, "non-finite evidence: holding the state")
    path = cusum_path(values, expected_sharpe=expected_sharpe, slack=config.slack)
    statistic = float(path[-1])
    if statistic >= config.threshold * config.dead_multiple:
        raw = "dead"
    elif statistic >= config.threshold:
        raw = "decaying"
    elif statistic >= config.threshold * config.watch_fraction:
        raw = "watch"
    else:
        raw = "healthy"
    state = raw
    if STATES.index(raw) < STATES.index(previous):
        # Going down a level needs a run of sessions below that level's floor. A dead generation stays dead: its capital is gone, and only a fresh candidate returns.
        floor = {"healthy": 0.0, "watch": config.watch_fraction, "decaying": 1.0, "dead": config.dead_multiple}[previous] * config.threshold
        recovered = len(path) >= config.recover_sessions and bool((path[-config.recover_sessions:] < floor).all())
        state = previous if previous == "dead" or not recovered else raw
    return DecayReport(state, statistic, len(values), _ew_sharpe(values), f"CUSUM {statistic:.2f} against {config.threshold:.2f}")


def average_run_lengths(*, expected_sharpe: float, config: DecayConfig | None = None, paths: int = 2000, seed: int = 1, horizon: int = 2520, decayed_sharpe: float | None = None) -> dict[str, Any]:
    """Simulated sessions to the first `decaying` alarm: with the alpha intact (a false alarm) and after it falls to `decayed_sharpe`, default zero. Paths that never alarm count at `horizon`."""
    config = config or DecayConfig()
    decayed = 0.0 if decayed_sharpe is None else float(decayed_sharpe)
    rng = np.random.default_rng(seed)

    def first_alarm(sharpe: float) -> np.ndarray:
        daily = sharpe / math.sqrt(TRADING_DAYS)
        step_noise = rng.normal(size=(paths, horizon))
        steps = float(expected_sharpe) / math.sqrt(TRADING_DAYS) - (daily + step_noise) - config.slack / math.sqrt(TRADING_DAYS)
        out = np.full(paths, horizon, dtype=float)
        level = np.zeros(paths)
        alive = np.ones(paths, dtype=bool)
        for session in range(horizon):
            level = np.maximum(0.0, level + steps[:, session])
            hit = alive & (level >= config.threshold) & (session + 1 >= config.min_sessions)
            out[hit] = session + 1
            alive &= ~hit
            if not alive.any():
                break
        return out

    intact, fallen = first_alarm(float(expected_sharpe)), first_alarm(decayed)
    return {
        "expected_sharpe": float(expected_sharpe), "decayed_sharpe": decayed, "threshold": config.threshold, "slack": config.slack, "paths": paths, "horizon": horizon,
        "median_false_alarm_sessions": float(np.median(intact)), "false_alarm_within_1y": float(np.mean(intact <= 252)), "false_alarm_within_5y": float(np.mean(intact <= 1260)),
        "median_detection_sessions": float(np.median(fallen)), "detected_within_1y": float(np.mean(fallen <= 252)), "detected_within_2y": float(np.mean(fallen <= 504)),
    }
