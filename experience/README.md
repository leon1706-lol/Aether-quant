# experience

Owns observation and decision history:

- observations
- signals
- expert outputs
- simulated trades
- later live trades

(Model versions and retraining events live in `retraining/` since V2-17 —
that package owns the `model_versions`/`retraining_events` Postgres tables
and reads this package's `experience_events` table as an input, but does not
write into it.)

V2 no longer uses a JSONL fallback. Redis is the temporary low-latency buffer, and PostgreSQL is the permanent experience store.

Runtime flow:

1. Signal generation, simulated trades or live trades push raw events into Redis immediately.
2. Redis stores the events as a stream or queue, for example via `XADD` or `LPUSH`.
3. A separate worker reads Redis asynchronously, for example via `XREAD` or `BLPOP`.
4. The worker writes batched events into PostgreSQL.
5. Controlled retraining reads from PostgreSQL as the single source of truth.

V2-19 adds `build_session_summary_event()` to `redis_queue.py`: main.py pushes
one of these per session rollover (see `main.py::_refresh_risk_state()`),
reusing `observation_metrics.compute_observation_summary()` for every stat —
it computes nothing itself besides `session_return`. Its `event_type` is
`"session_summary"` rather than `"market_decision"`, so it carries no
per-asset `ticker`/`symbol`/`signal`; `postgres_worker.py::event_to_row()`
uses `.get(..., "")` defaults for those columns rather than direct indexing
to accommodate this. `notifications/telegram_worker.py` is the consumer —
see that package's README for the alerting side.

V2-15 (Observation Mode) adds two members:

- `simulated_portfolio.py` (`SimulatedPortfolioState`) — an in-memory fake
  portfolio (cash/holdings/equity/drawdown/exposure/turnover) that never
  touches `self.Portfolio` or any broker call. Used whenever
  `execution.order_gate.resolve_order_permission` blocks a real order; its
  `snapshot()` is a drop-in superset of the `portfolio={...}` dict already
  passed to `build_experience_event`.
- `observation_metrics.py` — pure aggregation functions (counts, signal/action
  distribution, rejected-by-reason, simulated win/loss, Sharpe, max drawdown)
  over a plain `list[dict]` of experience events, usable identically against
  an in-memory event log or a Postgres `payload` column query.
