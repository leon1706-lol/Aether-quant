# experience

Owns observation and decision history:

- observations
- signals
- expert outputs
- simulated trades
- later live trades
- model versions
- retraining events

V2 no longer uses a JSONL fallback. Redis is the temporary low-latency buffer, and PostgreSQL is the permanent experience store.

Runtime flow:

1. Signal generation, simulated trades or live trades push raw events into Redis immediately.
2. Redis stores the events as a stream or queue, for example via `XADD` or `LPUSH`.
3. A separate worker reads Redis asynchronously, for example via `XREAD` or `BLPOP`.
4. The worker writes batched events into PostgreSQL.
5. Controlled retraining reads from PostgreSQL as the single source of truth.
