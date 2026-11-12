"""execution/accounts_io.py (V6.6.5, #349)."""

from __future__ import annotations

import json

import pytest

from execution.accounts_io import accounts_file, load_accounts, requested_account_id


def test_missing_file_is_the_default_alone(tmp_path, monkeypatch):
    monkeypatch.delenv("AQ_ACCOUNTS_FILE", raising=False)
    assert [account.id for account in load_accounts(tmp_path)] == ["default"]
    assert accounts_file(tmp_path) == tmp_path / "accounts.json"


def test_the_variable_names_the_file_and_an_invalid_file_raises(tmp_path, monkeypatch):
    registry = tmp_path / "elsewhere.json"
    registry.write_text(json.dumps({"accounts": [{"id": "b", "broker": "paper"}]}), encoding="utf-8")
    monkeypatch.setenv("AQ_ACCOUNTS_FILE", str(registry))
    assert [account.id for account in load_accounts(tmp_path)] == ["default", "b"]
    registry.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_accounts(tmp_path)


def test_the_requested_id_comes_from_the_environment_then_the_parameter(monkeypatch):
    monkeypatch.delenv("AQ_ACCOUNT", raising=False)
    assert requested_account_id(None) == "" and requested_account_id(" b ") == "b"
    monkeypatch.setenv("AQ_ACCOUNT", "a")
    assert requested_account_id("b") == "a"
