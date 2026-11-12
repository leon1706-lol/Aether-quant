"""Users, roles and tokens for the API and dashboard (V6.6.5, #350). Pure: no file, no clock, no network.

Three roles, each including the one below it: a **viewer** reads every page; an **operator** may also lock trading on an
account (the manual trade lock); an **admin** may also unlock it. A user can be scoped to some accounts or to all (`*`).
Tokens are random (`secrets.token_urlsafe(32)`), shown once when created, and stored only as a salted PBKDF2-SHA256 hash;
a token is checked in constant time against every user, so the time taken says nothing about which one matched.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

__all__ = ["Role", "User", "ITERATIONS", "new_token", "new_salt", "hash_token", "make_user", "verify_token", "authorize", "parse_users", "users_document"]

ITERATIONS = 200_000
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,63}$")


class Role(IntEnum):
    """Ordered roles: a viewer reads, an operator may also lock trading, an admin may also unlock it."""

    VIEWER = 1
    OPERATOR = 2
    ADMIN = 3

    @classmethod
    def parse(cls, text: str) -> Role:
        try:
            return cls[str(text).upper()]
        except KeyError:
            raise ValueError(f"unknown role {text!r} (viewer, operator, admin)") from None


@dataclass(frozen=True)
class User:
    """`accounts` is `("*",)` for every account, else the ids this user may act on."""

    name: str
    role: Role
    salt: str
    token_hash: str
    accounts: tuple[str, ...] = ("*",)

    def may_access(self, account: str | None) -> bool:
        return account is None or "*" in self.accounts or account in self.accounts


def new_token() -> str:
    """A fresh random bearer token (32 bytes, URL-safe); shown once, stored only as a hash."""
    return secrets.token_urlsafe(32)


def new_salt() -> str:
    """A fresh random 16-byte salt, hex-encoded."""
    return secrets.token_hex(16)


def hash_token(token: str, salt: str, iterations: int = ITERATIONS) -> str:
    """PBKDF2-SHA256 of a token under a salt, hex-encoded."""
    return hashlib.pbkdf2_hmac("sha256", str(token).encode("utf-8"), bytes.fromhex(salt), int(iterations)).hex()


def make_user(name: str, role: Role, token: str, *, accounts: Iterable[str] = ("*",), salt: str | None = None) -> User:
    """A user whose token is stored salted and hashed; `accounts` scopes it (`*` for all). Raises on a bad name."""
    if not _NAME_RE.match(str(name)):
        raise ValueError(f"bad user name {name!r}")
    chosen = salt or new_salt()
    scope = tuple(sorted({str(account) for account in accounts})) or ("*",)
    return User(str(name), Role(role), chosen, hash_token(token, chosen), scope)


def verify_token(users: Iterable[User], token: str | None) -> User | None:
    """The user whose token this is, or None. Every user is checked, whatever matched first."""
    if not token:
        return None
    found: User | None = None
    for user in users:
        if hmac.compare_digest(hash_token(token, user.salt), user.token_hash) and found is None:
            found = user
    return found


def authorize(user: User | None, required: Role, account: str | None = None, *, auth_required: bool) -> bool:
    """May `user` do something that needs `required` on `account`? With auth off, reads are open and nothing that writes
    is: a write always needs an authenticated user of the right role and scope."""
    if not auth_required and required == Role.VIEWER:
        return True
    if user is None:
        return False
    return int(user.role) >= int(required) and user.may_access(account)


def parse_users(doc: Mapping[str, Any]) -> tuple[User, ...]:
    """`{"users": [{"name", "role", "salt", "token_hash", "accounts"}]}` to users. Raises ValueError on a bad or duplicate entry."""
    rows = doc.get("users", []) if isinstance(doc, Mapping) else []
    users: list[User] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        name = str(row.get("name", ""))
        if not _NAME_RE.match(name) or name in seen:
            raise ValueError(f"bad or duplicate user {name!r}")
        seen.add(name)
        salt, digest = str(row.get("salt", "")), str(row.get("token_hash", ""))
        if not re.fullmatch(r"[0-9a-f]{32}", salt) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"user {name!r} has no valid salt and token hash")
        accounts = tuple(str(account) for account in row.get("accounts", ["*"])) or ("*",)
        users.append(User(name, Role.parse(str(row.get("role", "viewer"))), salt, digest, accounts))
    return tuple(users)


def users_document(users: Iterable[User]) -> dict[str, Any]:
    """The JSON the users file holds (hashes only)."""
    return {"users": [{"name": user.name, "role": user.role.name.lower(), "salt": user.salt, "token_hash": user.token_hash, "accounts": list(user.accounts)}
                      for user in users]}
