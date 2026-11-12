"""execution/secrets_io.py (V6.6.5, #348): the real environment, secret files and keyring behind the resolver."""

from __future__ import annotations

import pytest

from execution import secrets_io


def test_secret_env_matches_os_environ_get(monkeypatch):
    monkeypatch.setattr(secrets_io, "keyring_get", lambda service, user: None)
    monkeypatch.delenv("AETHER_REDIS_URL", raising=False)
    assert secrets_io.secret_env("REDIS_URL", "redis://default") == "redis://default"
    monkeypatch.setenv("AETHER_REDIS_URL", "")
    assert secrets_io.secret_env("REDIS_URL", "redis://default") == ""  # set but empty reads as empty, as before
    monkeypatch.setenv("AETHER_REDIS_URL", "redis://env")
    assert secrets_io.secret_env("REDIS_URL", "redis://default") == "redis://env"


def test_a_file_named_by_the_file_variable_is_read(tmp_path, monkeypatch):
    monkeypatch.setattr(secrets_io, "keyring_get", lambda service, user: None)
    secret_file = tmp_path / "dsn"
    secret_file.write_text("postgresql://file\n", encoding="utf-8")
    monkeypatch.setenv("AETHER_POSTGRES_DSN_FILE", str(secret_file))
    monkeypatch.setenv("AETHER_POSTGRES_DSN", "postgresql://env")
    assert secrets_io.secret_env("POSTGRES_DSN") == "postgresql://file"
    status = {row["name"]: row for row in secrets_io.all_secret_status()}
    assert status["POSTGRES_DSN"]["stored_safely"] is True and "postgresql://file" not in repr(status)


def test_keyring_absent_is_not_configured(monkeypatch):
    monkeypatch.setattr(secrets_io, "_keyring", lambda: None)
    assert secrets_io.keyring_get("aether-quant", "IB_PASSWORD") is None
    assert secrets_io.keyring_delete("IB_PASSWORD") is False
    with pytest.raises(RuntimeError):
        secrets_io.keyring_set("IB_PASSWORD", "x")


def test_keyring_round_trip_with_a_fake_backend(monkeypatch):
    store: dict[tuple[str, str], str] = {}

    class Fake:
        @staticmethod
        def get_password(service, user):
            return store.get((service, user))

        @staticmethod
        def set_password(service, user, value):
            store[(service, user)] = value

        @staticmethod
        def delete_password(service, user):
            del store[(service, user)]

    monkeypatch.setattr(secrets_io, "_keyring", lambda: Fake)
    monkeypatch.delenv("AETHER_PAPER2_COINBASE_API_KEY", raising=False)
    secrets_io.keyring_set("COINBASE_API_KEY", "kr-key", "paper2")
    assert store == {("aether-quant", "paper2/COINBASE_API_KEY"): "kr-key"}
    assert secrets_io.secret_env("COINBASE_API_KEY", account_id="paper2") == "kr-key"
    assert secrets_io.keyring_delete("COINBASE_API_KEY", "paper2") and not store
