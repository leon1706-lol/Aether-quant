# notifications

Telegram alerts.

- **`telegram_alerts.py` (pure):** the severity gate and message formats. Recomputes nothing, and null-safe.
- **`postgres_telegram.py`:** the watermark table and session-summary reads.
- **`telegram_client.py`:** a thin Bot API wrapper that never raises.
- **`telegram_worker.py`:** `python -m notifications.telegram_worker [--once]` polls two channels every `phase_v2.telegram.worker.poll_interval_seconds`:
  - **Triggers:** every `performance_triggers` row at or above `phase_v2.telegram.min_severity_for_trigger_alert`.
  - **Session summaries:** one digest per session rollover.

An unreachable Telegram never stalls a channel: the watermark always advances.

- **Docker:** the `telegram-worker` service, which needs only Postgres.
- **Secrets:** `AETHER_TELEGRAM_BOT_TOKEN` and `AETHER_TELEGRAM_CHAT_ID`, in a local `.env`. Never in `config.json`.
