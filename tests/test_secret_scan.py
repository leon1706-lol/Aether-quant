"""Tests for execution/secret_scan.py — the `aq secrets-check` detection.

Pins that: the real all-empty lean.json passes; a populated secret field is
caught; the returned list is field NAMES; and real .env files are distinguished
from the committed *.example templates.
"""

from execution.secret_scan import (
    find_populated_secret_fields,
    is_secret_field,
    is_tracked_env_secret,
)


def test_is_secret_field_matches_suffixes_and_exact():
    assert is_secret_field("polygon-api-key")
    assert is_secret_field("binance-api-secret")
    assert is_secret_field("ib-password")
    assert is_secret_field("ib-account")
    assert is_secret_field("charles-schwab-refresh-token")
    assert is_secret_field("nasdaq-auth-token")


def test_is_secret_field_ignores_non_secret_fields():
    assert not is_secret_field("data-folder")
    assert not is_secret_field("ib-trading-mode")
    assert not is_secret_field("live-data-port")
    assert not is_secret_field("oanda-environment")


def test_find_populated_secret_fields_empty_when_all_blank():
    template = {"ib-password": "", "polygon-api-key": "", "data-folder": "data"}

    assert find_populated_secret_fields(template) == []


def test_find_populated_secret_fields_flags_nonempty_secrets_only():
    config = {
        "ib-password": "hunter2",
        "polygon-api-key": "pk_live_abc",
        "ib-trading-mode": "live",  # not a secret field
        "data-folder": "data",
    }

    assert find_populated_secret_fields(config) == ["ib-password", "polygon-api-key"]


def test_find_populated_secret_fields_ignores_whitespace_only():
    assert find_populated_secret_fields({"ib-password": "   "}) == []


def test_is_tracked_env_secret_distinguishes_real_env_from_examples():
    assert is_tracked_env_secret(".env") is True
    assert is_tracked_env_secret(".env.live") is True
    assert is_tracked_env_secret(".env.compose") is True
    assert is_tracked_env_secret(".env.compose.example") is False
    assert is_tracked_env_secret(".env.live.example") is False
    assert is_tracked_env_secret("config.json") is False


def test_is_tracked_env_secret_handles_paths():
    assert is_tracked_env_secret("some/dir/.env.live") is True
    assert is_tracked_env_secret("some\\dir\\.env.live.example") is False
