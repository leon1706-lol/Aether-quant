"""monitoring/auth_io.py (V6.6.5, #350)."""

from __future__ import annotations

import pytest

from monitoring import auth_io
from monitoring.auth import Role, make_user


def test_no_file_no_auth_and_the_variable_forces_it(tmp_path, monkeypatch):
    monkeypatch.setenv("AQ_USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.delenv("AQ_AUTH", raising=False)
    assert auth_io.load_users() == () and not auth_io.auth_required(())
    monkeypatch.setenv("AQ_AUTH", "required")
    assert auth_io.auth_required(())


def test_save_and_load(tmp_path, monkeypatch):
    monkeypatch.setenv("AQ_USERS_FILE", str(tmp_path / "nested" / "users.json"))
    users = (make_user("a", Role.ADMIN, "token-a"),)
    path = auth_io.save_users(users)
    assert path.exists() and "token-a" not in path.read_text(encoding="utf-8")
    assert auth_io.load_users() == users and auth_io.auth_required(users)


def test_an_invalid_file_raises_rather_than_opening_the_api(tmp_path, monkeypatch):
    path = tmp_path / "users.json"
    path.write_text("{broken", encoding="utf-8")
    monkeypatch.setenv("AQ_USERS_FILE", str(path))
    with pytest.raises(ValueError):
        auth_io.load_users()
