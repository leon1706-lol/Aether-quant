"""The users file behind `monitoring/auth.py` (V6.6.5, #350): `$AQ_USERS_FILE`, else `state/users.json` (gitignored).

Auth is required when the file lists at least one user, or when `AQ_AUTH=required`; with neither, the API reads stay open
exactly as before and nothing can write. The file holds salted hashes only, and is written owner-only where the OS allows.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from json_safety import atomic_write_text
from monitoring.auth import User, parse_users, users_document

__all__ = ["users_file", "load_users", "save_users", "auth_required"]

ROOT_DIR = Path(__file__).resolve().parent.parent


def users_file() -> Path:
    return Path(os.environ.get("AQ_USERS_FILE") or (ROOT_DIR / "state" / "users.json"))


def load_users() -> tuple[User, ...]:
    """The users, or none when the file is missing. An unreadable or invalid file raises: a broken users file must not
    quietly open the API."""
    path = users_file()
    if not path.exists():
        return ()
    return parse_users(json.loads(path.read_text(encoding="utf-8")))


def save_users(users: tuple[User, ...]) -> Path:
    path = users_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(users_document(users), indent=1) + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # Windows: the ACL of the user's profile applies
    return path


def auth_required(users: tuple[User, ...]) -> bool:
    return bool(users) or os.environ.get("AQ_AUTH", "").lower() == "required"
