"""Thin, injectable Telegram Bot API client (V2-19).

Fire-and-forget, mirroring experience/redis_queue.py's ExperienceQueue: any
failure (missing credentials, network error, non-2xx response) is caught
and logged at WARNING, send_message() never raises. The `requests` import is
deferred inside send_message() so importing this module doesn't hard-require
`requests` when a _send_fn is injected (tests only).
"""

from __future__ import annotations

import logging
import os
from typing import Callable

logger = logging.getLogger(__name__)

_SEND_MESSAGE_URL = "https://api.telegram.org/bot{token}/sendMessage"
_REQUEST_TIMEOUT_SECONDS = 10


class TelegramClient:
    """Sends plain-text messages to a single Telegram chat.

    Parameters
    ----------
    bot_token : Telegram bot token; overridden by AETHER_TELEGRAM_BOT_TOKEN env
    chat_id   : Telegram chat id; overridden by AETHER_TELEGRAM_CHAT_ID env
    _send_fn  : injected callable(text) -> bool for test injection — when
                provided, send_message() never imports/calls `requests`.
    """

    def __init__(
        self,
        *,
        bot_token: str = "",
        chat_id: str = "",
        _send_fn: Callable[[str], bool] | None = None,
    ) -> None:
        self.bot_token = os.environ.get("AETHER_TELEGRAM_BOT_TOKEN", bot_token)
        self.chat_id = os.environ.get("AETHER_TELEGRAM_CHAT_ID", chat_id)
        self._send_fn = _send_fn

    def send_message(self, text: str) -> bool:
        """Send `text` to the configured chat. Never raises.

        Returns True on success, False on any failure (missing
        token/chat_id, network error, non-2xx response).
        """
        if self._send_fn is not None:
            try:
                return bool(self._send_fn(text))
            except Exception as exc:
                logger.warning("TelegramClient._send_fn failed: %s", exc)
                return False

        if not self.bot_token or not self.chat_id:
            logger.warning("TelegramClient: missing bot_token/chat_id — message not sent.")
            return False

        try:
            import requests  # deferred — not always installed outside the telegram worker

            response = requests.post(
                _SEND_MESSAGE_URL.format(token=self.bot_token),
                json={"chat_id": self.chat_id, "text": text},
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            if response.status_code >= 300:
                logger.warning(
                    "TelegramClient.send_message: non-2xx response %d: %s",
                    response.status_code,
                    response.text[:200],
                )
                return False
            return True
        except Exception as exc:
            logger.warning("TelegramClient.send_message failed: %s", exc)
            return False
