"""execution/secrets.py (V6.6.5, #348): lookup order, accounts, and a value that never shows. The real sources: tests/test_secrets_io.py."""

from __future__ import annotations

import pickle

import pytest

from execution.secrets import SecretValue, default_refs, env_prefix, parse_ref, redact, resolve_secret, secret_status


def test_lookup_order_is_file_var_then_docker_secret_then_env_then_keyring():
    refs = [str(ref) for ref in default_refs("IB_PASSWORD", env={"AETHER_IB_PASSWORD_FILE": "/tmp/pw"})]
    assert refs == ["file:/tmp/pw", "file:/run/secrets/aether_ib_password", "env:AETHER_IB_PASSWORD", "keyring:aether-quant/IB_PASSWORD"]
    assert [str(ref) for ref in default_refs("IB_PASSWORD", "acct-b")][1:] == [
        "env:AETHER_ACCT_B_IB_PASSWORD", "keyring:aether-quant/acct-b/IB_PASSWORD"]


def test_first_match_wins_and_a_file_beats_the_environment():
    files = {"/run/secrets/aether_postgres_dsn": "postgresql://from-file\n"}
    resolved = resolve_secret("POSTGRES_DSN", env={"AETHER_POSTGRES_DSN": "postgresql://from-env"}, read_file=files.get, keyring_get=lambda s, u: "from-keyring")
    assert resolved.value.reveal() == "postgresql://from-file" and resolved.source == "file:/run/secrets/aether_postgres_dsn"
    env_only = resolve_secret("POSTGRES_DSN", env={"AETHER_POSTGRES_DSN": "postgresql://from-env"}, read_file=lambda p: None, keyring_get=lambda s, u: None)
    assert env_only.value.reveal() == "postgresql://from-env" and env_only.source == "env:AETHER_POSTGRES_DSN"
    keyring = resolve_secret("POSTGRES_DSN", env={}, read_file=lambda p: None, keyring_get=lambda s, u: "kr" if (s, u) == ("aether-quant", "POSTGRES_DSN") else None)
    assert keyring.value.reveal() == "kr"
    nothing = resolve_secret("POSTGRES_DSN", env={}, read_file=lambda p: None)
    assert nothing.value is None and nothing.source is None


def test_a_failing_reader_is_a_missing_source():
    def boom(*args):
        raise OSError("locked")

    resolved = resolve_secret("IB_PASSWORD", env={"AETHER_IB_PASSWORD": "pw"}, read_file=boom, keyring_get=boom)
    assert resolved.value.reveal() == "pw"


def test_accounts_never_share_a_credential():
    env = {"AETHER_IB_PASSWORD": "default-pw", "AETHER_LIVE1_IB_PASSWORD": "live1-pw"}
    assert resolve_secret("IB_PASSWORD", account_id="live1", env=env, read_file=lambda p: None).value.reveal() == "live1-pw"
    assert resolve_secret("IB_PASSWORD", account_id="paper2", env=env, read_file=lambda p: None).value is None
    assert env_prefix(None) == env_prefix("default") == "AETHER_"
    with pytest.raises(ValueError):
        env_prefix("Bad Account!")


def test_a_secret_value_never_shows_itself():
    value = SecretValue("hunter2-very-secret")
    for text in (repr(value), str(value), f"{value}", f"{value!s}", "%s" % value):
        assert "hunter2" not in text
    assert value.reveal() == "hunter2-very-secret" and value == SecretValue("hunter2-very-secret") and value != SecretValue("other")
    with pytest.raises(TypeError):
        pickle.dumps(value)


def test_refs_parse_and_literals_are_refused():
    assert str(parse_ref("env:AETHER_X")) == "env:AETHER_X"
    for bad in ("literal:abc", "abc", "env:", "http://x"):
        with pytest.raises(ValueError):
            parse_ref(bad)
    with pytest.raises(ValueError):
        default_refs("lower_case")


def test_redact_hides_values_longest_first_and_leaves_short_ones():
    out = redact("dsn postgresql://u:longpassword@h and longpassword and 12", [SecretValue("longpassword"), "postgresql://u:longpassword@h", "12"])
    assert "longpassword" not in out and out.count("***") == 2 and out.endswith("12")


def test_status_has_names_and_sources_never_values():
    rows = secret_status([
        resolve_secret("IB_PASSWORD", env={"AETHER_IB_PASSWORD": "pw-value-1"}, read_file=lambda p: None),
        resolve_secret("COINBASE_API_SECRET", env={}, read_file=lambda p: "cb-secret-value" if p.endswith("coinbase_api_secret") else None),
        resolve_secret("TELEGRAM_BOT_TOKEN", env={}, read_file=lambda p: None),
    ])
    assert "pw-value-1" not in repr(rows) and "cb-secret-value" not in repr(rows)
    assert [row["stored_safely"] for row in rows] == [False, True, False]
    assert [row["resolved"] for row in rows] == [True, True, False]


# V6.6.5 mutation check (seed 665): the boundaries the first tests left open


def test_redaction_hides_the_longest_secret_whole_first():
    assert redact("key=abcdef12345", ["abcd", "abcdef12345"]) == "key=***"
    assert redact("key=abcdef12345", [SecretValue("abcd"), SecretValue("abcdef12345")]) == "key=***"


def test_redaction_masks_four_characters_and_leaves_three():
    assert redact("pin 1234 and 567", ["1234", "567"]) == "pin *** and 567"


def test_refs_and_resolved_secrets_are_frozen():
    import dataclasses

    ref = parse_ref("env:AETHER_X")
    resolved = resolve_secret("REDIS_URL", env={"AETHER_REDIS_URL": "redis://x"}, read_file=lambda path: None)
    for record, field in ((ref, "target"), (resolved, "source")):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(record, field, "changed")


# V6.6.5 (#355, CodeQL py/clear-text-logging-sensitive-data): a URL logged without its password


@pytest.mark.parametrize(("url", "expected"), [
    ("redis://:sekret@redis:6379/0", "redis://:***@redis:6379/0"),
    ("postgresql://aether:pw@db:5432/aq", "postgresql://aether:***@db:5432/aq"),
    ("redis://user@host:6379", "redis://user@host:6379"),
    ("redis://localhost:6380/0", "redis://localhost:6380/0"),
    ("redis://host/path@x", "redis://host/path@x"),
    ("not a url", "not a url"),
])
def test_redact_url_masks_only_the_password(url, expected):
    from execution.secrets import redact_url

    assert redact_url(url) == expected
