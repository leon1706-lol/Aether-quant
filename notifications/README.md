# notifications

Owns Telegram alerting (V2-19). Pure/IO/worker split, matching `performance/`
and `retraining/`:

- `telegram_alerts.py` (pure) — `should_alert_trigger()` (severity gate),
  `format_trigger_alert()`, `format_session_summary_alert()`. Renders fields
  `performance/triggers.py` and `experience/observation_metrics.py` already
  computed; recomputes nothing.
- `postgres_telegram.py` (IO) — embedded DDL for `telegram_alert_watermark`
  (one row per channel: `"triggers"`, `"session_summary"`), plus
  `fetch_session_summaries_since()`, a defensive read of `experience_events`
  (owned by `experience/postgres_worker.py`) for `event_type="session_summary"`
  rows. Trigger fetching is **not** reimplemented here — `telegram_worker.py`
  imports `fetch_triggers_since()` directly from
  `performance.postgres_triggers`.
- `telegram_client.py` (IO, injectable) — thin Telegram Bot API wrapper.
  `send_message()` never raises; deferred `import requests` inside the call
  (mirrors `experience/redis_queue.py`'s deferred `import redis`). Bot
  token/chat id come only from `AETHER_TELEGRAM_BOT_TOKEN`/
  `AETHER_TELEGRAM_CHAT_ID` env vars — never in `config.json`, never
  hardcoded.
- `telegram_worker.py` — standalone worker (`python -m
  notifications.telegram_worker [--once]`) polling two independent,
  watermark-gated channels every `phase_v2.telegram.worker.poll_interval_seconds`:
  - **Triggers**: every `performance_triggers` row at or above
    `phase_v2.telegram.min_severity_for_trigger_alert` becomes a Telegram
    message. Because this polls *all* trigger types (not just
    `drawdown_trigger`), risk-lock activation, regime shifts, liquidity
    rejections, Sharpe/win-rate/confidence degradation and all five
    topology triggers are alerted for free — no extra instrumentation.
  - **Session summaries**: `main.py` pushes one `event_type="session_summary"`
    experience event per session rollover (see
    `experience/redis_queue.py::build_session_summary_event()`), built from
    `experience/observation_metrics.py::compute_observation_summary()`. This
    worker turns each new one into a quick post-market-close performance
    digest.
  - An unreachable Telegram API never stalls a channel's watermark — sends
    are attempted best-effort per row, and the watermark always advances to
    the newest row's `created_at` regardless of individual send failures.

Docker: `telegram-worker` service in `docker-compose.yml`, running from
the single consolidated `aether-quant-engine` image (the same build every
other service — the app and every other worker — shares; see
`requirements/README.md`), depends only on `postgres` (no Redis — this
worker never touches the experience stream directly).

Secrets: `AETHER_TELEGRAM_BOT_TOKEN` / `AETHER_TELEGRAM_CHAT_ID`, set via a
local `.env` (see `.env.compose.example`) — never committed, never placed in
`config.json`.
