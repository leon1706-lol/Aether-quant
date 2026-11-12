"""monitoring/auth.py (V6.6.5, #350)."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from monitoring.auth import Role, User, authorize, hash_token, make_user, new_token, parse_users, users_document, verify_token


def test_tokens_hash_and_verify():
    token = new_token()
    user = make_user("ops", Role.OPERATOR, token, accounts=["b", "a"])
    assert user.accounts == ("a", "b") and token not in repr(users_document([user]))
    assert verify_token([user], token) == user
    assert verify_token([user], token + "x") is None and verify_token([user], None) is None and verify_token([], token) is None
    assert hash_token(token, user.salt) == user.token_hash and len(user.salt) == 32


def test_roles_order_and_scope():
    viewer = make_user("v", Role.VIEWER, "t1")
    operator = make_user("o", Role.OPERATOR, "t2", accounts=["paper-a"])
    admin = make_user("a", Role.ADMIN, "t3")
    assert authorize(viewer, Role.VIEWER, auth_required=True) and not authorize(viewer, Role.OPERATOR, auth_required=True)
    assert authorize(operator, Role.OPERATOR, "paper-a", auth_required=True) and not authorize(operator, Role.OPERATOR, "default", auth_required=True)
    assert not authorize(operator, Role.ADMIN, "paper-a", auth_required=True) and authorize(admin, Role.ADMIN, "anything", auth_required=True)
    assert authorize(None, Role.VIEWER, auth_required=False) and not authorize(None, Role.OPERATOR, auth_required=False)
    assert not authorize(None, Role.VIEWER, auth_required=True)


def test_parse_round_trip_and_refusals():
    users = (make_user("a", Role.ADMIN, "t"), make_user("v", Role.VIEWER, "u", accounts=["x"]))
    assert parse_users(users_document(users)) == users
    with pytest.raises(ValueError):
        parse_users({"users": [{"name": "a", "role": "admin", "salt": "zz", "token_hash": "00"}]})
    with pytest.raises(ValueError):
        doc = users_document(users)
        parse_users({"users": doc["users"] + doc["users"][:1]})
    with pytest.raises(ValueError):
        Role.parse("root")
    with pytest.raises(ValueError):
        make_user("bad name!", Role.VIEWER, "t")
    assert parse_users({}) == ()


@settings(max_examples=300, deadline=None)
@given(st.sampled_from(list(Role)), st.sampled_from(list(Role)), st.lists(st.sampled_from(["*", "a", "b"]), max_size=3), st.sampled_from([None, "a", "b", "c"]), st.booleans())
def test_authorize_never_grants_above_the_users_role_or_scope(role, required, accounts, account, auth_required):
    user = User("u", role, "0" * 32, "0" * 64, tuple(accounts) or ("*",))
    granted = authorize(user, required, account, auth_required=auth_required)
    if granted and (auth_required or required != Role.VIEWER):
        assert int(role) >= int(required) and user.may_access(account)
    # monotone: a higher role is granted whenever a lower one is
    if granted:
        stronger = User("u", Role(max(int(role), int(required))), "0" * 32, "0" * 64, user.accounts)
        assert authorize(stronger, required, account, auth_required=auth_required)


# V6.6.5 mutation check (seed 665): the constants and the parse guard the first tests left open


def test_the_hash_is_pbkdf2_sha256_at_the_pinned_cost():
    import hashlib

    import monitoring.auth as auth

    salt = "00112233445566778899aabbccddeeff"
    assert auth.ITERATIONS == 200_000  # lowering it weakens every stored hash
    assert hash_token("token", salt) == hashlib.pbkdf2_hmac("sha256", b"token", bytes.fromhex(salt), 200_000).hex()


def test_a_user_record_cannot_be_changed_in_place():
    import dataclasses

    user = make_user("ops", Role.OPERATOR, "t")
    with pytest.raises(dataclasses.FrozenInstanceError):
        user.role = Role.ADMIN  # type: ignore[misc]


def test_a_new_token_carries_32_random_bytes():
    tokens = {new_token() for _ in range(20)}
    assert len(tokens) == 20 and all(len(token) == 43 for token in tokens)  # base64url of 32 bytes


@pytest.mark.parametrize(("salt", "digest"), [("0" * 32, "z" * 64), ("z" * 32, "0" * 64), ("0" * 31, "0" * 64), ("0" * 32, "0" * 63)])
def test_a_users_file_needs_both_a_valid_salt_and_a_valid_hash(salt, digest):
    with pytest.raises(ValueError, match="salt and token hash"):
        parse_users({"users": [{"name": "ops", "role": "operator", "salt": salt, "token_hash": digest}]})
