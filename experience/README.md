# experience

Observation and decision history: Redis is the low-latency buffer, PostgreSQL the permanent store.

1. Signals and trades push events to a Redis stream at once.
2. A worker reads asynchronously and writes batches to PostgreSQL.
3. Controlled retraining reads PostgreSQL as the source of truth. Model versions and retraining events live in `retraining/`.

**Members**

- **`redis_queue.py`:** `ExperienceQueue`. `phase_v2.experience_queue.async_enabled` (default off) moves the Redis write off the hot path. Backtests never push. Also builds session-summary events for `notifications/`.
- **`postgres_worker.py`:** batch inserts. Producers serialize finite-safe JSON; a poison row dead-letters, while an outage re-raises and stays pending (#120).
- **`simulated_portfolio.py`:** an in-memory portfolio used whenever `execution.order_gate.resolve_order_permission` blocks a real order. It never touches the broker.
- **`observation_metrics.py`:** pure aggregates over a list of events (signal distribution, rejections, simulated win rate, Sharpe, drawdown), usable on memory or a Postgres query.
