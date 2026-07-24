"""Redis Stream publisher for Aether Quant experience events (V2-13).

Publishes one market-decision event per asset per bar to a Redis Stream
(XADD) with a bounded maxlen. All Redis failures are caught and logged;
trading is never blocked.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from .observation_metrics import compute_observation_summary

logger = logging.getLogger(__name__)


def build_experience_event(
    *,
    mode: str,
    symbol: str,
    ticker: str,
    signal: str,
    action: str,
    execution_note: str,
    probability_up: float | None,
    confidence: float,
    target_weight: float,
    regime: dict,
    moe_gating: dict,
    topology: dict,
    liquidity: dict,
    market_analysis: dict,
    portfolio: dict,
    sequence_model: dict | None = None,
    resolved_predicted_rank_20d: float | None = None,
    close_price: float | None = None,
    corporate_action: dict | None = None,
) -> dict[str, Any]:
    """Construct a standardised experience event dict.

    Pure function — no side effects, no I/O. Directly testable without
    any Redis dependency.

    `sequence_model` is the optional Phase 2 causal-TCN sequence-encoder
    prediction (`main.py::_run_sequence_model()`, `{"direction",
    "magnitude", "volatility"}` or None when the model isn't loaded/failed
    for this bar) — informational only, same as everywhere else it's
    threaded, but now persisted for offline analysis instead of only
    reaching the live dashboard.

    `resolved_predicted_rank_20d`/`close_price` (Phase 6 of the 5/10 -> 9/10
    roadmap): the SAME resolved rank_20d value main.py already computes
    (preferring the sequence model's head, falling back to multitask's —
    see risk/position_sizing.py::rank_sizing_multiplier()'s docstring),
    plus this bar's close, persisted specifically so
    performance/rank_ic_monitor.py's outcome-resolution job can self-join
    experience events on (ticker, date + 20 trading days) with no separate
    live price feed dependency. Without this, a multitask-fallback rank
    prediction (sequence model disabled) never reached the experience
    store at all — `sequence_model` above only carries the sequence
    model's own prediction, not the resolved value main.py actually used.

    `corporate_action` (V4.7, development/Problems.md - corporate-action
    modeling): {"split_factor": float, "reference_price": float} when
    Lean's own slice.Splits reports a same-bar split event for this
    symbol, else None (absent, not a placeholder default - a bar with no
    split must never be indistinguishable from one Lean reported an
    unparseable/zero split_factor for). Purely observational auditability
    - main.py never recomputes an OCC-style strike/multiplier adjustment
    from this; Lean/the option-chain data itself owns that fact.
    """
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "market_decision",
        "created_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": mode,
        "symbol": symbol,
        "ticker": ticker,
        "signal": signal,
        "action": action,
        "execution_note": execution_note,
        "probability_up": probability_up,
        "confidence": confidence,
        "target_weight": target_weight,
        "regime": regime,
        "moe_gating": moe_gating,
        "topology": topology,
        "liquidity": liquidity,
        "market_analysis": market_analysis,
        "portfolio": portfolio,
        "sequence_model": sequence_model,
        "resolved_predicted_rank_20d": resolved_predicted_rank_20d,
        "close_price": close_price,
        "corporate_action": corporate_action,
    }


def build_session_summary_event(
    *,
    mode: str,
    session_date: Any,
    session_start_equity: float,
    session_end_equity: float,
    events: list[dict],
) -> dict[str, Any]:
    """Construct a session_summary experience event (Phase V2-19).

    Pure function — no side effects, no I/O. Pushed by main.py at each
    session rollover (see main.py::_refresh_risk_state()), reusing
    experience.observation_metrics.compute_observation_summary() for every
    per-session statistic; computes nothing itself besides session_return.
    `session_date` accepts anything with an isoformat() (datetime.date) or
    falls back to str().
    """
    session_return = (
        (session_end_equity - session_start_equity) / session_start_equity if session_start_equity else 0.0
    )
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "session_summary",
        "created_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": mode,
        "session_date": session_date.isoformat() if hasattr(session_date, "isoformat") else str(session_date),
        "session_start_equity": session_start_equity,
        "session_end_equity": session_end_equity,
        "session_return": session_return,
        "observation_summary": compute_observation_summary(events),
    }


def build_option_strategy_outcome_event(
    *,
    mode: str,
    symbol: str,
    ticker: str,
    strategy_name: str,
    realized_pnl: float,
    entry_bar: int,
    exit_bar: int,
    contracts: int,
    entry_net_debit_or_credit: float,
    exit_net_debit_or_credit: float,
    regime: dict,
    moe_gating: dict,
    topology: dict,
    liquidity: dict,
) -> dict[str, Any]:
    """Construct an option_strategy_outcome experience event (V4.7,
    development/Problems.md #29's own framing) - the prerequisite data
    source a learned multi-leg strategy-selector model needs that does not
    exist anywhere else in this codebase: build_experience_event()'s own
    `portfolio.last_realized_pnl` field is symbol_key-keyed only (via
    experience/simulated_portfolio.py's SimulatedPortfolio), with no
    concept of "strategy" at all, so it can never be disaggregated by
    strategy_name after the fact.

    Deliberately its OWN event shape (not shoehorned into
    build_experience_event()'s portfolio={...} sub-dict, which is keyed
    one-per-asset-per-bar) - a strategy close is a distinct, sparser
    occurrence than every-bar market_decision events. Pure function - no
    side effects, no I/O; pushed via the SAME ExperienceQueue.push() as
    every other event type here, no new Redis stream/channel.

    regime/moe_gating/topology/liquidity are the SAME per-bar payload
    dicts main.py already threads into build_experience_event() at the
    bar this position was OPENED - train_strategy_selector.py reads these
    back as its feature vector, matching train_topology.py's own
    "regime.risk_score, topology.correlation_strength, liquidity score"
    extraction pattern (see that trainer's own docstring) rather than
    inventing a new feature vocabulary. No Postgres DDL change is needed
    for this new event_type - experience/postgres_worker.py::event_to_row()
    already stores the full payload generically and falls back
    action=event_type when no "action" key is present, so
    `WHERE action = 'option_strategy_outcome'` is already index-backed.
    """
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "option_strategy_outcome",
        "created_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": mode,
        "symbol": symbol,
        "ticker": ticker,
        "strategy_name": strategy_name,
        "realized_pnl": realized_pnl,
        "entry_bar": entry_bar,
        "exit_bar": exit_bar,
        "contracts": contracts,
        "entry_net_debit_or_credit": entry_net_debit_or_credit,
        "exit_net_debit_or_credit": exit_net_debit_or_credit,
        "regime": regime,
        "moe_gating": moe_gating,
        "topology": topology,
        "liquidity": liquidity,
    }


class ExperienceQueue:
    """Fire-and-forget Redis Stream publisher.

    All failures (connection errors, XADD errors, missing package) are
    caught and logged at WARNING level. push() never raises; the trading
    loop is never blocked.

    Parameters
    ----------
    enabled     : kill switch — if False, push() is always a no-op
    redis_url   : connection URL; overridden by AETHER_REDIS_URL env var
    stream_name : Redis key for XADD (default: "aether:experience")
    maxlen      : approximate cap on stream length (MAXLEN ~)
    _client     : pre-built Redis client for test injection
    """

    def __init__(
        self,
        enabled: bool = True,
        redis_url: str = "redis://localhost:6380/0",
        stream_name: str = "aether:experience",
        maxlen: int = 100_000,
        _client=None,
    ) -> None:
        self.enabled = enabled
        self.stream_name = stream_name
        self.maxlen = maxlen
        self._client = None

        if not enabled:
            return

        if _client is not None:
            self._client = _client
            return

        url = os.environ.get("AETHER_REDIS_URL", redis_url) or "redis://localhost:6380/0"
        try:
            import redis as redis_lib  # deferred — not always installed in Lean environments

            client = redis_lib.from_url(url, socket_connect_timeout=2, socket_timeout=2)
            client.ping()
            self._client = client
            logger.info(
                "ExperienceQueue connected to %s (stream=%s, maxlen=%d)",
                url,
                stream_name,
                maxlen,
            )
        except Exception as exc:
            logger.warning(
                "ExperienceQueue: Redis unavailable at %s — experience events will be skipped. (%s)",
                url,
                exc,
            )

    def push(self, event: dict) -> bool:
        """Publish one event dict to the Redis Stream.

        Returns True on success, False on any failure.  Never raises.
        """
        if not self.enabled or self._client is None:
            return False
        try:
            self._client.xadd(
                self.stream_name,
                {"payload": json.dumps(event)},
                maxlen=self.maxlen,
                approximate=True,
            )
            return True
        except Exception as exc:
            logger.warning("ExperienceQueue.push failed: %s", exc)
            return False
