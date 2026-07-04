"""Tests for notifications.telegram_client — V2-19.

Conventions: no test classes, module-level helpers, no real network calls —
either the _send_fn injection point is used, or requests.post is patched.
"""

from unittest.mock import MagicMock, patch

from notifications.telegram_client import TelegramClient


def test_send_message_uses_injected_send_fn():
    calls = []

    def fake_send(text: str) -> bool:
        calls.append(text)
        return True

    client = TelegramClient(bot_token="t", chat_id="c", _send_fn=fake_send)
    assert client.send_message("hello") is True
    assert calls == ["hello"]


def test_send_message_send_fn_exception_returns_false_not_raise():
    def failing_send(text: str) -> bool:
        raise RuntimeError("boom")

    client = TelegramClient(bot_token="t", chat_id="c", _send_fn=failing_send)
    assert client.send_message("hello") is False


def test_send_message_missing_credentials_returns_false():
    client = TelegramClient(bot_token="", chat_id="")
    assert client.send_message("hello") is False


def test_send_message_posts_to_telegram_api_with_credentials():
    client = TelegramClient(bot_token="tok", chat_id="123")
    response_mock = MagicMock(status_code=200)
    with patch("requests.post", return_value=response_mock) as post_mock:
        assert client.send_message("hi there") is True

    args, kwargs = post_mock.call_args
    assert "tok" in args[0]
    assert kwargs["json"] == {"chat_id": "123", "text": "hi there"}


def test_send_message_non_2xx_response_returns_false():
    client = TelegramClient(bot_token="tok", chat_id="123")
    response_mock = MagicMock(status_code=403, text="Forbidden")
    with patch("requests.post", return_value=response_mock):
        assert client.send_message("hi there") is False


def test_send_message_network_exception_returns_false():
    client = TelegramClient(bot_token="tok", chat_id="123")
    with patch("requests.post", side_effect=OSError("network down")):
        assert client.send_message("hi there") is False


def test_env_vars_override_constructor_defaults(monkeypatch):
    monkeypatch.setenv("AETHER_TELEGRAM_BOT_TOKEN", "env-token")
    monkeypatch.setenv("AETHER_TELEGRAM_CHAT_ID", "env-chat")
    client = TelegramClient(bot_token="ctor-token", chat_id="ctor-chat")
    assert client.bot_token == "env-token"
    assert client.chat_id == "env-chat"
